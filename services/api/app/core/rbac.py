"""Role-based access control.

Roles map to coarse permissions here. Row-level checks ("only parties see
their contract") live in each module's service/policy layer.
"""

from __future__ import annotations

from enum import StrEnum

from app.modules.users.models import UserRole


class Perm(StrEnum):
    CONTRACTS_USE = "contracts:use"
    CONTRACT_TYPES_WRITE = "contract_types:write"
    RULES_WRITE = "rules:write"
    RULES_APPROVE = "rules:approve"
    SCAN_USE = "scan:use"
    CASES_USE = "cases:use"
    COMPANY_MANAGE = "company:manage"
    MODERATION = "moderation"
    CALENDAR_WRITE = "calendar:write"
    USERS_ADMIN = "users:admin"
    AUDIT_READ = "audit:read"


_BASE = {Perm.CONTRACTS_USE, Perm.SCAN_USE}

ROLE_PERMISSIONS: dict[UserRole, frozenset[Perm]] = {
    UserRole.CITIZEN: frozenset(_BASE),
    UserRole.BUSINESS: frozenset(_BASE | {Perm.COMPANY_MANAGE}),
    UserRole.LAWYER: frozenset(_BASE | {Perm.COMPANY_MANAGE, Perm.CASES_USE}),
    UserRole.EDITOR: frozenset(
        _BASE
        | {
            Perm.CONTRACT_TYPES_WRITE,
            Perm.RULES_WRITE,
            Perm.RULES_APPROVE,
            Perm.CALENDAR_WRITE,
        }
    ),
    UserRole.MODERATOR: frozenset(_BASE | {Perm.MODERATION}),
    UserRole.ADMIN: frozenset(Perm),
}

# Roles that must have TOTP 2FA enabled to use privileged endpoints.
MFA_REQUIRED_ROLES = frozenset({UserRole.EDITOR, UserRole.ADMIN})


def has_perm(role: UserRole, perm: Perm) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, frozenset())
