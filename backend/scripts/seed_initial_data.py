"""Seed initial data for the MP.AI platform database.

Creates system entities idempotently (safe to re-run):
  1. System Admin Organization  — name="System Admin Org", slug="system-admin"
     └─ OrganizationWallet        — starting credits: 10_000_000 minimal units
  2. Global PromptTemplates       — system prompt-optimizer starters (org_id=NULL)
  3. Platform superadmins         — is_superadmin=True for PLATFORM_SUPERADMIN_EMAILS
  4. LLM model registry           — default OpenRouter / Groq models + pricing

The script does NOT create Subscription plan *tables* (those are code-level
enums in ``SubscriptionPlanName``); instead it documents the per-plan limits
inline and seeds the StripeCustomer plan record so QuotaService resolves the
correct tier for the system org (ENTERPRISE).

Usage (from ``backend/`` or project root):
    python scripts/seed_initial_data.py          # from backend/
    python backend/scripts/seed_initial_data.py  # from repo root

Requires DATABASE_URL from backend/.env (same as the API).
"""

from __future__ import annotations

import asyncio
import sys
import traceback
import uuid
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow ``python backend/scripts/seed_initial_data.py``
# from the repository root, or ``python scripts/seed_initial_data.py``
# from backend/.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_ROOT = _SCRIPT_DIR.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# ---------------------------------------------------------------------------
# Imports (after sys.path is set)
# ---------------------------------------------------------------------------
import app.models  # noqa: F401  — registers all mappers on Base.metadata

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.models.billing.organization_wallet import OrganizationWallet
from app.models.llm_model import LLMModel
from app.models.core_models import (
    Company,
    Project,
    SubscriptionPlanName,
    UserCompanyWorkspace,
    UserRole,
)
from app.models.llm.prompt_template import PromptTemplate
from app.models.saas_metering import StripeCustomer
from app.models.users import User
from app.core.security import hash_password

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_ORG_NAME = "System Admin Org"
SYSTEM_ORG_SLUG = "system-admin"

# Wallet balance is stored as integer minimal units (hundredths of a credit).
# 10_000_000 units = 100 000.00 credits.
SYSTEM_ORG_INITIAL_WALLET_BALANCE: int = 10_000_000

# Accounts that always own the Admin Panel (override via PLATFORM_SUPERADMIN_EMAILS).
PLATFORM_SUPERADMIN_EMAILS: list[str] = list(
    getattr(settings, "PLATFORM_SUPERADMIN_EMAILS", None)
    or ["igor.mirkhanov@mail.ru", "8saaask8@gmail.com"]
)

# Default LLM registry rows shown in /admin → «LLM модели и цены».
# Prices are USD per 1k tokens, as published by the providers.
SEED_LLM_MODELS: list[dict[str, object]] = [
    {
        "provider": "openrouter",
        "model_name": "openai/gpt-oss-20b:free",
        "display_name": "GPT-OSS 20B (OpenRouter Free)",
        "base_url": "https://openrouter.ai/api/v1",
        "context_window": 131_072,
        "cost_per_1k_input": Decimal("0.000000"),
        "cost_per_1k_output": Decimal("0.000000"),
    },
    {
        "provider": "openrouter",
        "model_name": "openai/gpt-4o-mini",
        "display_name": "GPT-4o Mini (OpenRouter)",
        "base_url": "https://openrouter.ai/api/v1",
        "context_window": 128_000,
        "cost_per_1k_input": Decimal("0.000150"),
        "cost_per_1k_output": Decimal("0.000600"),
    },
    {
        "provider": "openrouter",
        "model_name": "openai/gpt-4o",
        "display_name": "GPT-4o (OpenRouter)",
        "base_url": "https://openrouter.ai/api/v1",
        "context_window": 128_000,
        "cost_per_1k_input": Decimal("0.002500"),
        "cost_per_1k_output": Decimal("0.010000"),
    },
    {
        "provider": "groq",
        "model_name": "openai/gpt-oss-20b",
        "display_name": "GPT-OSS 20B (Groq Free — fallback)",
        "base_url": "https://api.groq.com/openai/v1",
        "context_window": 131_072,
        "cost_per_1k_input": Decimal("0.000000"),
        "cost_per_1k_output": Decimal("0.000000"),
    },
]

