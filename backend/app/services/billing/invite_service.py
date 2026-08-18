"""Organization invite service — hashed tokens, membership on accept."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing.organization_invite import OrganizationInvite
from app.models.core_models import UserCompanyWorkspace, UserRole
from app.models.users import User
from app.schemas.billing.invites import (
    AcceptOrganizationInviteResponse,
    OrganizationInviteCreate,
    OrganizationInviteCreated,
    OrganizationInviteListResponse,
    OrganizationInviteRead,
)


def hash_invite_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def generate_raw_invite_token() -> str:
    return secrets.token_urlsafe(32)


class InviteServiceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InviteExpiredError(InviteServiceError):
    def __init__(self, message: str = "Invitation token has expired.") -> None:
        super().__init__(message, status_code=400)


class InviteNotFoundError(InviteServiceError):
    def __init__(self, message: str = "Invitation token is invalid.") -> None:
        super().__init__(message, status_code=404)


class InviteService:
    """Email invite lifecycle for organization workspaces."""

    INVITE_TTL_DAYS = 7
    _MANAGE_ROLES = frozenset({UserRole.OWNER, UserRole.ADMIN})

    def _repo_query(self, organization_id: uuid.UUID):
        return select(OrganizationInvite).where(
            OrganizationInvite.organization_id == organization_id
        )

    @staticmethod
    def _parse_role(role: str) -> UserRole:
        try:
            return UserRole(role.strip().upper())
        except ValueError as exc:
            raise InviteServiceError(f"Unsupported role '{role}'.", status_code=400) from exc

    async def create_invite(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        email: str,
        role: str,
        inviter_user_id: uuid.UUID,
    ) -> OrganizationInviteCreated:
        payload = OrganizationInviteCreate(email=email, role=role)
        normalized_email = payload.email
        role_value = payload.role

        pending = await db.scalar(
            select(OrganizationInvite).where(
                OrganizationInvite.organization_id == organization_id,
                OrganizationInvite.email == normalized_email,
                OrganizationInvite.is_accepted.is_(False),
                OrganizationInvite.expires_at > datetime.now(timezone.utc),
            )
        )
        if pending is not None:
            raise InviteServiceError(
                "An active invitation already exists for this email.",
                status_code=409,
            )

        raw_token = generate_raw_invite_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.INVITE_TTL_DAYS)
        invite = OrganizationInvite(
            organization_id=organization_id,
            email=normalized_email,
            role=role_value,
            token_hash=hash_invite_token(raw_token),
            expires_at=expires_at,
            is_accepted=False,
            invited_by_id=inviter_user_id,
        )
        db.add(invite)
        await db.flush()

        from app.services.security_audit_service import security_audit_service

        await security_audit_service.invite_created(
            db,
            organization_id=organization_id,
            actor_user_id=inviter_user_id,
            invitation_id=invite.id,
            email=invite.email,
            role=invite.role,
        )

        logger.info(
            "Billing.invite_created | org={org} email={email} role={role} by={by}",
            org=organization_id,
            email=normalized_email,
            role=role_value,
            by=inviter_user_id,
        )
        return OrganizationInviteCreated(
            id=invite.id,
            organization_id=invite.organization_id,
            email=invite.email,
            role=invite.role,
            expires_at=invite.expires_at,
            token=raw_token,
            created_at=invite.created_at,
        )

    async def list_active_invites(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
    ) -> OrganizationInviteListResponse:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(OrganizationInvite)
            .where(
                OrganizationInvite.organization_id == organization_id,
                OrganizationInvite.is_accepted.is_(False),
                OrganizationInvite.expires_at > now,
            )
            .order_by(OrganizationInvite.created_at.desc())
        )
        rows = list(result.scalars().all())
        return OrganizationInviteListResponse(
            items=[OrganizationInviteRead.model_validate(row) for row in rows],
            total=len(rows),
        )

    async def revoke_invite(
        self,
        db: AsyncSession,
        organization_id: uuid.UUID,
        invite_id: uuid.UUID,
    ) -> None:
        invite = await db.scalar(
            select(OrganizationInvite).where(
                OrganizationInvite.id == invite_id,
                OrganizationInvite.organization_id == organization_id,
            )
        )
        if invite is None:
            raise InviteServiceError("Invitation not found.", status_code=404)
        deleted = db.delete(invite)
        if hasattr(deleted, "__await__"):
            await deleted  # type: ignore[misc]
        await db.flush()
        logger.info(
            "Billing.invite_revoked | org={org} invite_id={invite_id}",
            org=organization_id,
            invite_id=invite_id,
        )

    async def accept_invite(
        self,
        db: AsyncSession,
        raw_token: str,
        user: User,
    ) -> AcceptOrganizationInviteResponse:
        digest = hash_invite_token(raw_token)
        invite = await db.scalar(
            select(OrganizationInvite).where(OrganizationInvite.token_hash == digest)
        )
        if invite is None:
            raise InviteNotFoundError()

        if invite.is_accepted:
            raise InviteServiceError("Invitation has already been accepted.", status_code=409)

        now = datetime.now(timezone.utc)
        expires_at = invite.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise InviteExpiredError()

        user_email = (user.email or "").strip().lower()
        if user_email != invite.email.strip().lower():
            raise InviteServiceError(
                "Invitation email does not match the authenticated user.",
                status_code=403,
            )

        role = self._parse_role(invite.role)

        existing = await db.scalar(
            select(UserCompanyWorkspace).where(
                UserCompanyWorkspace.user_id == user.id,
                UserCompanyWorkspace.company_id == invite.organization_id,
            )
        )
        if existing is not None:
            existing.role = role
            membership = existing
        else:
            membership = UserCompanyWorkspace(
                user_id=user.id,
                company_id=invite.organization_id,
                role=role,
            )
            db.add(membership)

        invite.is_accepted = True
        # Switch active workspace context to the invited organization.
        user.company_id = invite.organization_id
        user.role = role
        await db.flush()

        logger.info(
            "Billing.invite_accepted | org={org} user_id={user_id} role={role}",
            org=invite.organization_id,
            user_id=user.id,
            role=role.value,
        )
        return AcceptOrganizationInviteResponse(
            organization_id=invite.organization_id,
            role=role.value,
            membership_id=membership.id,
            email=invite.email,
        )


invite_service = InviteService()
