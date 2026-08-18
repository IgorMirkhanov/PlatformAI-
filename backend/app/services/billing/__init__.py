"""Workspace & Billing services package."""

from app.services.billing.wallet_service import (
    DeductResult,
    InsufficientFundsError,
    WalletNotFoundError,
    WalletService,
    wallet_service,
)

__all__ = [
    "DeductResult",
    "InsufficientFundsError",
    "WalletNotFoundError",
    "WalletService",
    "wallet_service",
]


def __getattr__(name: str):
    # Lazy invite exports — avoid schema import side-effects for wallet-only callers.
    if name in {
        "InviteExpiredError",
        "InviteNotFoundError",
        "InviteService",
        "InviteServiceError",
        "hash_invite_token",
        "invite_service",
    }:
        from app.services.billing import invite_service as _invite

        return getattr(_invite, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
