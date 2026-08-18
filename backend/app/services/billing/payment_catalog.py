"""Catalog of top-up packages and subscription plans (tokens / pricing)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TopUpPackage:
    id: str
    label: str
    amount_usd: Decimal
    tokens_allocated: int
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class SubscriptionPlanPackage:
    id: str
    label: str
    amount_usd: Decimal
    tokens_allocated: int
    plan_id: str
    currency: str = "USD"


TOPUP_PACKAGES: dict[str, TopUpPackage] = {
    "topup_100k": TopUpPackage(
        id="topup_100k",
        label="100k tokens",
        amount_usd=Decimal("10.00"),
        tokens_allocated=100_000,
    ),
    "topup_1m": TopUpPackage(
        id="topup_1m",
        label="1M tokens",
        amount_usd=Decimal("80.00"),
        tokens_allocated=1_000_000,
    ),
}

SUBSCRIPTION_PLANS: dict[str, SubscriptionPlanPackage] = {
    "sub_pro": SubscriptionPlanPackage(
        id="sub_pro",
        label="PRO (monthly)",
        amount_usd=Decimal("49.00"),
        tokens_allocated=500_000,
        plan_id="pro",
    ),
    "sub_enterprise": SubscriptionPlanPackage(
        id="sub_enterprise",
        label="ENTERPRISE (monthly)",
        amount_usd=Decimal("199.00"),
        tokens_allocated=2_500_000,
        plan_id="enterprise",
    ),
}


def resolve_catalog_item(
    item_type: str,
    package_id: str,
) -> TopUpPackage | SubscriptionPlanPackage:
    key = (package_id or "").strip().lower()
    if item_type == "subscription":
        plan = SUBSCRIPTION_PLANS.get(key)
        if plan is None:
            raise ValueError(f"Unknown subscription package '{package_id}'.")
        return plan
    package = TOPUP_PACKAGES.get(key)
    if package is None:
        raise ValueError(f"Unknown top-up package '{package_id}'.")
    return package
