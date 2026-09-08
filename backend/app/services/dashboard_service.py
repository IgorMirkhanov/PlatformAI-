from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.core_models import (
    Bot,
    BotDiagnosticLog,
    ChatMessage,
    Client,
    MessageSender,
)
from app.schemas.core_schemas import AgentStatusSummary, DashboardDailyPoint, DashboardStatsResponse
from app.schemas.diagnostic_schemas import DiagnosticLogListResponse
from app.services.ai_orchestrator import USD_TO_KZT
from app.services.billing_service import billing_service
from app.services.diagnostic_log_service import diagnostic_log_service

TOKEN_COST_KZT_PER_MESSAGE = round(0.002 * USD_TO_KZT, 4)
CSV_HEADERS = [
    "Date",
    "Bot Name",
    "Total Dialogs",
    "Total Messages",
    "Token Expense (KZT)",
    "System Health Index",
]

OMNICHANNEL_KEYS = ("telegram", "whatsapp", "instagram", "vkontakte", "web_widget")
_WEEKDAY_LABELS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def _empty_daily_series(*, days: int = 7) -> list[DashboardDailyPoint]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    points: list[DashboardDailyPoint] = []
    cursor = start
    while cursor <= today:
        points.append(
            DashboardDailyPoint(
                date=cursor.isoformat(),
                label=_WEEKDAY_LABELS_RU[cursor.weekday()],
                messages=0,
                dialogs=0,
            )
        )
        cursor = date.fromordinal(cursor.toordinal() + 1)
    return points


async def _build_daily_series(
    db: AsyncSession,
    *,
    bot_ids: list[uuid.UUID],
    days: int = 7,
) -> list[DashboardDailyPoint]:
    """Real last-N-days message/dialog counts (UTC calendar days)."""
    points = _empty_daily_series(days=days)
    if not bot_ids:
        return points

    today = datetime.now(UTC).date()
    start_day = today - timedelta(days=days - 1)
    range_start = datetime.combine(start_day, time.min, tzinfo=UTC)

    day_expr = func.date_trunc("day", ChatMessage.created_at)

    messages_rows = await db.execute(
        select(day_expr.label("day"), func.count(ChatMessage.id))
        .join(Client, ChatMessage.client_id == Client.id)
        .where(Client.bot_id.in_(bot_ids), ChatMessage.created_at >= range_start)
        .group_by(day_expr)
    )
    messages_by_day: dict[str, int] = {}
    for day_value, count in messages_rows.all():
        if day_value is None:
            continue
        day_date = day_value.date() if hasattr(day_value, "date") else day_value
        messages_by_day[day_date.isoformat()] = int(count or 0)

    dialogs_rows = await db.execute(
        select(day_expr.label("day"), func.count(func.distinct(Client.id)))
        .join(Client, ChatMessage.client_id == Client.id)
        .where(Client.bot_id.in_(bot_ids), ChatMessage.created_at >= range_start)
        .group_by(day_expr)
    )
    dialogs_by_day: dict[str, int] = {}
    for day_value, count in dialogs_rows.all():
        if day_value is None:
            continue
        day_date = day_value.date() if hasattr(day_value, "date") else day_value
        dialogs_by_day[day_date.isoformat()] = int(count or 0)

    for point in points:
        point.messages = messages_by_day.get(point.date, 0)
        point.dialogs = dialogs_by_day.get(point.date, 0)
    return points


def _extract_connected_channels(credentials: dict[str, object]) -> list[str]:
    connected: list[str] = []
    raw_channels = credentials.get("channels")
    if isinstance(raw_channels, dict):
        for key, value in raw_channels.items():
            if isinstance(value, dict) and value.get("connected"):
                connected.append(str(key))

    legacy_channel = credentials.get("channel")
    if credentials.get("token_hash") and legacy_channel in {"telegram", "whatsapp"}:
        legacy_key = str(legacy_channel)
        if legacy_key not in connected:
            connected.append(legacy_key)

    return connected


