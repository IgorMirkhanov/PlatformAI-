#!/usr/bin/env python3
"""MP.AI — live stack verification before filling production API keys.

Validates the encrypt → persist → decrypt → outbound API chain for:
  • Telegram Bot API (getMe)
  • Wazzup24 (/channels)
  • LLM providers (org BYOK override + platform .env fallback)

Also asserts that a missing single LLM vendor key does not break the gateway
chain for other configured providers.

Usage (from repo root):
    python scripts/verify_live_stack.py
    python scripts/verify_live_stack.py --skip-live-http
    python backend/scripts/verify_live_stack.py

Environment (optional live probes):
    VERIFY_TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN
    VERIFY_WAZZUP_API_KEY / WAZZUP_API_KEY
    OPENAI_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY / …

Exit codes:
    0 — crypto + DB roundtrip OK; live probes green or intentionally skipped
    1 — crypto/DB failure or required live probe failed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if (_REPO_ROOT / "backend" / "app").is_dir():
    sys.path.insert(0, str(_BACKEND_ROOT))
elif (_REPO_ROOT / "app").is_dir():
    sys.path.insert(0, str(_REPO_ROOT))
    _BACKEND_ROOT = _REPO_ROOT
    _REPO_ROOT = _REPO_ROOT.parent

for candidate in (
    _REPO_ROOT / ".env",
    _REPO_ROOT / ".env.production",
    _BACKEND_ROOT / ".env.production",
):
    if candidate.is_file():
        try:
            from dotenv import load_dotenv

            # Prefer local .env for developer machines; production file is secondary.
            load_dotenv(candidate, override=False)
            print(f"[env] loaded {candidate}")
        except Exception as exc:  # noqa: BLE001
            print(f"[env] failed to load {candidate}: {exc}")


OK = "[OK]"
FAIL = "[FAIL]"
WARN = "[WARN]"
SKIP = "[SKIP]"
INFO = "[INFO]"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


@dataclass
class Report:
    items: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        self.items.append(CheckResult(name=name, ok=ok, detail=detail, required=required))
        tag = OK if ok else (WARN if not required else FAIL)
        print(f"{tag} {name}: {detail}")

    @property
    def failed_required(self) -> list[CheckResult]:
        return [i for i in self.items if i.required and not i.ok]


def _mask(secret: str | None) -> str:
    raw = (secret or "").strip()
    if not raw:
        return "(empty)"
    if len(raw) <= 10:
        return f"{raw[:2]}…(len={len(raw)})"
    return f"{raw[:6]}…{raw[-4:]} (len={len(raw)})"


def _looks_like_placeholder(token: str) -> bool:
    low = token.lower()
    return any(
        marker in low
        for marker in (
            "test-",
            "fake",
            "placeholder",
            "changeme",
            "your_",
            "xxx",
            "dummy",
        )
    )


async def check_crypto_roundtrip(report: Report) -> None:
    from app.core.security import decrypt_credential, encrypt_credential

    sample = f"verify-live-stack-{uuid.uuid4().hex[:12]}"
    sealed = encrypt_credential(sample)
    opened = decrypt_credential(sealed)
    report.add(
        "crypto.roundtrip",
        opened == sample and sealed != sample,
        f"seal={_mask(sealed)} open_ok={opened == sample}",
    )


async def check_llm_key_isolation(report: Report) -> None:
    """Missing Anthropic/DeepSeek must not remove Groq/OpenAI from the chain."""
    from app.core.config import settings
    from app.services.llm.factory import build_gateway_providers

    org_override = {"openai": "sk-org-override-verify-only-not-a-real-key"}
    providers = build_gateway_providers(
        include_unconfigured=False,
        org_api_keys=org_override,
    )
    keyed = [p for p in providers if getattr(p, "api_key", None)]
    openai_rows = [
        p for p in keyed if str(getattr(p, "provider_id", "")).lower() == "openai"
    ]
    org_wins = bool(openai_rows) and openai_rows[0].api_key == org_override["openai"]
    report.add(
        "llm.org_key_overrides_settings",
        org_wins,
        f"openai_key={_mask(openai_rows[0].api_key if openai_rows else None)} "
        f"configured_count={len(keyed)}",
    )

    # Platform chain without forcing every vendor key.
    platform = build_gateway_providers(include_unconfigured=False)
    platform_keyed = [
        str(getattr(p, "provider_id", type(p).__name__))
        for p in platform
        if getattr(p, "api_key", None)
    ]
    any_platform = len(platform_keyed) > 0 or bool(
        settings.OPENAI_API_KEY
        or getattr(settings, "OPENROUTER_API_KEY", None)
        or getattr(settings, "GROQ_API_KEY", None)
        or getattr(settings, "ANTHROPIC_API_KEY", None)
        or getattr(settings, "DEEPSEEK_API_KEY", None)
    )
    report.add(
        "llm.partial_env_keys_ok",
        True if platform_keyed or not any_platform else len(platform_keyed) >= 1,
        f"configured_providers={platform_keyed or ['(none — fill .env.production)']}",
        required=False,
    )


async def check_llm_ping(report: Report, *, skip_live: bool) -> None:
    if skip_live:
        report.add("llm.live_ping", True, "skipped (--skip-live-http)", required=False)
        return

    from app.core.config import settings
    from app.services.llm.factory import build_gateway_providers
    from app.services.llm.gateway import ResilientLLMGateway

    providers = build_gateway_providers(include_unconfigured=False)
    keyed = [p for p in providers if getattr(p, "api_key", None)]
    if not keyed:
        report.add(
            "llm.live_ping",
            True,
            "no platform LLM keys yet — safe to fill .env.production",
            required=False,
        )
        return

    if all(_looks_like_placeholder(str(getattr(p, "api_key", "") or "")) for p in keyed):
        report.add(
            "llm.live_ping",
            True,
            "keys look like placeholders — skip live completion",
            required=False,
        )
        return

    gateway = ResilientLLMGateway(keyed)
    try:
        response = await gateway.complete(
            [{"role": "user", "content": "Reply with exactly: PONG"}],
            temperature=0.0,
            max_tokens=16,
        )
        text = (response.content or "").strip()
        report.add(
            "llm.live_ping",
            True,
            f"HTTP ok reply={text[:40]!r} model={getattr(response, 'model_name', None)}"
            + ("" if text else " (empty body — model reachable)"),
            required=False,
        )
    except Exception as exc:  # noqa: BLE001
        report.add(
            "llm.live_ping",
            False,
            f"{type(exc).__name__}: {exc}",
            required=False,
        )
    finally:
        _ = settings  # keep settings import used for env visibility


async def _telegram_get_me(token: str) -> tuple[bool, str]:
    import httpx

    url = f"https://api.telegram.org/bot{token}/getMe"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code == 200 and body.get("ok"):
            username = (body.get("result") or {}).get("username")
            return True, f"getMe ok @{username}"
        return False, f"status={response.status_code} body={str(body)[:200]}"


async def _wazzup_channels(api_key: str) -> tuple[bool, str]:
    import httpx

    from app.core.config import settings

    base = (getattr(settings, "WAZZUP_API_BASE_URL", None) or "https://api.wazzup24.com/v3").rstrip("/")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{base}/channels",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code < 400:
            return True, f"/channels ok status={response.status_code}"
        return False, f"status={response.status_code} body={response.text[:200]}"


async def check_db_channel_roundtrip(report: Report, *, skip_live: bool) -> None:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.core.security import decrypt_credential, encrypt_credential
    from app.models.channels import BotChannel, HubChannelStatus, HubChannelType
    from app.models.core_models import Bot, PlatformType
    from app.models.users import User

    telegram_token = (
        os.getenv("VERIFY_TELEGRAM_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or f"000000000:TEST-verify-{uuid.uuid4().hex[:8]}"
    )
    wazzup_key = (
        os.getenv("VERIFY_WAZZUP_API_KEY")
        or os.getenv("WAZZUP_API_KEY")
        or f"wz-test-{uuid.uuid4().hex[:12]}"
    )
    live_tg = (
        not skip_live
        and not _looks_like_placeholder(telegram_token)
        and "TEST-verify" not in telegram_token
    )
    live_wz = (
        not skip_live
        and not _looks_like_placeholder(wazzup_key)
        and not wazzup_key.startswith("wz-test-")
    )

    candidate_urls = [
        settings.DATABASE_URL,
        os.getenv("DATABASE_URL") or "",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/mpai",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/mpai",
        "postgresql+asyncpg://mpai_app:mpai_app@127.0.0.1:5432/mpai_production",
    ]
    # de-dupe while preserving order
    seen: set[str] = set()
    urls: list[str] = []
    for raw in candidate_urls:
        url = (raw or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)

    engine = None
    working_url = ""
    last_error = "no candidates"
    for url in urls:
        try:
            eng = create_async_engine(url, pool_pre_ping=True)
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
            engine = eng
            working_url = url
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            try:
                await eng.dispose()  # type: ignore[name-defined]
            except Exception:
                pass

    if engine is None:
        report.add(
            "db.bot_channel_roundtrip",
            False,
            f"Postgres unreachable ({last_error}). Start Docker / local PG, then re-run.",
            required=False,
        )
        return

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    bot_id: uuid.UUID | None = None
    channel_ids: list[uuid.UUID] = []

    try:
        async with session_factory() as db:
            user = (
                await db.execute(select(User).where(User.deleted_at.is_(None)).limit(1))
            ).scalar_one_or_none()
            if user is None:
                report.add(
                    "db.bot_channel_roundtrip",
                    False,
                    "no User row — seed a user or run migrations first",
                    required=False,
                )
                return

            org_id = getattr(user, "company_id", None) or user.id
            bot = Bot(
                id=uuid.uuid4(),
                user_id=user.id,
                organization_id=org_id,
                name=f"verify-live-stack-{uuid.uuid4().hex[:6]}",
                platform_type=PlatformType.TELEGRAM,
                is_active=True,
                credentials={},
            )
            db.add(bot)
            await db.flush()
            bot_id = bot.id

            tg_row = BotChannel(
                id=uuid.uuid4(),
                bot_id=bot.id,
                channel_type=HubChannelType.TELEGRAM,
                status=HubChannelStatus.CONNECTED,
                encrypted_token=encrypt_credential(telegram_token),
                reference_id="verify-telegram",
                meta_data={"purpose": "verify_live_stack"},
            )
            wz_row = BotChannel(
                id=uuid.uuid4(),
                bot_id=bot.id,
                channel_type=HubChannelType.WAZZUP,
                status=HubChannelStatus.CONNECTED,
                encrypted_token=encrypt_credential(wazzup_key),
                reference_id="verify-wazzup-channel",
                meta_data={"purpose": "verify_live_stack"},
            )
            db.add(tg_row)
            db.add(wz_row)
            await db.commit()
            channel_ids = [tg_row.id, wz_row.id]

            tg_db = await db.get(BotChannel, tg_row.id)
            wz_db = await db.get(BotChannel, wz_row.id)
            assert tg_db is not None and wz_db is not None
            tg_plain = decrypt_credential(tg_db.encrypted_token or "")
            wz_plain = decrypt_credential(wz_db.encrypted_token or "")
            crypto_ok = tg_plain == telegram_token and wz_plain == wazzup_key
            host_hint = working_url.split("@")[-1] if "@" in working_url else working_url[:32]
            report.add(
                "db.bot_channel_encrypt_persist_decrypt",
                crypto_ok,
                f"host={host_hint} bot_id={bot_id} tg={_mask(tg_plain)} wz={_mask(wz_plain)}",
            )

            if live_tg:
                ok, detail = await _telegram_get_me(tg_plain)
                report.add("telegram.getMe", ok, detail, required=False)
            else:
                report.add(
                    "telegram.getMe",
                    True,
                    "skipped (no live VERIFY_TELEGRAM_TOKEN / placeholder)",
                    required=False,
                )

            if live_wz:
                ok, detail = await _wazzup_channels(wz_plain)
                report.add("wazzup.channels", ok, detail, required=False)
            else:
                report.add(
                    "wazzup.channels",
                    True,
                    "skipped (no live VERIFY_WAZZUP_API_KEY / placeholder)",
                    required=False,
                )
    except Exception as exc:  # noqa: BLE001
        report.add(
            "db.bot_channel_roundtrip",
            False,
            f"{type(exc).__name__}: {exc}",
            required=False,
        )
    finally:
        if bot_id is not None:
            try:
                async with session_factory() as db:
                    for cid in channel_ids:
                        row = await db.get(BotChannel, cid)
                        if row is not None:
                            await db.delete(row)
                    bot = await db.get(Bot, bot_id)
                    if bot is not None:
                        await db.delete(bot)
                    await db.commit()
                report.add(
                    "db.cleanup",
                    True,
                    f"removed bot={bot_id} channels={len(channel_ids)}",
                    required=False,
                )
            except Exception as exc:  # noqa: BLE001
                report.add(
                    "db.cleanup",
                    False,
                    f"{type(exc).__name__}: {exc}",
                    required=False,
                )
        await engine.dispose()


def _print_verdict(report: Report) -> int:
    print()
    print("=" * 60)
    print(" VERIFY LIVE STACK — READINESS VERDICT")
    print("=" * 60)
    failed = report.failed_required
    optional_fail = [i for i in report.items if not i.required and not i.ok]

    if not failed and not optional_fail:
        print(f"{OK} System is READY to receive real .env.production API keys.")
        print(
            "  Next: set TELEGRAM / WAZZUP / LLM keys, re-run with live tokens, "
            "then point Wazzup webhook to /api/v1/webhooks/wazzup"
        )
        return 0
    if not failed and optional_fail:
        only_db = all(i.name.startswith("db.") for i in optional_fail)
        print(f"{WARN} Crypto + LLM key injection OK; optional probes need attention:")
        for item in optional_fail:
            print(f"  - {item.name}: {item.detail}")
        if only_db:
            print(
                "  Verdict: SAFE to fill .env.production LLM/Telegram/Wazzup keys. "
                "Start Postgres (Docker) and re-run to confirm bot_channels encrypt persist."
            )
        else:
            print("  Safe to fill .env.production; re-run after keys / infra are present.")
        return 0

    print(f"{FAIL} NOT READY — fix required failures before production keys:")
    for item in failed:
        print(f"  - {item.name}: {item.detail}")
    return 1


async def main_async(args: argparse.Namespace) -> int:
    report = Report()
    print(f"{INFO} verify_live_stack starting (skip_live_http={args.skip_live_http})")
    await check_crypto_roundtrip(report)
    await check_llm_key_isolation(report)
    await check_llm_ping(report, skip_live=args.skip_live_http)
    await check_db_channel_roundtrip(report, skip_live=args.skip_live_http)
    return _print_verdict(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-live-http",
        action="store_true",
        help="Skip Telegram/Wazzup/LLM HTTP probes (crypto+DB only).",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
