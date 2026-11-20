from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import hmac_sha256
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.timeutils import utcnow
from app.modules.audit import service as audit
from app.modules.auth.otp import normalize_phone
from app.modules.users.models import (
    Company,
    CompanyMember,
    CompanyRole,
    Profile,
    ProfileType,
    User,
    UserRole,
    UserStatus,
)
from app.modules.users.schemas import CompanyCreate, ProfileUpdate, UserUpdate


async def update_me(db: AsyncSession, user: User, data: UserUpdate) -> User:
    if data.email is not None:
        exists = await db.scalar(select(User.id).where(User.email == data.email, User.id != user.id))
        if exists:
            raise Conflict("Email is already used", code="email_taken")
        user.email = data.email
    if data.locale is not None:
        user.locale = data.locale
    if data.channels is not None:
        user.preferences = {**(user.preferences or {}), "channels": data.channels}
    if data.telegram_chat_id is not None:
        user.telegram_chat_id = data.telegram_chat_id
    await db.flush()
    return user


async def update_profile(db: AsyncSession, user: User, data: ProfileUpdate) -> Profile:
    profile = user.profile
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
        user.profile = profile
    changes = data.model_dump(exclude_unset=True)
    if changes.get("pinfl"):
        profile.pinfl_hash = hmac_sha256(changes["pinfl"], purpose="pinfl")
    if "license_no" in changes:
        # Any change of license number must be re-verified by a moderator.
        profile.license_verified_at = None
    if changes.get("type") == ProfileType.LAWYER:
        # Lawyer role is granted only after license verification by a moderator.
        changes.pop("type")
    for k, v in changes.items():
        setattr(profile, k, v)
    await db.flush()
    await audit.record(
        db,
        action="profile.update",
        entity="user",
        entity_id=user.id,
        actor_id=user.id,
        meta={"fields": sorted(changes)},
    )
    return profile


async def request_deletion(db: AsyncSession, user: User) -> None:
    user.status = UserStatus.DELETION_REQUESTED
    user.deleted_at = utcnow()
    await audit.record(db, action="user.deletion_requested", entity="user", entity_id=user.id, actor_id=user.id)


async def verify_lawyer(db: AsyncSession, *, actor: User, user_id: uuid.UUID) -> User:
    target = await db.get(User, user_id)
    if target is None or target.profile is None:
        raise NotFound("User not found")
    if not target.profile.license_no:
        raise ValidationFailed("User has no license number", code="license_missing")
    target.profile.type = ProfileType.LAWYER
    target.profile.license_verified_at = utcnow()
    target.role = UserRole.LAWYER
    await audit.record(
        db,
        action="lawyer.verified",
        entity="user",
        entity_id=target.id,
        actor_id=actor.id,
        meta={"license_no": target.profile.license_no},
    )
    return target


# --- companies ---------------------------------------------------------------


async def create_company(db: AsyncSession, user: User, data: CompanyCreate) -> Company:
    if await db.scalar(select(Company.id).where(Company.stir == data.stir)):
        raise Conflict("Company with this STIR already exists", code="stir_taken")
    company = Company(owner_id=user.id, **data.model_dump())
    company.members = [CompanyMember(user_id=user.id, role=CompanyRole.OWNER)]
    db.add(company)
    if user.role == UserRole.CITIZEN:
        user.role = UserRole.BUSINESS
    await db.flush()
    await audit.record(db, action="company.create", entity="company", entity_id=company.id, actor_id=user.id)
    return company


async def my_companies(db: AsyncSession, user: User) -> list[Company]:
    rows = await db.scalars(
        select(Company).join(CompanyMember).where(CompanyMember.user_id == user.id).order_by(Company.name)
    )
    return list(rows)


async def company_role(db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID) -> CompanyRole | None:
    return await db.scalar(
        select(CompanyMember.role).where(CompanyMember.company_id == company_id, CompanyMember.user_id == user_id)
    )


async def _require_company_admin(db: AsyncSession, company_id: uuid.UUID, user: User) -> Company:
    company = await db.get(Company, company_id)
    if company is None:
        raise NotFound("Company not found")
    role = await company_role(db, company_id, user.id)
    if role not in (CompanyRole.OWNER, CompanyRole.ADMIN):
        raise Forbidden("Only company owner/admin can manage members")
    return company


async def add_member(db: AsyncSession, *, company_id: uuid.UUID, actor: User, phone: str, role: CompanyRole) -> Company:
    company = await _require_company_admin(db, company_id, actor)
    if role == CompanyRole.OWNER:
        raise ValidationFailed("Ownership transfer is a separate operation", code="owner_role")
    member_user = await db.scalar(select(User).where(User.phone == normalize_phone(phone)))
    if member_user is None:
        raise NotFound("User with this phone is not registered", code="user_not_registered")
    if await company_role(db, company_id, member_user.id):
        raise Conflict("User is already a member", code="already_member")
    db.add(CompanyMember(company_id=company_id, user_id=member_user.id, role=role))
    await db.flush()
    await db.refresh(company, ["members"])
    await audit.record(
        db,
        action="company.member_add",
        entity="company",
        entity_id=company_id,
        actor_id=actor.id,
        meta={"user_id": str(member_user.id), "role": role.value},
    )
    return company


async def remove_member(db: AsyncSession, *, company_id: uuid.UUID, actor: User, user_id: uuid.UUID) -> None:
    company = await _require_company_admin(db, company_id, actor)
    if user_id == company.owner_id:
        raise ValidationFailed("Owner cannot be removed", code="owner_role")
    member = await db.get(CompanyMember, (company_id, user_id))
    if member is None:
        raise NotFound("Member not found")
    await db.delete(member)
    await audit.record(
        db,
        action="company.member_remove",
        entity="company",
        entity_id=company_id,
        actor_id=actor.id,
        meta={"user_id": str(user_id)},
    )