class DashboardService:
    """Aggregate analytics for the SaaS workspace dashboard."""

    async def get_dashboard_stats(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
    ) -> DashboardStatsResponse:
        try:
            user = await billing_service._resolve_user(db, user_id)
        except ValueError as exc:
            logger.warning("Dashboard.user_not_found | error={error}", error=str(exc))
            raise

        billing = await billing_service.get_billing_status(db, user.id)

        bots_result = await db.execute(
            select(Bot)
            .where(
                Bot.organization_id == user.company_id,
                Bot.deleted_at.is_(None),
            )
            .options(selectinload(Bot.flows))
        )
        bots = bots_result.scalars().unique().all()

        unique_dialogs_result = await db.execute(
            select(func.count(Client.id)).where(Client.bot_id.in_([bot.id for bot in bots] or [uuid.uuid4()]))
        )
        total_unique_dialogs = int(unique_dialogs_result.scalar_one() or 0)

        if not bots:
            return DashboardStatsResponse(
                total_unique_dialogs=0,
                total_messages_dispatched=0,
                api_token_expenditure=0.0,
                active_agents=0,
                inactive_agents=0,
                subscription_balance=billing.balance,
                subscription_plan=billing.plan_name,
                agents=[],
                period_label="last_7_days",
                daily_series=_empty_daily_series(),
            )

        bot_ids = [bot.id for bot in bots]

        messages_result = await db.execute(
            select(func.count(ChatMessage.id))
            .join(Client, ChatMessage.client_id == Client.id)
            .where(Client.bot_id.in_(bot_ids))
        )
        total_messages = int(messages_result.scalar_one() or 0)

        bot_messages_result = await db.execute(
            select(func.count(ChatMessage.id))
            .join(Client, ChatMessage.client_id == Client.id)
            .where(
                Client.bot_id.in_(bot_ids),
                ChatMessage.sender == MessageSender.BOT,
            )
        )
        bot_messages = int(bot_messages_result.scalar_one() or 0)

        api_token_expenditure = round(bot_messages * 0.002, 4)

        # Batch dialog counts — avoids per-bot N+1 queries.
        dialogs_rows = await db.execute(
            select(Client.bot_id, func.count(Client.id))
            .where(Client.bot_id.in_(bot_ids))
            .group_by(Client.bot_id)
        )
        dialogs_by_bot = {bot_id: int(count or 0) for bot_id, count in dialogs_rows.all()}

        agent_summaries: list[AgentStatusSummary] = []
        for bot in bots:
            flows = list(getattr(bot, "flows", None) or [])
            flow_published = any(
                getattr(flow, "is_published", False) and flow.deleted_at is None for flow in flows
            )
            credentials = bot.credentials if isinstance(bot.credentials, dict) else {}
            connected_channels = _extract_connected_channels(credentials)

            agent_summaries.append(
                AgentStatusSummary(
                    bot_id=bot.id,
                    bot_name=bot.name,
                    platform_type=bot.platform_type,
                    is_active=bot.is_active,
                    channel_connected=bool(credentials.get("token_hash")) or bool(connected_channels),
                    flow_published=flow_published,
                    unique_dialogs=dialogs_by_bot.get(bot.id, 0),
                    connected_channels=connected_channels,
                )
            )

        active_agents = sum(1 for bot in bots if bot.is_active)
        inactive_agents = len(bots) - active_agents
        daily_series = await _build_daily_series(db, bot_ids=bot_ids, days=7)

        logger.info(
            "Dashboard.stats | user_id={user_id} dialogs={dialogs} messages={messages}",
            user_id=user.id,
            dialogs=total_unique_dialogs,
            messages=total_messages,
        )

        return DashboardStatsResponse(
            total_unique_dialogs=total_unique_dialogs,
            total_messages_dispatched=total_messages,
            api_token_expenditure=api_token_expenditure,
            active_agents=active_agents,
            inactive_agents=inactive_agents,
            subscription_balance=billing.balance,
            subscription_plan=billing.plan_name,
            agents=agent_summaries,
            period_label="last_7_days",
            daily_series=daily_series,
        )

    async def list_diagnostic_logs(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
        limit: int = 25,
    ) -> DiagnosticLogListResponse:
        user = await billing_service._resolve_user(db, user_id)
        return await diagnostic_log_service.list_recent_for_user(
            db,
            user_id=user.id,
            limit=limit,
        )

    async def iter_export_rows(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        bot_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, str | int | float]]:
        user = await billing_service._resolve_user(db, user_id)
        bots_query = select(Bot).where(Bot.user_id == user.id)
        if bot_id is not None:
            bots_query = bots_query.where(Bot.id == bot_id)
        bots_result = await db.execute(bots_query)
        bots = bots_result.scalars().all()
        if not bots:
            return []

        range_start = datetime.combine(start_date or date(1970, 1, 1), time.min, tzinfo=UTC)
        range_end = datetime.combine(end_date or datetime.now(UTC).date(), time.max, tzinfo=UTC)

        rows: list[dict[str, str | int | float]] = []
        for bot in bots:
            day_cursor = range_start.date()
            final_day = range_end.date()
            while day_cursor <= final_day:
                day_start = datetime.combine(day_cursor, time.min, tzinfo=UTC)
                day_end = datetime.combine(day_cursor, time.max, tzinfo=UTC)

                dialogs_result = await db.execute(
                    select(func.count(func.distinct(Client.id)))
                    .join(ChatMessage, ChatMessage.client_id == Client.id)
                    .where(
                        Client.bot_id == bot.id,
                        ChatMessage.created_at >= day_start,
                        ChatMessage.created_at <= day_end,
                    )
                )
                total_dialogs = int(dialogs_result.scalar_one() or 0)

                messages_result = await db.execute(
                    select(func.count(ChatMessage.id))
                    .join(Client, ChatMessage.client_id == Client.id)
                    .where(
                        Client.bot_id == bot.id,
                        ChatMessage.created_at >= day_start,
                        ChatMessage.created_at <= day_end,
                    )
                )
                total_messages = int(messages_result.scalar_one() or 0)

                bot_messages_result = await db.execute(
                    select(func.count(ChatMessage.id))
                    .join(Client, ChatMessage.client_id == Client.id)
                    .where(
                        Client.bot_id == bot.id,
                        ChatMessage.sender == MessageSender.BOT,
                        ChatMessage.created_at >= day_start,
                        ChatMessage.created_at <= day_end,
                    )
                )
                bot_messages = int(bot_messages_result.scalar_one() or 0)
                token_expense = round(bot_messages * TOKEN_COST_KZT_PER_MESSAGE, 2)

                errors_result = await db.execute(
                    select(func.count(BotDiagnosticLog.id)).where(
                        BotDiagnosticLog.bot_id == bot.id,
                        BotDiagnosticLog.created_at >= day_start,
                        BotDiagnosticLog.created_at <= day_end,
                    )
                )
                error_count = int(errors_result.scalar_one() or 0)
                health_index = max(0, min(100, 100 - error_count * 8))

                if total_dialogs or total_messages or error_count:
                    rows.append(
                        {
                            "Date": day_cursor.isoformat(),
                            "Bot Name": bot.name,
                            "Total Dialogs": total_dialogs,
                            "Total Messages": total_messages,
                            "Token Expense (KZT)": token_expense,
                            "System Health Index": health_index,
                        }
                    )

                day_cursor = date.fromordinal(day_cursor.toordinal() + 1)

        return rows

    async def build_export_csv(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        bot_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> str:
        export_rows = await self.iter_export_rows(
            db,
            user_id=user_id,
            bot_id=bot_id,
            start_date=start_date,
            end_date=end_date,
        )
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in export_rows:
            writer.writerow(row)
        logger.info(
            "Dashboard.export_csv | rows={rows} bot_id={bot_id}",
            rows=len(export_rows),
            bot_id=bot_id,
        )
        return buffer.getvalue()


dashboard_service = DashboardService()
