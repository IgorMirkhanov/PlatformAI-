"""CLI: org-level channel + AI credential readiness table."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.channels import BotChannel, HubChannelStatus
from app.models.core_models import Bot, Company
from app.models.tenant_credentials import CredentialKind, CredentialStatus, TenantCredential


LLM_KINDS = {
    CredentialKind.LLM_OPENAI.value,
    CredentialKind.LLM_DEEPSEEK.value,
    CredentialKind.LLM_ANTHROPIC.value,
    CredentialKind.LLM_GROQ.value,
    CredentialKind.LLM_OPENROUTER.value,
    CredentialKind.LLM_GEMINI.value,
}


async def _run() -> int:
    async with async_session_factory() as db:
        orgs = list((await db.scalars(select(Company))).all())
        print(f"{'org':<36} {'name':<24} {'ai_ok':<6} {'channels':<8} {'orphan':<6}")
        warnings = 0
        for org in orgs:
            creds = list(
                (
                    await db.scalars(
                        select(TenantCredential).where(
                            TenantCredential.organization_id == org.id,
                            TenantCredential.kind.in_(list(LLM_KINDS)),
                            TenantCredential.status == CredentialStatus.ACTIVE.value,
                        )
                    )
                ).all()
            )
            ai_ok = bool(creds)
            bots = list((await db.scalars(select(Bot).where(Bot.organization_id == org.id))).all())
            bot_ids = [b.id for b in bots]
            channels = []
            if bot_ids:
                channels = list(
                    (
                        await db.scalars(
                            select(BotChannel).where(
                                BotChannel.bot_id.in_(bot_ids),
                                BotChannel.status == HubChannelStatus.CONNECTED,
                            )
                        )
                    ).all()
                )
            orphan = 0
            if channels and not ai_ok:
                orphan = len(channels)
                warnings += 1
                print(
                    f"WARN orphan channels org={org.id} name={org.name!r} count={orphan}",
                    file=sys.stderr,
                )
            print(
                f"{str(org.id):<36} {str(org.name)[:24]:<24} {str(ai_ok):<6} {len(channels):<8} {orphan:<6}"
            )
        return 1 if warnings else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify channel/AI readiness per organization.")
    parser.parse_args()
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