# Models the vendor pulled from the free tier: keep the row for audit trail but
# switch it off so routing and pricing never pick a slug that answers 404.
RETIRED_LLM_MODELS: list[tuple[str, str]] = [
    ("openrouter", "meta-llama/llama-3.2-3b-instruct:free"),
    ("groq", "llama-3.1-8b-instant"),
]

# Per-plan limits (informational — QuotaService reads these same constants).
PLAN_LIMITS: dict[str, dict[str, object]] = {
    "FREE": {
        "label": "Free",
        "price_kzt": "0.00",
        "price_usd": "0.00",
        "max_bots": 1,
        "messages_per_day": 200,
        "tokens_per_month": 100_000,
        "crm_contacts": 100,
        "crm_deals": 10,
        "crm_automation_rules": 1,
        "initial_credits": 0,
        "llm_access": "basic",
        "notes": "Starter tier — GPT-4o-mini / Ollama only",
    },
    "PRO": {
        "label": "Pro",
        "price_kzt": "24500.00",
        "price_usd": "49.00",
        "max_bots": 10,
        "messages_per_day": 10_000,
        "tokens_per_month": 5_000_000,
        "crm_contacts": 5_000,
        "crm_deals": 500,
        "crm_automation_rules": 20,
        "initial_credits": 50_000,
        "llm_access": "full_multivendor",
        "notes": "Full multi-vendor LLM showcase (OpenAI, Anthropic, DeepSeek, Gemini, GLM, Qwen)",
    },
    "ENTERPRISE": {
        "label": "Enterprise",
        "price_kzt": "99000.00",
        "price_usd": "199.00",
        "max_bots": 999,
        "messages_per_day": 1_000_000,
        "tokens_per_month": 100_000_000,
        "crm_contacts": 100_000,
        "crm_deals": 10_000,
        "crm_automation_rules": 100,
        "initial_credits": 250_000,
        "llm_access": "full_multivendor_priority",
        "notes": "Maximum limits, priority routing, SLA",
    },
}

