"""Keep a multi-case showcase prompt inside the case the user actually picked.

Prompts that switch on ``{{current_case}}`` describe several companies and tell
the model to call functions this platform does not execute. Without a real
case value, retrieval mixes every knowledge file and the model prints the
shared "test finished" menu. This module is a no-op for every other prompt.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.core_models import ChatMessage, KnowledgeBaseDocument

CASE_TOKEN = "{{current_case}}"
MAIN_MENU = "main_menu"
CASE_CLOSER = "Режим тестирования текущего кейса успешно завершен"

_ROUTER_RE = re.compile(
    r'option\s+"(?P<option>\d+)"\s*,\s*or text\s+(?P<aliases>(?:"[^"]+"\s*,?\s*)+)\)'
    r"[^`\n]{0,120}`(?P<func>activate_[a-z0-9_]+)`",
    re.IGNORECASE,
)
_MODE_RE = re.compile(
    r'\{\{current_case\}\}\s*==\s*"(?P<case>[a-z0-9_]+)"',
    re.IGNORECASE,
)
_EXIT_RE = re.compile(r"(?<!\w)выйти(?!\w)", re.IGNORECASE)
_OPTION_RE = re.compile(r"^[0-9]{1,2}$")


@dataclass(frozen=True)
class CaseRoute:
    case_id: str
    option: str
    aliases: list[str]


@dataclass(frozen=True)
class ShowcaseTurn:
    active: bool
    case_id: str = ""
    prompt: str | None = None
    allowed_document_ids: list[str] | None = None
    lock: str = ""


def prompt_uses_cases(prompt: str | None) -> bool:
    return CASE_TOKEN in (prompt or "")


def parse_case_routes(prompt: str) -> list[CaseRoute]:
    case_ids = list(dict.fromkeys(match.group("case") for match in _MODE_RE.finditer(prompt)))
    routes: list[CaseRoute] = []
    seen: set[str] = set()
    for match in _ROUTER_RE.finditer(prompt):
        case_id = _case_id_for_function(match.group("func"), case_ids)
        if not case_id or case_id in seen:
            continue
        aliases = re.findall(r'"([^"]+)"', match.group("aliases"))
        routes.append(
            CaseRoute(
                case_id=case_id,
                option=match.group("option"),
                aliases=[alias.strip() for alias in aliases if alias.strip()],
            )
        )
        seen.add(case_id)
    return routes


def resolve_showcase_case(
    prompt: str,
    incoming_message: str,
    stored_case: str | None,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Return the case id for this turn. ``main_menu`` when nothing is selected."""
    routes = parse_case_routes(prompt)
    if user_requests_exit(incoming_message):
        return MAIN_MENU
    picked = match_case_selection(incoming_message, routes)
    if picked:
        return picked
    if stored_case:
        return stored_case
    inferred = infer_case_from_history(history or [], routes)
    if inferred:
        return inferred
    persona = infer_case_from_assistant(history or [], routes)
    if persona:
        return persona
    return MAIN_MENU


def user_requests_exit(text: str) -> bool:
    return _EXIT_RE.search(text or "") is not None


def match_case_selection(text: str, routes: list[CaseRoute]) -> str | None:
    folded = _normalize_choice(text)
    if not folded or not routes:
        return None
    if _OPTION_RE.fullmatch(folded):
        for route in routes:
            if route.option == folded:
                return route.case_id
        return None
    if len(folded) > 48:
        return None
    for route in routes:
        for alias in route.aliases:
            token = alias.casefold().strip()
            if not token:
                continue
            if folded == token or re.search(rf"(?<!\w){re.escape(token)}(?!\w)", folded):
                return route.case_id
    return None


def infer_case_from_history(
    history: list[dict[str, str]],
    routes: list[CaseRoute],
) -> str | None:
    case_id: str | None = None
    for item in history:
        content = str(item.get("content") or "")
        if item.get("role") != "user":
            continue
        if user_requests_exit(content):
            case_id = MAIN_MENU
            continue
        picked = match_case_selection(content, routes)
        if picked:
            case_id = picked
    return case_id


def infer_case_from_assistant(
    history: list[dict[str, str]],
    routes: list[CaseRoute],
) -> str | None:
    """Recover a case from the last in-character reply when the user never sent a number."""
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        text = str(item.get("content") or "")
        folded = text.casefold()
        if "режим тестирования" in folded or "выберите следующий кейс" in folded:
            continue
        for route in routes:
            for alias in route.aliases:
                token = alias.casefold()
                stems = [token]
                if len(token) >= 6:
                    stems.append(token[:-1])
                if any(len(stem) >= 5 and stem in folded for stem in stems):
                    return route.case_id
    return None


def apply_case_to_prompt(prompt: str, case_id: str) -> str:
    return prompt.replace(CASE_TOKEN, case_id or MAIN_MENU)


