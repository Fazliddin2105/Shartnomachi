"""Shared FastAPI dependencies: DB session, authentication, authorisation."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Unauthorized
from app.core.rbac import MFA_REQUIRED_ROLES, Perm, has_perm
from app.core.security import TokenClaims, decode_access_token
from app.db.session import get_db
from app.modules.users.models import User, UserStatus

# scope="function": the transaction commits *before* the response is sent. With the default ("request")
# the commit ran after the response, so a fast client (OTP request -> verify, token refresh) could read
# state that was not committed yet.
DB = Annotated[AsyncSession, Depends(get_db, scope="function")]

_bearer = HTTPBearer(auto_error=False)


async def get_claims(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> TokenClaims:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthorized()
    return decode_access_token(creds.credentials)


async def get_current_user(db: DB, claims: Annotated[TokenClaims, Depends(get_claims)]) -> User:
    user = await db.get(User, claims.user_id)
    if user is None or user.status in (UserStatus.BLOCKED, UserStatus.DELETED):
        raise Unauthorized("Account is not active", code="account_inactive")
    # Role changes take effect immediately even if the JWT still carries the old role.
    user.__dict__["_mfa"] = claims.mfa
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*perms: Perm) -> Callable[..., Coroutine[Any, Any, User]]:
    async def _dep(user: CurrentUser) -> User:
        for p in perms:
            if not has_perm(user.role, p):
                raise Forbidden(f"Missing permission: {p.value}", code="permission_denied")
        if user.role in MFA_REQUIRED_ROLES and not user.__dict__.get("_mfa"):
            raise Forbidden("Two-factor authentication required", code="mfa_required")
        return user

    return _dep


class Page:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PageParams = Annotated[Page, Depends()]
