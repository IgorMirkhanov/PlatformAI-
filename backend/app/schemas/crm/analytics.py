"""Native CRM analytics response schemas (funnel / performance / forecast)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FunnelStageStat(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage_id: uuid.UUID
    stage_name: str
    position: int
    deal_count: int = 0
    amount_sum: Decimal = Field(default=Decimal("0.00"))


class CrmFunnelResponse(BaseModel):
    pipeline_id: uuid.UUID
    stages: list[FunnelStageStat]
    total_deals: int = 0
    won_deals: int = 0
    conversion_rate: float = Field(
        default=0.0,
        description="won_deals / total_deals in the filtered window (0..1).",
    )


class ManagerPerformanceRow(BaseModel):
    assigned_user_id: uuid.UUID | None = None
    won_count: int = 0
    lost_count: int = 0
    revenue: Decimal = Field(
        default=Decimal("0.00"),
        description="Sum of amount for WON deals.",
    )


class CrmPerformanceResponse(BaseModel):
    items: list[ManagerPerformanceRow]


class CrmForecastResponse(BaseModel):
    open_deal_count: int = 0
    forecast_amount: Decimal = Field(
        default=Decimal("0.00"),
        description="Sum of amount for all OPEN deals in the organization.",
    )
