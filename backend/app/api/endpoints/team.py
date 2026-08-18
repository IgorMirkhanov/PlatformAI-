import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import Permission, get_current_user, require_permission, require_roles, ROLE_PERMISSIONS
from app.models.core_models import UserRole
from app.models.users import User
from app.schemas.team_schemas import (
    AcceptTeamInviteRequest,
    AcceptTeamInviteResponse,
    CreateCompanyRequest,
    CreateCompanyResponse,
    CurrentUserResponse,
    OrganizationsListResponse,
    SwitchCompanyRequest,
    SwitchCompanyResponse,
    TeamInviteRequest,
    TeamInviteResponse,
    TeamMemberRead,
    TeamMembersResponse,
    UpdateCurrentUserRequest,
    UpdateTeamMemberRoleRequest,
)
from app.services.team_service import team_service

router = APIRouter(prefix="/team", tags=["team"])


@router.get("/me", response_model=CurrentUserResponse, summary="Get current authenticated user")
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> CurrentUserResponse:
    return await team_service.get_current_user_profile(current_user)


@router.patch("/me", response_model=CurrentUserResponse, summary="Update current user profile")
async def update_current_user_profile(
    payload: UpdateCurrentUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CurrentUserResponse:
    allow_rename = False
    if payload.company_name is not None:
        perms = ROLE_PERMISSIONS.get(current_user.role, frozenset())
        allow_rename = Permission.TEAM_MANAGE in perms
        if not allow_rename:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owners and admins can rename the organization.",
            )
        allow_rename = True
    try:
        return await team_service.update_current_user(
            db,
            current_user=current_user,
            payload=payload,
            allow_company_rename=allow_rename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/organizations",
    response_model=OrganizationsListResponse,
    summary="List organizations available to the current user",
)
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrganizationsListResponse:
    return await team_service.list_organizations(db, current_user=current_user)


@router.post(
    "/companies",
    response_model=CreateCompanyResponse,
    summary="Create a new organization workspace",
)
async def create_company(
    payload: CreateCompanyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CreateCompanyResponse:
    try:
        return await team_service.create_company(db, current_user=current_user, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/switch-company",
    response_model=SwitchCompanyResponse,
    summary="Switch active organization workspace",
)
async def switch_company(
    payload: SwitchCompanyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SwitchCompanyResponse:
    try:
        return await team_service.switch_company(db, current_user=current_user, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/members",
    response_model=TeamMembersResponse,
    summary="List company team members and pending invitations",
)
async def list_team_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TeamMembersResponse:
    try:
        perms = ROLE_PERMISSIONS.get(current_user.role, frozenset())
        include_pending = Permission.TEAM_MANAGE in perms
        return await team_service.list_members(
            db,
            current_user=current_user,
            include_pending_invites=include_pending,
        )
    except Exception as exc:
        logger.exception("Team.list_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load team members.",
        ) from exc


@router.post(
    "/invite",
    response_model=TeamInviteResponse,
    summary="Invite a team member by email",
)
async def invite_team_member(
    payload: TeamInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> TeamInviteResponse:
    try:
        return await team_service.invite_member(
            db,
            current_user=current_user,
            payload=payload,
            ip_address=request.client.host if request.client else None,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid invite payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Team.invite_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create team invitation.",
        ) from exc


@router.post(
    "/accept-invite",
    response_model=AcceptTeamInviteResponse,
    summary="Accept a pending team invitation",
)
async def accept_team_invite(
    payload: AcceptTeamInviteRequest,
    db: AsyncSession = Depends(get_db),
) -> AcceptTeamInviteResponse:
    try:
        return await team_service.accept_invite(db, payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Invalid accept payload", "issues": exc.errors()},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Team.accept_error | error={error}", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept team invitation.",
        ) from exc


@router.patch(
    "/members/{member_id}",
    response_model=TeamMemberRead,
    summary="Update a team member role",
)
async def update_team_member_role(
    member_id: uuid.UUID,
    payload: UpdateTeamMemberRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> TeamMemberRead:
    try:
        return await team_service.update_member_role(
            db,
            current_user=current_user,
            member_id=member_id,
            payload=payload,
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Team.update_role_error | member_id={member_id} error={error}", member_id=member_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update team member role.",
        ) from exc


@router.delete(
    "/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a team member's workspace access",
)
async def revoke_team_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await team_service.revoke_member(db, current_user=current_user, member_id=member_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Team.revoke_error | member_id={member_id} error={error}", member_id=member_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke team member.",
        ) from exc


@router.delete(
    "/invites/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a pending team invitation",
)
async def cancel_team_invitation(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
) -> None:
    try:
        await team_service.cancel_invitation(
            db,
            current_user=current_user,
            invitation_id=invitation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Team.cancel_invite_error | invitation_id={invitation_id} error={error}",
            invitation_id=invitation_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel invitation.",
        ) from exc
