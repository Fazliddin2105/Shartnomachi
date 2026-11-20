from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, PageParams, require
from app.core.errors import NotFound
from app.core.rbac import Perm
from app.modules.audit import service as audit
from app.modules.users import service
from app.modules.users.models import User, UserRole, UserStatus
from app.modules.users.schemas import (
    AdminUserUpdate,
    CompanyCreate,
    CompanyOut,
    MemberAdd,
    ProfileOut,
    ProfileUpdate,
    UserOut,
    UserUpdate,
)

router = APIRouter(tags=["users"])


def _user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    if out.profile is not None and user.profile is not None:
        out.profile.has_pinfl = bool(user.profile.pinfl_hash)
    return out


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.patch("/me", response_model=UserOut)
async def update_me(body: UserUpdate, db: DB, user: CurrentUser) -> UserOut:
    return _user_out(await service.update_me(db, user, body))


@router.put("/me/profile", response_model=ProfileOut)
async def update_profile(body: ProfileUpdate, db: DB, user: CurrentUser) -> ProfileOut:
    profile = await service.update_profile(db, user, body)
    out = ProfileOut.model_validate(profile)
    out.has_pinfl = bool(profile.pinfl_hash)
    return out


@router.post(
    "/me/deletion-request", status_code=status.HTTP_202_ACCEPTED, summary="Shaxsiy ma'lumotlarni o'chirish so'rovi"
)
async def deletion_request(db: DB, user: CurrentUser) -> dict[str, str]:
    await service.request_deletion(db, user)
    return {"status": "deletion_requested"}


# --- companies ---------------------------------------------------------------

companies = APIRouter(prefix="/companies", tags=["companies"])


@companies.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_company(body: CompanyCreate, db: DB, user: CurrentUser) -> CompanyOut:
    return CompanyOut.model_validate(await service.create_company(db, user, body))


@companies.get("", response_model=list[CompanyOut])
async def list_companies(db: DB, user: CurrentUser) -> list[CompanyOut]:
    return [CompanyOut.model_validate(c) for c in await service.my_companies(db, user)]


@companies.post("/{company_id}/members", response_model=CompanyOut)
async def add_member(company_id: uuid.UUID, body: MemberAdd, db: DB, user: CurrentUser) -> CompanyOut:
    company = await service.add_member(db, company_id=company_id, actor=user, phone=body.phone, role=body.role)
    return CompanyOut.model_validate(company)


@companies.delete("/{company_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(company_id: uuid.UUID, user_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    await service.remove_member(db, company_id=company_id, actor=user, user_id=user_id)


# --- admin / moderation --------------------------------------------------------

admin = APIRouter(prefix="/admin/users", tags=["admin"])


@admin.get("", response_model=list[UserOut])
async def admin_list_users(
    db: DB,
    page: PageParams,
    _: Annotated[User, Depends(require(Perm.USERS_ADMIN))],
    role: UserRole | None = None,
    status_: UserStatus | None = None,
    phone: str | None = None,
) -> list[UserOut]:
    stmt = select(User).order_by(User.created_at.desc()).limit(page.limit).offset(page.offset)
    if role:
        stmt = stmt.where(User.role == role)
    if status_:
        stmt = stmt.where(User.status == status_)
    if phone:
        stmt = stmt.where(User.phone.contains(phone.strip()))
    return [_user_out(u) for u in await db.scalars(stmt)]


@admin.patch("/{user_id}", response_model=UserOut)
async def admin_update_user(
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    db: DB,
    actor: Annotated[User, Depends(require(Perm.USERS_ADMIN))],
) -> UserOut:
    target = await db.get(User, user_id)
    if target is None:
        raise NotFound("User not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(target, k, v)
    await audit.record(
        db,
        action="admin.user_update",
        entity="user",
        entity_id=user_id,
        actor_id=actor.id,
        meta={k: str(v) for k, v in changes.items()},
    )
    return _user_out(target)


@admin.post("/{user_id}/verify-lawyer", response_model=UserOut, summary="Yurist litsenziyasini tasdiqlash (moderator)")
async def verify_lawyer(
    user_id: uuid.UUID, db: DB, actor: Annotated[User, Depends(require(Perm.MODERATION))]
) -> UserOut:
    return _user_out(await service.verify_lawyer(db, actor=actor, user_id=user_id))
