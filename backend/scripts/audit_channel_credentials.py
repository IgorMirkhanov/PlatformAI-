"""Report which bot channels hold tokens the current key cannot decrypt.

Prints identifiers and status only — never credential material.
"""

import asyncio

from sqlalchemy import select

from app.core.security import decrypt_credential
from app.db.session import async_session_factory
from app.models.channels import BotChannel
from app.models.core_models import Bot


async def main() -> None:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(BotChannel, Bot.name)
                .join(Bot, Bot.id == BotChannel.bot_id)
                .order_by(BotChannel.channel_type)
            )
        ).all()

        print(f"channels_total: {len(rows)}")
        for channel, bot_name in rows:
            token = channel.encrypted_token
            if not token:
                state = "no-token-stored"
            else:
                try:
                    state = "OK" if decrypt_credential(token) else "empty-after-decrypt"
                except Exception as exc:  # noqa: BLE001
                    state = f"DECRYPT_FAILED ({type(exc).__name__})"
            print(
                f"  bot={bot_name!r} type={channel.channel_type.value} "
                f"status={channel.status.value} id={channel.id} -> {state}"
            )


if __name__ == "__main__":
    asyncio.run(main())
