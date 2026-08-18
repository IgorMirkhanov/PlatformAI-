from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.security import hash_password
from app.models.core_models import (
    Company,
    SubscriptionPlanName,
    TeamInvitation,
    TeamInvitationStatus,
    UserCompanyWorkspace,
    UserRole,
)
from app.models.users import User
from app.schemas.team_schemas import (
    AcceptTeamInviteRequest,
    AcceptTeamInviteResponse,
    CompanyWorkspaceRead,
    CreateCompanyRequest,
    CreateCompanyResponse,
    CurrentUserResponse,
    OrganizationsListResponse,
    SwitchCompanyRequest,
    SwitchCompanyResponse,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamInvitationRead,
    TeamMemberRead,
    TeamMembersResponse,
    UpdateCurrentUserRequest,
    UpdateTeamMemberRoleRequest,
)
from app.services.security_audit_service import security_audit_service

# Seat quotas mirrored by /organizations/usage.
TEAM_SEAT_LIMITS: dict[SubscriptionPlanName, int] = {
    SubscriptionPlanName.FREE: 3,
    SubscriptionPlanName.PRO: 15,
    SubscriptionPlanName.ENTERPRISE: 999,
}

_ADMIN_INVITE_ROLES = frozenset({UserRole.PROMPT_ENGINEER, UserRole.OPERATOR})


def _hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