# Global prompt templates seeded with organization_id=NULL (system defaults).
SEED_PROMPT_TEMPLATES: list[dict[str, str]] = [
    {
        "name": "system_prompt_optimizer_v1",
        "description": (
            "Default system prompt for the prompt-optimization service. "
            "Instructs the LLM to rewrite a user-supplied prompt to be clearer, "
            "more specific, and better suited for an AI assistant context."
        ),
        "content": (
            "You are an expert prompt engineer. "
            "Your task is to rewrite the user-provided prompt to make it:\n"
            "1. Clearer and more specific.\n"
            "2. Better structured (role → context → task → format).\n"
            "3. Free of ambiguities that would confuse a language model.\n\n"
            "Return ONLY the improved prompt text — no explanations, no commentary."
        ),
    },
    {
        "name": "system_prompt_concise_assistant",
        "description": "Concise, professional assistant persona template.",
        "content": (
            "You are a helpful, concise, and professional AI assistant for {{company_name}}. "
            "Answer the user's questions accurately and briefly. "
            "If you do not know the answer, say so honestly. "
            "Do not invent information. Language: {{language|default('auto')}}."
        ),
    },
    {
        "name": "system_prompt_sales_agent",
        "description": "Sales-focused assistant template for lead qualification flows.",
        "content": (
            "You are a friendly sales assistant for {{company_name}}. "
            "Your goal is to understand the prospect's needs, present relevant product benefits, "
            "and guide them toward a consultation or purchase. "
            "Be warm, concise, and never pushy. "
            "Use the following product context:\n{{product_context}}"
        ),
    },
    {
        "name": "system_prompt_support_agent",
        "description": "Customer support agent template with escalation awareness.",
        "content": (
            "You are a customer support specialist for {{company_name}}. "
            "Help users resolve issues quickly and professionally. "
            "If you cannot resolve the issue, offer to escalate to a human agent. "
            "FAQ context:\n{{faq_context|default('No FAQ loaded.')}}"
        ),
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OK = "[OK]"
SKIP = "[SKIP]"
ERR = "[ERROR]"


def _log(tag: str, msg: str) -> None:
    print(f"{tag} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


async def _seed_system_org(session) -> Company:
    """Ensure the System Admin Organization and its wallet exist."""
    existing: Company | None = await session.scalar(
        select(Company).where(Company.slug == SYSTEM_ORG_SLUG)
    )
    if existing is not None:
        _log(SKIP, f"System org already exists  id={existing.id}  name={existing.name!r}")
        return existing

    # We need a stub owner user for the FK constraint on companies.owner_user_id.
    # Check for an existing superadmin first.
    superadmin: User | None = await session.scalar(
        select(User).where(User.is_superadmin.is_(True)).limit(1)
    )
    if superadmin is None:
        # Create a minimal system bot user (not a real login account).
        system_user_id = uuid.uuid4()
        superadmin = User(
            id=system_user_id,
            email="system@mp.ai",
            hashed_password=hash_password(uuid.uuid4().hex),  # random, unusable
            company_name=SYSTEM_ORG_NAME,
            full_name="System Bot",
            company_id=system_user_id,
            role=UserRole.OWNER,
            is_superadmin=True,
            is_active=True,
            is_verified=True,
        )
        session.add(superadmin)
        await session.flush()
        _log(OK, f"Created system bot user  id={superadmin.id}  email={superadmin.email!r}")

    org_id = uuid.uuid4()
    org = Company(
        id=org_id,
        name=SYSTEM_ORG_NAME,
        slug=SYSTEM_ORG_SLUG,
        owner_user_id=superadmin.id,
        timezone="UTC",
    )
    session.add(org)
    await session.flush()
    _log(OK, f"Created system org  id={org.id}  slug={org.slug!r}")

    # Membership
    session.add(
        UserCompanyWorkspace(
            user_id=superadmin.id,
            company_id=org.id,
            role=UserRole.OWNER,
        )
    )

    # Default project
    session.add(
        Project(
            organization_id=org.id,
            name="System",
            slug="system",
            description="System-level default project",
        )
    )

    # StripeCustomer / plan record → QuotaService resolves ENTERPRISE for this org.
    stripe_record = await session.scalar(
        select(StripeCustomer).where(StripeCustomer.organization_id == org.id)
    )
    if stripe_record is None:
        session.add(
            StripeCustomer(
                organization_id=org.id,
                # Use a synthetic placeholder so the NOT NULL constraint is met.
                # QuotaService only reads plan_name and organization_id.
                stripe_customer_id=f"sys_{org.id.hex}",
                plan_name=SubscriptionPlanName.ENTERPRISE.value,
                status="active",
            )
        )
        _log(OK, "Set plan=ENTERPRISE for system org via StripeCustomer")

    await session.flush()
    return org


async def _seed_wallet(session, org: Company) -> None:
    """Ensure the OrganizationWallet exists and has starting credits."""
    wallet: OrganizationWallet | None = await session.get(
        OrganizationWallet, org.id
    )
    if wallet is not None:
        _log(
            SKIP,
            f"Wallet already exists  org_id={org.id}  balance={wallet.balance}",
        )
        return

    wallet = OrganizationWallet(
        organization_id=org.id,
        balance=SYSTEM_ORG_INITIAL_WALLET_BALANCE,
    )
    session.add(wallet)
    await session.flush()
    _log(
        OK,
        f"Created wallet  org_id={org.id}  balance={SYSTEM_ORG_INITIAL_WALLET_BALANCE:,} units",
    )


async def _seed_prompt_templates(session) -> None:
    """Seed global (organization_id=NULL) prompt templates."""
    for tpl in SEED_PROMPT_TEMPLATES:
        name = tpl["name"]
        existing = await session.scalar(
            select(PromptTemplate).where(
                PromptTemplate.name == name,
                PromptTemplate.organization_id.is_(None),
            )
        )
        if existing is not None:
            _log(SKIP, f"Prompt template already exists  name={name!r}")
            continue

        session.add(
            PromptTemplate(
                name=name,
                content=tpl["content"],
                description=tpl.get("description"),
                organization_id=None,
                is_active=True,
                version=1,
            )
        )
        _log(OK, f"Created prompt template  name={name!r}")

    await session.flush()


async def _seed_platform_superadmins(session) -> None:
    """
    Grant ``is_superadmin`` to the hard-coded platform owner accounts.

    Runs on every API start (idempotent). Accounts that have not registered
    yet are reported as skipped — the grant applies on the next start.
    """
    for email in PLATFORM_SUPERADMIN_EMAILS:
        normalized = email.strip().lower()
        if not normalized:
            continue
        user: User | None = await session.scalar(
            select(User).where(func.lower(User.email) == normalized)
        )
        if user is None:
            _log(SKIP, f"Superadmin seed: no account for {normalized!r} yet — register first")
            continue
        if bool(user.is_superadmin) and bool(getattr(user, "is_active", True)):
            _log(SKIP, f"Superadmin already granted  email={normalized!r}")
            continue
        user.is_superadmin = True
        if hasattr(user, "is_support"):
            user.is_support = False
        if hasattr(user, "is_active"):
            user.is_active = True
        _log(OK, f"Granted is_superadmin=True  email={normalized!r}  id={user.id}")

    await session.flush()


async def _seed_llm_models(session) -> None:
    """Upsert the default LLM registry rows shown in the Admin Panel."""
    for spec in SEED_LLM_MODELS:
        provider = str(spec["provider"]).lower()
        model_name = str(spec["model_name"])
        existing: LLMModel | None = await session.scalar(
            select(LLMModel).where(
                LLMModel.provider == provider,
                LLMModel.model_name == model_name,
            )
        )
        if existing is not None:
            # Keep pricing / endpoint in sync, never flip a manual is_active off.
            existing.display_name = str(spec["display_name"])
            existing.base_url = spec["base_url"]  # type: ignore[assignment]
            existing.context_window = int(spec["context_window"])  # type: ignore[arg-type]
            existing.cost_per_1k_input = spec["cost_per_1k_input"]  # type: ignore[assignment]
            existing.cost_per_1k_output = spec["cost_per_1k_output"]  # type: ignore[assignment]
            _log(SKIP, f"LLM model exists, pricing refreshed  {provider}/{model_name}")
            continue

        session.add(
            LLMModel(
                id=uuid.uuid4(),
                provider=provider,
                model_name=model_name,
                display_name=str(spec["display_name"]),
                base_url=spec["base_url"],  # type: ignore[arg-type]
                context_window=int(spec["context_window"]),  # type: ignore[arg-type]
                cost_per_1k_input=spec["cost_per_1k_input"],  # type: ignore[arg-type]
                cost_per_1k_output=spec["cost_per_1k_output"],  # type: ignore[arg-type]
                is_active=True,
                is_system_default=False,
            )
        )
        _log(OK, f"Created LLM model  {provider}/{model_name}")

    for provider, model_name in RETIRED_LLM_MODELS:
        retired: LLMModel | None = await session.scalar(
            select(LLMModel).where(
                LLMModel.provider == provider,
                LLMModel.model_name == model_name,
            )
        )
        if retired is None:
            continue
        if retired.is_active:
            retired.is_active = False
            retired.is_system_default = False
            _log(OK, f"Deactivated retired LLM model  {provider}/{model_name}")

    await session.flush()


def _print_plan_summary() -> None:
    """Print human-readable subscription plan limits to stdout."""
    print("\n── Subscription plan limits (code-level, no DB table) ──")
    for key, cfg in PLAN_LIMITS.items():
        print(
            f"  {key:12s}  bots={cfg['max_bots']:>4}  "
            f"msg/day={cfg['messages_per_day']:>10,}  "
            f"tok/mo={cfg['tokens_per_month']:>12,}  "
            f"credits={cfg['initial_credits']:>8,}  "
            f"llm={cfg['llm_access']}"
        )
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _verify_connectivity() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    _log(OK, "Database connection verified")


async def seed() -> None:
    await _verify_connectivity()

    async with async_session_factory() as session:
        try:
            org = await _seed_system_org(session)
            await _seed_wallet(session, org)
            await _seed_prompt_templates(session)
            await _seed_platform_superadmins(session)
            await _seed_llm_models(session)
            await session.commit()
            _log(OK, "All seed operations committed successfully")
        except Exception:
            await session.rollback()
            _log(ERR, "Seed failed — transaction rolled back")
            raise

    _print_plan_summary()


async def _main() -> None:
    print("=== MP.AI — Initial data seed ===\n")
    try:
        await seed()
        print("\n=== Seed complete ===")
    except Exception:
        print("\n=== Seed FAILED — full traceback below ===")
        traceback.print_exc()
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