def case_lock_instruction(case_id: str) -> str:
    if case_id in {"", MAIN_MENU, "none"}:
        return (
            "CASE LOCK: current_case is main_menu. "
            "Offer the case list and wait for a choice. "
            "Do not role-play a company and do not use another company's facts."
        )
    return (
        f'CASE LOCK: current_case is "{case_id}". '
        "Stay in this company only. Ignore every other mode in the instructions. "
        "The user leaves this case only by writing «выйти». "
        "Do not end the test, do not say that testing is finished, and do not print the case menu. "
        "A booking, a price, or a symptom is not the end of the dialogue. "
        "Use only the knowledge for this case. Do not mention doctors, prices, or services from other cases. "
        "Do not paste a scripted greeting or copy an earlier reply. "
        "Answer the latest user message in your own words."
    )


def strip_unrequested_case_closer(text: str) -> str:
    index = (text or "").find("Режим тестирования")
    if index < 0:
        return (text or "").strip()
    return text[:index].strip()


def file_matches_case(file_name: str, case_id: str, aliases: list[str]) -> bool:
    name = (file_name or "").casefold()
    tokens = [part for part in case_id.casefold().split("_") if len(part) >= 4]
    tokens.extend(alias.casefold() for alias in aliases if len(alias) >= 4)
    return any(token in name for token in tokens)


async def load_showcase_case(db: AsyncSession, client_id: uuid.UUID) -> str | None:
    result = await db.execute(
        select(ChatMessage.payload)
        .where(ChatMessage.client_id == client_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(40)
    )
    for payload in result.scalars():
        if isinstance(payload, dict) and payload.get("showcase_case"):
            return str(payload["showcase_case"])
    return None


async def remember_showcase_case(
    db: AsyncSession,
    client_id: uuid.UUID,
    case_id: str,
) -> None:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.client_id == client_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return
    payload = dict(row.payload or {})
    if payload.get("showcase_case") == case_id:
        return
    payload["showcase_case"] = case_id
    row.payload = payload
    flag_modified(row, "payload")


async def allowed_documents_for_case(
    db: AsyncSession,
    bot_id: uuid.UUID,
    case_id: str,
    routes: list[CaseRoute],
) -> list[str] | None:
    """Document ids for the active case.

    An empty list means "do not retrieve" (the main menu). ``None`` means the
    filenames did not match, so the caller should keep the normal search.
    """
    if case_id in {"", MAIN_MENU, "none"}:
        return []
    route = next((item for item in routes if item.case_id == case_id), None)
    aliases = list(route.aliases) if route is not None else []
    result = await db.execute(
        select(KnowledgeBaseDocument.id, KnowledgeBaseDocument.file_name).where(
            KnowledgeBaseDocument.bot_id == bot_id,
            KnowledgeBaseDocument.deleted_at.is_(None),
            KnowledgeBaseDocument.is_context_active.is_(True),
        )
    )
    matched = [
        str(document_id)
        for document_id, file_name in result.all()
        if file_matches_case(str(file_name or ""), case_id, aliases)
    ]
    if not matched:
        return None
    return matched


async def prepare_showcase_turn(
    db: AsyncSession,
    *,
    bot_id: uuid.UUID | None,
    client_id: uuid.UUID | None,
    prompt: str | None,
    incoming_message: str,
    history: list[dict[str, str]],
) -> ShowcaseTurn:
    raw = (prompt or "").strip()
    if not prompt_uses_cases(raw):
        return ShowcaseTurn(active=False, prompt=prompt)
    stored = None
    if client_id is not None:
        stored = await load_showcase_case(db, client_id)
    case_id = resolve_showcase_case(raw, incoming_message, stored, history)
    routes = parse_case_routes(raw)
    allowed: list[str] | None = [] if case_id in {MAIN_MENU, "none"} else None
    if bot_id is not None and case_id not in {MAIN_MENU, "none"}:
        allowed = await allowed_documents_for_case(db, bot_id, case_id, routes)
    if client_id is not None:
        await remember_showcase_case(db, client_id, case_id)
    return ShowcaseTurn(
        active=True,
        case_id=case_id,
        prompt=apply_case_to_prompt(raw, case_id),
        allowed_document_ids=allowed,
        lock=case_lock_instruction(case_id),
    )


def _case_id_for_function(function_name: str, case_ids: list[str]) -> str | None:
    function = function_name.casefold()
    for case_id in sorted(case_ids, key=len, reverse=True):
        token = case_id.split("_", 1)[0].casefold()
        if token and token in function:
            return case_id
    return None


def _normalize_choice(text: str) -> str:
    folded = (text or "").strip().casefold()
    folded = folded.replace("️⃣", "")
    folded = folded.strip(" .)\t")
    return folded
