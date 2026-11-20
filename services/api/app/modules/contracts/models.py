from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.db.base import Base, Timestamps, UUIDPk
from app.db.types import EncryptedJSON, EncryptedString, JSONType, StrEnumType


class FormRequirement(StrEnum):
    SIMPLE = "simple"  # oddiy yozma shakl
    NOTARIAL = "notarial"  # notarial tasdiq
    REGISTRATION = "registration"  # davlat ro'yxatidan o'tkazish

    @property
    def rank(self) -> int:
        return {"simple": 0, "notarial": 1, "registration": 2}[self.value]


class ContractType(UUIDPk, Timestamps, Base):
    __tablename__ = "contract_types"

    code: Mapped[str] = mapped_column(String(64), unique=True)
    title_uz: Mapped[str] = mapped_column(String(255))
    title_ru: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    form_requirement: Mapped[FormRequirement] = mapped_column(
        StrEnumType(FormRequirement), default=FormRequirement.SIMPLE
    )
    # [{"when": {...condition...}, "form": "notarial", "reason": "..."}]
    form_rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    questionnaire: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    template: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    template_ru: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    # Mandatory elements used by the scanner: [{"code","title","patterns":[regex]}]
    required_elements: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # How to derive obligations on activation (see contracts.obligations_from_answers)
    obligation_templates: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    legal_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    detect_keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # Provenance of the current template (official lex.uz model form, or none). See templates module.
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONType)


class ClauseLibrary(UUIDPk, Timestamps, Base):
    """Optional clauses users can add (jarima, kafolat, maxfiylik, fors-major...)."""

    __tablename__ = "clause_library"

    contract_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_types.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body_template: Mapped[str] = mapped_column(Text)
    params_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    risk_level: Mapped[str] = mapped_column(String(8), default="low")  # low | medium | high
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ContractOrigin(StrEnum):
    GENERATED = "generated"
    UPLOADED = "uploaded"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"  # Kutilmoqda
    ACTIVE = "active"  # Faol
    EXPIRED = "expired"  # Muddati tugagan
    COMPLETED = "completed"  # Yakunlangan
    DISPUTED = "disputed"  # Nizoli
    CANCELLED = "cancelled"


class Contract(UUIDPk, Timestamps, Base):
    __tablename__ = "contracts"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_types.id", ondelete="RESTRICT"))
    origin: Mapped[ContractOrigin] = mapped_column(StrEnumType(ContractOrigin), default=ContractOrigin.GENERATED)
    status: Mapped[ContractStatus] = mapped_column(
        StrEnumType(ContractStatus), default=ContractStatus.DRAFT, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    language: Mapped[str] = mapped_column(String(5), default="uz")
    answers: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, default=dict)  # questionnaire (PII)
    selected_clauses: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # last summary
    form_requirement: Mapped[FormRequirement] = mapped_column(
        StrEnumType(FormRequirement), default=FormRequirement.SIMPLE
    )
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date, index=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column()
    activated_at: Mapped[datetime | None] = mapped_column()

    parties: Mapped[list[ContractParty]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", lazy="selectin", order_by="ContractParty.created_at"
    )
    contract_type: Mapped[ContractType | None] = relationship(lazy="selectin")


class ContractVersion(UUIDPk, Base):
    __tablename__ = "contract_versions"
    __table_args__ = (UniqueConstraint("contract_id", "number"),)

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON)  # rendered contract, encrypted at rest
    sha256: Mapped[str] = mapped_column(String(64))  # sha256(canonical_json(content))
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))  # DOCX
    pdf_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    # Multi-signature PKCS#7 (all parties, E-IMZO) - the legally strongest artefact
    signed_container_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="SET NULL"))
    validation: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    red_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PartyRole(StrEnum):
    A = "A"
    B = "B"
    LAWYER = "lawyer"
    OBSERVER = "observer"


