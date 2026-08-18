"""Auth token lifecycle: refresh tokens, password reset, OAuth stubs."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import mint_user_token
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.auth_tokens import OAuthAccount, PasswordResetToken, RefreshToken
from app.models.users import User


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _refresh_ttl() -> timedelta:
    days = int(getattr(settings, "JWT_REFRESH_TOKEN_EXPIRE_DAYS", 30))
    return timedelta(days=days)


class AuthTokenService:
    """Opaque refresh + password-reset tokens (hashed at rest)."""

    async def issue_refresh_token(
        self,
        db: AsyncSession,
        user: User,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> str:
        raw = secrets.token_urlsafe(48)
        row = RefreshToken(
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(timezone.utc) + _refresh_ttl(),
            user_agent=(user_agent or "")[:512] or None,
            ip_address=(ip_address or "")[:64] or None,
        )
        db.add(row)
        await db.flush()
        return raw

    async def rotate_refresh_token(
        self,
        db: AsyncSession,
        raw_refresh: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, str, str]:
        """
        Validate refresh token → revoke → mint new access + refresh.

        Returns ``(user, access_token, new_refresh_token)``.
        """
        token_hash = _hash_token(raw_refresh.strip())
        row = await db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        now = datetime.now(timezone.utc)
        if row is None or row.revoked_at is not None or row.expires_at < now:
            raise ValueError("Invalid or expired refresh token.")

        user = await db.get(User, row.user_id)
        if user is None or not bool(user.is_active) or user.deleted_at is not None:
            raise ValueError("User is inactive or deleted.")

        row.revoked_at = now
        new_refresh = await self.issue_refresh_token(
            db, user, user_agent=user_agent, ip_address=ip_address
        )
        access = mint_user_token(user)
        return user, access, new_refresh

    async def revoke_refresh_token(self, db: AsyncSession, raw_refresh: str) -> None:
        token_hash = _hash_token(raw_refresh.strip())
        row = await db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await db.flush()

    async def revoke_all_refresh_tokens(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        """Revoke every active refresh token for the user (logout-all / password change)."""
        now = datetime.now(timezone.utc)
        tokens = (
            await db.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).all()
        for row in tokens:
            row.revoked_at = now
        if tokens:
            await db.flush()
        return len(tokens)

    async def create_password_reset_token(self, db: AsyncSession, user: User) -> str:
        raw = secrets.token_urlsafe(32)
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(row)
        await db.flush()
        return raw

    async def reset_password(
        self,
        db: AsyncSession,
        *,
        raw_token: str,
        new_password: str,
    ) -> User:
        token_hash = _hash_token(raw_token.strip())
        row = await db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        now = datetime.now(timezone.utc)
        if row is None or row.used_at is not None or row.expires_at < now:
            raise ValueError("Invalid or expired password reset token.")

        user = await db.get(User, row.user_id)
        if user is None or user.deleted_at is not None:
            raise ValueError("User not found.")

        user.hashed_password = hash_password(new_password)
        row.used_at = now
        # Revoke all refresh tokens on password change
        tokens = (
            await db.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user.id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).all()
        for t in tokens:
            t.revoked_at = now
        await db.flush()
        return user

    async def link_oauth_stub(
        self,
        db: AsyncSession,
        user: User,
        *,
        provider: str,
        provider_account_id: str,
        profile_json: str | None = None,
    ) -> OAuthAccount:
        existing = await db.scalar(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_account_id == provider_account_id,
            )
        )
        if existing is not None:
            return existing
        account = OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_account_id=provider_account_id,
            raw_profile=profile_json,
        )
        db.add(account)
        await db.flush()
        return account


class EmailStubService:
    """Email delivery stub — logs instead of sending (replace with SES/SendGrid in prod)."""

    def send_password_reset(self, *, email: str, reset_token: str) -> None:
        reset_url = (
            f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')}"
            f"/reset-password?token={reset_token}"
        )
        # Never log the full token — only a short fingerprint for support correlation.
        fingerprint = reset_token[-4:] if len(reset_token) >= 4 else "****"
        logger.info(
            "EmailStub.password_reset | to={email} token_fp=…{fp} url_host={host}",
            email=email,
            fp=fingerprint,
            host=getattr(settings, "FRONTEND_URL", "http://localhost:3000"),
        )
        # Full URL only in non-production so local QA can click the link from logs.
        if not settings.is_production:
            logger.debug("EmailStub.password_reset_dev_url | url={url}", url=reset_url)

    def send_verification(self, *, email: str, verify_token: str) -> None:
        logger.info(
            "EmailStub.verify_email | to={email} token={token}",
            email=email,
            token=verify_token[:8] + "…",
        )


auth_token_service = AuthTokenService()
email_stub = EmailStubService()