class TeamService:
    """Multi-tenant team membership and invitation lifecycle."""

    INVITE_TTL_DAYS = 7

    async def get_current_user_profile(self, user: User) -> CurrentUserResponse:
        return CurrentUserResponse.model_validate(user)

    async def list_organizations(
        self,
        db: AsyncSession,
        *,
        current_user: User,
    ) -> OrganizationsListResponse:
        result = await db.execute(
            select(UserCompanyWorkspace, Company)
            .join(Company, Company.id == UserCompanyWorkspace.company_id)
            .where(UserCompanyWorkspace.user_id == current_user.id)
            .order_by(Company.created_at.asc())
        )
        rows = result.all()
        organizations: list[CompanyWorkspaceRead] = []
        for membership, company in rows:
            organizations.append(
                CompanyWorkspaceRead(
                    id=company.id,
                    name=company.name,
                    role=membership.role,
                    timezone=company.timezone,
                    is_active=company.id == current_user.company_id,
                )
            )

        if not organizations:
            company = await self._ensure_primary_company(db, current_user)
            organizations.append(
                CompanyWorkspaceRead(
                    id=company.id,
                    name=company.name,
                    role=current_user.role,
                    timezone=company.timezone,
                    is_active=True,
                )
            )

        return OrganizationsListResponse(
            active_company_id=current_user.company_id,
            organizations=organizations,
        )

    async def create_company(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        payload: CreateCompanyRequest,
    ) -> CreateCompanyResponse:
        company = Company(
            name=payload.name.strip(),
            owner_user_id=current_user.id,
            timezone=current_user.timezone or "Asia/Almaty",
        )
        db.add(company)
        await db.flush()

        membership = UserCompanyWorkspace(
            user_id=current_user.id,
            company_id=company.id,
            role=UserRole.OWNER,
        )
        db.add(membership)

        current_user.company_id = company.id
        current_user.company_name = company.name
        current_user.role = UserRole.OWNER
        await db.flush()

        from app.services.crm.pipeline_service import pipeline_service

        await pipeline_service.create_default_pipeline(db, company.id)

        logger.info(
            "Team.company_created | user_id={user_id} company_id={company_id}",
            user_id=current_user.id,
            company_id=company.id,
        )

        from app.core.auth import mint_user_token

        return CreateCompanyResponse(
            company=CompanyWorkspaceRead(
                id=company.id,
                name=company.name,
                role=UserRole.OWNER,
                timezone=company.timezone,
                is_active=True,
            ),
            access_token=mint_user_token(current_user),
        )

    async def switch_company(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        payload: SwitchCompanyRequest,
    ) -> SwitchCompanyResponse:
        result = await db.execute(
            select(UserCompanyWorkspace, Company)
            .join(Company, Company.id == UserCompanyWorkspace.company_id)
            .where(
                UserCompanyWorkspace.user_id == current_user.id,
                UserCompanyWorkspace.company_id == payload.company_id,
            )
        )
        row = result.first()
        if row is None:
            raise ValueError("Organization membership not found.")

        membership, company = row
        current_user.company_id = company.id
        current_user.company_name = company.name
        current_user.role = membership.role
        await db.flush()

        logger.info(
            "Team.company_switched | user_id={user_id} company_id={company_id}",
            user_id=current_user.id,
            company_id=company.id,
        )

        from app.core.auth import mint_user_token

        return SwitchCompanyResponse(
            company_id=company.id,
            company_name=company.name,
            role=membership.role,
            timezone=company.timezone,
            access_token=mint_user_token(current_user),
        )

    async def update_current_user(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        payload: UpdateCurrentUserRequest,
        allow_company_rename: bool = False,
    ) -> CurrentUserResponse:
        if payload.full_name is not None:
            current_user.full_name = payload.full_name.strip()

        if payload.timezone is not None:
            current_user.timezone = payload.timezone.strip()
            company = await self._get_company(db, current_user.company_id)
            if company is not None:
                company.timezone = payload.timezone.strip()

        if payload.company_name is not None:
            if not allow_company_rename:
                raise ValueError("Only owners and admins can rename the organization.")
            company = await self._get_company(db, current_user.company_id)
            if company is not None:
                company.name = payload.company_name.strip()
                current_user.company_name = company.name

        await db.flush()
        return CurrentUserResponse.model_validate(current_user)

    async def apply_workspace_context(
        self,
        db: AsyncSession,
        user: User,
        company_id: uuid.UUID,
        *,
        persist: bool = False,
    ) -> User:
        """Bind request-scoped company/role from membership.

        By default uses ``set_committed_value`` so middleware auto-commit cannot
        overwrite the user's persisted active company after a switch.
        Explicit switch/create paths pass ``persist=True``.
        """
        result = await db.execute(
            select(UserCompanyWorkspace, Company)
            .join(Company, Company.id == UserCompanyWorkspace.company_id)
            .where(
                UserCompanyWorkspace.user_id == user.id,
                UserCompanyWorkspace.company_id == company_id,
            )
        )
        row = result.first()
        if row is None:
            raise ValueError("Invalid workspace context.")

        membership, company = row
        if persist:
            user.company_id = company.id
            user.company_name = company.name
            user.role = membership.role
        else:
            set_committed_value(user, "company_id", company.id)
            set_committed_value(user, "company_name", company.name)
            set_committed_value(user, "role", membership.role)
        return user

    async def list_members(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        include_pending_invites: bool = True,
    ) -> TeamMembersResponse:
        await self._expire_stale_invites(db, current_user.company_id)

        members_result = await db.execute(
            select(User, UserCompanyWorkspace)
            .join(
                UserCompanyWorkspace,
                UserCompanyWorkspace.user_id == User.id,
            )
            .where(UserCompanyWorkspace.company_id == current_user.company_id)
            .order_by(User.created_at.asc())
        )
        rows = members_result.all()

        invite_items: list[TeamInvitationRead] = []
        if include_pending_invites:
            invites_result = await db.execute(
                select(TeamInvitation)
                .where(
                    TeamInvitation.company_id == current_user.company_id,
                    TeamInvitation.status == TeamInvitationStatus.PENDING,
                )
                .order_by(TeamInvitation.created_at.desc())
            )
            invites = invites_result.scalars().all()
            invite_items = [TeamInvitationRead.model_validate(invite) for invite in invites]

        member_items = [
            TeamMemberRead(
                id=member.id,
                email=member.email,
                full_name=member.full_name,
                company_name=member.company_name,
                company_id=current_user.company_id,
                role=membership.role,
                created_at=member.created_at,
            )
            for member, membership in rows
        ]

        logger.info(
            "Team.list_members | company_id={company_id} members={members} pending={pending}",
            company_id=current_user.company_id,
            members=len(member_items),
            pending=len(invite_items),
        )

        return TeamMembersResponse(
            company_id=current_user.company_id,
            members=member_items,
            pending_invitations=invite_items,
            total_members=len(member_items),
            total_pending=len(invite_items),
        )

    async def invite_member(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        payload: TeamInviteRequest,
        ip_address: str | None = None,
    ) -> TeamInviteResponse:
        if current_user.role == UserRole.ADMIN and payload.role not in _ADMIN_INVITE_ROLES:
            raise ValueError("Admins may only invite Prompt Engineers or Operators.")

        await self._ensure_seat_available(db, current_user.company_id)

        normalized_email = payload.email.strip().lower()

        existing_user = await db.execute(select(User).where(User.email == normalized_email))
        if existing_user.scalar_one_or_none() is not None:
            raise ValueError("A user with this email already exists on the platform.")

        pending = await db.execute(
            select(TeamInvitation).where(
                TeamInvitation.company_id == current_user.company_id,
                TeamInvitation.email == normalized_email,
                TeamInvitation.status == TeamInvitationStatus.PENDING,
            )
        )
        if pending.scalar_one_or_none() is not None:
            raise ValueError("An active invitation already exists for this email.")

        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(days=self.INVITE_TTL_DAYS)
        invitation = TeamInvitation(
            company_id=current_user.company_id,
            email=normalized_email,
            role=payload.role,
            token=_hash_invite_token(raw_token),
            expires_at=expires_at,
            status=TeamInvitationStatus.PENDING,
            invited_by_user_id=current_user.id,
        )
        db.add(invitation)
        await db.flush()
        await security_audit_service.invite_created(
            db,
            organization_id=current_user.company_id,
            actor_user_id=current_user.id,
            invitation_id=invitation.id,
            email=invitation.email,
            role=invitation.role.value,
            ip_address=ip_address,
        )

        logger.info(
            "Team.invite_created | company_id={company_id} email={email} role={role} invited_by={user_id}",
            company_id=current_user.company_id,
            email=normalized_email,
            role=payload.role.value,
            user_id=current_user.id,
        )

        return TeamInviteResponse(
            invitation_id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            token=raw_token,
            expires_at=invitation.expires_at,
        )

    async def accept_invite(
        self,
        db: AsyncSession,
        payload: AcceptTeamInviteRequest,
    ) -> AcceptTeamInviteResponse:
        normalized_email = payload.email.strip().lower()
        raw_token = payload.token.strip()
        invitation = await self._find_invitation_by_token(db, raw_token)
        if invitation is None:
            raise ValueError("Invitation token is invalid.")

        if invitation.status != TeamInvitationStatus.PENDING:
            raise ValueError("Invitation is no longer active.")

        if invitation.expires_at < datetime.now(UTC):
            invitation.status = TeamInvitationStatus.EXPIRED
            await db.flush()
            raise ValueError("Invitation token has expired.")

        if invitation.email != normalized_email:
            raise ValueError("Invitation email does not match.")

        await self._ensure_seat_available(db, invitation.company_id)

        existing = await db.execute(select(User).where(User.email == normalized_email))
        if existing.scalar_one_or_none() is not None:
            raise ValueError("A user with this email already exists.")

        company = await self._get_company(db, invitation.company_id)
        company_name = company.name if company is not None else "MP.AI Workspace"

        user = User(
            email=normalized_email,
            hashed_password=hash_password(payload.password),
            company_name=company_name,
            full_name=payload.full_name.strip() or normalized_email.split("@")[0],
            company_id=invitation.company_id,
            role=invitation.role,
        )
        db.add(user)
        await db.flush()

        db.add(
            UserCompanyWorkspace(
                user_id=user.id,
                company_id=invitation.company_id,
                role=invitation.role,
            )
        )

        invitation.status = TeamInvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(UTC)
        # Normalize legacy plaintext tokens to hash at accept time.
        if invitation.token == raw_token:
            invitation.token = _hash_invite_token(raw_token)
        await db.flush()

        logger.info(
            "Team.invite_accepted | company_id={company_id} user_id={user_id} role={role}",
            company_id=invitation.company_id,
            user_id=user.id,
            role=invitation.role.value,
        )

        return AcceptTeamInviteResponse(
            user_id=user.id,
            company_id=user.company_id,
            email=user.email,
            role=user.role,
        )

    async def update_member_role(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        member_id: uuid.UUID,
        payload: UpdateTeamMemberRoleRequest,
        ip_address: str | None = None,
    ) -> TeamMemberRead:
        if member_id == current_user.id:
            raise ValueError("You cannot change your own role.")

        if payload.role == UserRole.OWNER and current_user.role != UserRole.OWNER:
            raise ValueError("Only owners can assign the OWNER role.")

        member, membership = await self._get_company_membership(
            db, current_user.company_id, member_id
        )

        if membership.role == UserRole.OWNER and current_user.role != UserRole.OWNER:
            raise ValueError("Only owners can change another owner's role.")

        if membership.role == UserRole.OWNER and payload.role != UserRole.OWNER:
            owners = await self._count_owners(db, current_user.company_id)
            if owners <= 1:
                raise ValueError("Cannot change role of the last workspace owner.")

        if (
            current_user.role == UserRole.ADMIN
            and payload.role == UserRole.ADMIN
            and membership.role != UserRole.ADMIN
        ):
            raise ValueError("Admins cannot promote members to Admin. Ask an owner.")

        previous_role = membership.role
        membership.role = payload.role
        # Keep denormalized User.role in sync only for the member's active workspace.
        if member.company_id == current_user.company_id:
            member.role = payload.role
        await db.flush()
        await security_audit_service.role_changed(
            db,
            organization_id=current_user.company_id,
            actor_user_id=current_user.id,
            target_user_id=member.id,
            previous_role=previous_role.value,
            new_role=payload.role.value,
            ip_address=ip_address,
        )

        logger.info(
            "Team.role_updated | company_id={company_id} member_id={member_id} from={prev} to={new} by={actor}",
            company_id=current_user.company_id,
            member_id=member.id,
            prev=previous_role.value,
            new=payload.role.value,
            actor=current_user.id,
        )
        return TeamMemberRead(
            id=member.id,
            email=member.email,
            full_name=member.full_name,
            company_name=member.company_name,
            company_id=current_user.company_id,
            role=membership.role,
            created_at=member.created_at,
        )

    async def revoke_member(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        member_id: uuid.UUID,
    ) -> None:
        if member_id == current_user.id:
            raise ValueError("You cannot revoke your own access.")

        member, membership = await self._get_company_membership(
            db, current_user.company_id, member_id
        )
        if membership.role == UserRole.OWNER:
            if current_user.role != UserRole.OWNER:
                raise ValueError("Only owners can revoke another owner.")
            owners = await self._count_owners(db, current_user.company_id)
            if owners <= 1:
                raise ValueError("Cannot revoke the last workspace owner.")

        company_id = current_user.company_id
        await db.delete(membership)
        await db.flush()

        if member.company_id == company_id:
            await self._rebind_active_company(db, member)

        logger.warning(
            "Team.member_revoked | company_id={company_id} member_id={member_id} by={actor}",
            company_id=company_id,
            member_id=member_id,
            actor=current_user.id,
        )

    async def cancel_invitation(
        self,
        db: AsyncSession,
        *,
        current_user: User,
        invitation_id: uuid.UUID,
    ) -> None:
        result = await db.execute(
            select(TeamInvitation).where(
                TeamInvitation.id == invitation_id,
                TeamInvitation.company_id == current_user.company_id,
            )
        )
        invitation = result.scalar_one_or_none()
        if invitation is None:
            raise ValueError("Invitation not found.")

        invitation.status = TeamInvitationStatus.EXPIRED
        await db.flush()
        logger.info(
            "Team.invite_cancelled | company_id={company_id} invitation_id={invitation_id}",
            company_id=current_user.company_id,
            invitation_id=invitation_id,
        )

    async def _get_company_membership(
        self,
        db: AsyncSession,
        company_id: uuid.UUID,
        member_id: uuid.UUID,
    ) -> tuple[User, UserCompanyWorkspace]:
        result = await db.execute(
            select(User, UserCompanyWorkspace)
            .join(
                UserCompanyWorkspace,
                UserCompanyWorkspace.user_id == User.id,
            )
            .where(
                User.id == member_id,
                UserCompanyWorkspace.company_id == company_id,
            )
        )
        row = result.first()
        if row is None:
            raise ValueError("Team member not found.")
        return row[0], row[1]

    async def _count_owners(self, db: AsyncSession, company_id: uuid.UUID) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(UserCompanyWorkspace)
            .where(
                UserCompanyWorkspace.company_id == company_id,
                UserCompanyWorkspace.role == UserRole.OWNER,
            )
        )
        return int(result.scalar_one() or 0)

    async def _get_company(
        self,
        db: AsyncSession,
        company_id: uuid.UUID,
    ) -> Company | None:
        result = await db.execute(select(Company).where(Company.id == company_id))
        return result.scalar_one_or_none()

    async def _ensure_primary_company(
        self,
        db: AsyncSession,
        user: User,
    ) -> Company:
        company = await self._get_company(db, user.company_id)
        if company is not None:
            existing = await db.execute(
                select(UserCompanyWorkspace).where(
                    UserCompanyWorkspace.user_id == user.id,
                    UserCompanyWorkspace.company_id == company.id,
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(
                    UserCompanyWorkspace(
                        user_id=user.id,
                        company_id=company.id,
                        role=user.role,
                    )
                )
                await db.flush()
            return company

        company = Company(
            id=user.company_id,
            name=user.company_name,
            owner_user_id=user.id,
            timezone=user.timezone or "Asia/Almaty",
        )
        db.add(company)
        await db.flush()
        db.add(
            UserCompanyWorkspace(
                user_id=user.id,
                company_id=company.id,
                role=user.role,
            )
        )
        await db.flush()

        from app.services.crm.pipeline_service import pipeline_service

        await pipeline_service.create_default_pipeline(db, company.id)
        return company

    async def _expire_stale_invites(self, db: AsyncSession, company_id: uuid.UUID) -> None:
        result = await db.execute(
            select(TeamInvitation).where(
                TeamInvitation.company_id == company_id,
                TeamInvitation.status == TeamInvitationStatus.PENDING,
                TeamInvitation.expires_at < datetime.now(UTC),
            )
        )
        stale = result.scalars().all()
        for invite in stale:
            invite.status = TeamInvitationStatus.EXPIRED
        if stale:
            await db.flush()

    async def _find_invitation_by_token(
        self,
        db: AsyncSession,
        raw_token: str,
    ) -> TeamInvitation | None:
        token_hash = _hash_invite_token(raw_token)
        result = await db.execute(
            select(TeamInvitation).where(TeamInvitation.token == token_hash)
        )
        invitation = result.scalar_one_or_none()
        if invitation is not None:
            return invitation
        # Legacy plaintext tokens (pre-hash migration).
        result = await db.execute(
            select(TeamInvitation).where(TeamInvitation.token == raw_token)
        )
        return result.scalar_one_or_none()

    async def _ensure_seat_available(self, db: AsyncSession, company_id: uuid.UUID) -> None:
        seats_used = await db.scalar(
            select(func.count())
            .select_from(UserCompanyWorkspace)
            .where(UserCompanyWorkspace.company_id == company_id)
        )
        pending = await db.scalar(
            select(func.count())
            .select_from(TeamInvitation)
            .where(
                TeamInvitation.company_id == company_id,
                TeamInvitation.status == TeamInvitationStatus.PENDING,
                TeamInvitation.expires_at >= datetime.now(UTC),
            )
        )
        company = await self._get_company(db, company_id)
        plan = SubscriptionPlanName.FREE
        if company is not None:
            from app.services.billing_service import billing_service

            try:
                billing = await billing_service.get_billing_status(db, company.owner_user_id)
                plan = billing.plan_name
            except Exception:
                plan = SubscriptionPlanName.FREE

        limit = TEAM_SEAT_LIMITS.get(plan, 3)
        used = int(seats_used or 0) + int(pending or 0)
        if used >= limit:
            raise ValueError(
                f"Team seat limit reached for plan {plan.value} ({limit} seats)."
            )

    async def _rebind_active_company(self, db: AsyncSession, user: User) -> None:
        result = await db.execute(
            select(UserCompanyWorkspace, Company)
            .join(Company, Company.id == UserCompanyWorkspace.company_id)
            .where(UserCompanyWorkspace.user_id == user.id)
            .order_by(Company.created_at.asc())
            .limit(1)
        )
        row = result.first()
        if row is None:
            return
        membership, company = row
        user.company_id = company.id
        user.company_name = company.name
        user.role = membership.role
        await db.flush()


team_service = TeamService()