class ContractParty(UUIDPk, Base):
    __tablename__ = "contract_parties"

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    role: Mapped[PartyRole] = mapped_column(StrEnumType(PartyRole))
    represents: Mapped[PartyRole | None] = mapped_column(StrEnumType(PartyRole))  # lawyer acting for A or B
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    display_name: Mapped[str | None] = mapped_column(String(255))
    invite_phone: Mapped[str | None] = mapped_column(EncryptedString)
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Blind index of invite_phone: lets the invitee find the invitation after an OTP login.
    invite_phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    invited_at: Mapped[datetime | None] = mapped_column()
    joined_at: Mapped[datetime | None] = mapped_column()
    confirmed_at: Mapped[datetime | None] = mapped_column()  # approved current version
    # Negotiation: consent to the *terms* (answers + clauses) before the common document is generated
    agreed_terms_sha256: Mapped[str | None] = mapped_column(String(64))
    agreed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    contract: Mapped[Contract] = relationship(back_populates="parties")


class ObjectionStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ContractObjection(UUIDPk, Base):
    """A party's disagreement with the terms, optionally with concrete proposed values (counter-offer)."""

    __tablename__ = "contract_objections"

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_parties.id", ondelete="SET NULL"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    side: Mapped[str] = mapped_column(String(8))  # A | B
    comment: Mapped[str] = mapped_column(EncryptedString)
    fields: Mapped[list[str]] = mapped_column(JSONType, default=list)  # questionnaire keys concerned
    proposed: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, default=dict)  # {key: value}
    status: Mapped[ObjectionStatus] = mapped_column(
        StrEnumType(ObjectionStatus), default=ObjectionStatus.OPEN, index=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column()
    resolution_note: Mapped[str | None] = mapped_column(EncryptedString)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ContractEvent(UUIDPk, Base):
    """Human-readable negotiation timeline (the tamper-evident trail stays in the audit log)."""

    __tablename__ = "contract_events"

    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    side: Mapped[str | None] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ApprovalMethod(StrEnum):
    OTP = "otp"
    ONEID = "oneid"
    EIMZO = "eimzo"


class ContractApproval(UUIDPk, Base):
    """Immutable evidence of consent to a specific version (spec §5.5)."""

    __tablename__ = "contract_approvals"
    __table_args__ = (UniqueConstraint("version_id", "party_id"),)

    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contract_versions.id", ondelete="RESTRICT"), index=True)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contract_parties.id", ondelete="RESTRICT"))
    user_id: Mapped[uuid.UUID] = mapped_column()
    method: Mapped[ApprovalMethod] = mapped_column(StrEnumType(ApprovalMethod))
    sha256: Mapped[str] = mapped_column(String(64))  # hash the signer saw
    ip: Mapped[str | None] = mapped_column(String(64))
    device: Mapped[str | None] = mapped_column(String(255))
    signed_at: Mapped[datetime] = mapped_column(default=utcnow)
    # {"otp_id": ..., "phone_masked": ...} | {"pkcs7": ..., "cert_serial": ...}
    proof: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # HMAC over (version sha, party, user, method, signed_at) => server-side seal
    seal: Mapped[str] = mapped_column(String(64))


class ArchivedContract(UUIDPk, Base):
    """A signed contract in a party's personal archive (created when all parties have signed).

    One row per user: each side keeps its own entry (notes/tags are private to that user), while the
    document itself stays the immutable signed version referenced by `version_id` / `sha256`.
    """

    __tablename__ = "archived_contracts"
    __table_args__ = (UniqueConstraint("user_id", "version_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contract_versions.id", ondelete="RESTRICT"))
    version_number: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    side: Mapped[str | None] = mapped_column(String(8))  # A | B — the owner's side in the contract
    title: Mapped[str] = mapped_column(String(255))
    type_code: Mapped[str | None] = mapped_column(String(64))
    counterparty: Mapped[str | None] = mapped_column(EncryptedString)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="UZS")
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    signed_at: Mapped[datetime] = mapped_column()
    note: Mapped[str | None] = mapped_column(EncryptedString)  # private note of this user
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    archived_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
