"""Optional fastapi-users integration (JWT strategy over existing User table).

Primary auth surface remains ``/api/v1/auth`` (login/register/refresh/reset).
Set ``FASTAPI_USERS_ENABLED=true`` to expose fastapi-users ``/api/v1/users`` me/update.
"""

from __future__ import annotations

from fastapi import FastAPI
from loguru import logger

from app.core.config import settings

FASTAPI_USERS_ENABLED = bool(settings.FASTAPI_USERS_ENABLED)


def mount_fastapi_users(app: FastAPI) -> None:
    """Mount fastapi-users users router when enabled (login stays on /auth)."""
    if not FASTAPI_USERS_ENABLED:
        return

    import uuid
    from collections.abc import AsyncGenerator

    from fastapi import Depends
    from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
    from fastapi_users.authentication import (
        AuthenticationBackend,
        BearerTransport,
        JWTStrategy,
    )
    from fastapi_users.db import SQLAlchemyUserDatabase
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.database import get_db
    from app.models.users import User

    class UserReadFU(schemas.BaseUser[uuid.UUID]):
        full_name: str = ""
        company_name: str = ""
        company_id: uuid.UUID | None = None

    class UserUpdateFU(schemas.BaseUserUpdate):
        full_name: str | None = None

    class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
        reset_password_token_secret = str(settings.JWT_SECRET_KEY or "dev-reset")
        verification_token_secret = str(settings.JWT_SECRET_KEY or "dev-verify")

        async def on_after_forgot_password(self, user: User, token: str, request=None) -> None:
            from app.services.auth_token_service import email_stub

            email_stub.send_password_reset(email=user.email, reset_token=token)

    async def get_user_db(
        session: AsyncSession = Depends(get_db),
    ) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID], None]:
        yield SQLAlchemyUserDatabase(session, User)

    async def get_user_manager(
        user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),
    ) -> AsyncGenerator[UserManager, None]:
        yield UserManager(user_db)

    def get_jwt_strategy() -> JWTStrategy:
        return JWTStrategy(
            secret=str(settings.JWT_SECRET_KEY or "dev"),
            lifetime_seconds=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            algorithm=settings.JWT_ALGORITHM,
        )

    auth_backend = AuthenticationBackend(
        name="jwt",
        transport=BearerTransport(tokenUrl="/api/v1/auth/login"),
        get_strategy=get_jwt_strategy,
    )
    fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

    logger.info("FastAPIUsers.mount | prefix=/api/v1/users")
    app.include_router(
        fastapi_users.get_users_router(UserReadFU, UserUpdateFU),
        prefix="/api/v1/users",
        tags=["users"],
    )


__all__ = ["FASTAPI_USERS_ENABLED", "mount_fastapi_users"]
