from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, PageParams
from app.core.crypto import canonical_json, sha256_hex
from app.core.errors import NotFound
from app.core.ratelimit import get_limiter
from app.modules.anchoring import service as anchoring
from app.modules.anchoring.models import LeafKind
from app.modules.approvals import service as approvals
from app.modules.contracts import negotiation, service
from app.modules.contracts.models import (
    ApprovalMethod,
    Contract,
    ContractParty,
    ContractStatus,
    ContractType,
    ContractVersion,
    FormRequirement,
    PartyRole,
)
from app.modules.files import service as files
from app.modules.users.models import User

router = APIRouter(tags=["contracts"])


class ContractTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    title_uz: str
    title_ru: str | None
    description: str | None
    form_requirement: FormRequirement
    has_ru_template: bool = False
    version: int = 1
    source: dict[str, Any] | None = None


class ContractTypeDetail(ContractTypeOut):
    questionnaire: dict[str, Any]
    legal_refs: list[dict[str, Any]]
    library: list[dict[str, Any]] = Field(default_factory=list)


class ContractCreate(BaseModel):
    type_code: str
    title: str | None = Field(default=None, max_length=255)
    my_role: PartyRole = Field(description="A | B | lawyer")
    represents: PartyRole | None = Field(default=None, description="Yurist bo'lsa: A yoki B nomidan")
    company_id: uuid.UUID | None = None


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: PartyRole
    represents: PartyRole | None
    user_id: uuid.UUID | None
    company_id: uuid.UUID | None
    display_name: str | None
    invited_at: datetime | None
    joined_at: datetime | None
    confirmed_at: datetime | None


class ContractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_id: uuid.UUID
    company_id: uuid.UUID | None
    type_id: uuid.UUID | None
    origin: str
    status: ContractStatus
    title: str
    language: str
    form_requirement: FormRequirement
    total_amount: Decimal | None
    currency: str
    starts_on: date | None
    ends_on: date | None
    current_version_id: uuid.UUID | None
    validation: dict[str, Any]
    parties: list[PartyOut]
    created_at: datetime
    updated_at: datetime
    party_names: dict[str, str | None] = Field(default_factory=dict)


def contract_out(c: Any, cls: type[ContractOut] | None = None) -> Any:
    """Adds display names of the parties (from the encrypted questionnaire) for list views."""
    out = (cls or ContractOut).model_validate(c)
    out.party_names = service.party_names(c)
    return out


class ContractDetail(ContractOut):
    answers: dict[str, Any]
    selected_clauses: list[dict[str, Any]]


class SelectedClause(BaseModel):
    clause_id: uuid.UUID
    params: dict[str, Any] = Field(default_factory=dict)


class AnswersPatch(BaseModel):
    answers: dict[str, Any]
    merge: bool = True
    selected_clauses: list[SelectedClause] | None = Field(
        default=None, description='[{"clause_id": "...", "params": {...}}]'
    )


class GenerateIn(BaseModel):
    language: Literal["uz", "ru"] = "uz"


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    number: int
    sha256: str
    file_id: uuid.UUID | None
    pdf_file_id: uuid.UUID | None
    signed_container_file_id: uuid.UUID | None = None
    validation: dict[str, Any]
    red_acknowledged: bool
    created_at: datetime


class InviteIn(BaseModel):
    phone: str
    role: PartyRole = PartyRole.B
    represents: PartyRole | None = None
    display_name: str | None = None


class AcceptIn(BaseModel):
    token: str


class InvitationOut(BaseModel):
    party_id: uuid.UUID
    role: PartyRole
    role_title: str
    invited_at: datetime | None
    expires_at: datetime | None
    contract_id: uuid.UUID
    contract_title: str
    contract_status: ContractStatus
    type_code: str | None
    total_amount: str | None
    currency: str
    inviter_name: str | None
    current_version: int | None
    current_sha256: str | None


class ApproveIn(BaseModel):
    method: ApprovalMethod = ApprovalMethod.OTP
    code: str | None = None
    pkcs7: str | None = None
    sha256: str = Field(description="Foydalanuvchiga ko'rsatilgan hujjat xeshi")


class StatusIn(BaseModel):
    status: Literal[ContractStatus.COMPLETED, ContractStatus.DISPUTED, ContractStatus.ACTIVE, ContractStatus.CANCELLED]
    reason: str | None = None


# --- types ---------------------------------------------------------------------------


@router.get("/contract-types", response_model=list[ContractTypeOut], summary="Shartnoma turlari")
async def list_types(db: DB) -> list[ContractTypeOut]:
    rows = await db.scalars(
        select(ContractType).where(ContractType.is_active.is_(True)).order_by(ContractType.title_uz)
    )
    return [ContractTypeOut.model_validate(t).model_copy(update={"has_ru_template": bool(t.template_ru)}) for t in rows]


@router.get("/contract-types/{code}", response_model=ContractTypeDetail, summary="Savolnoma va bandlar kutubxonasi")
async def get_type(code: str, db: DB) -> ContractTypeDetail:
    t = await service.get_type(db, code)
    lib = await service.library_for(db, t.id)
    return ContractTypeDetail(
        id=t.id,
        code=t.code,
        title_uz=t.title_uz,
        title_ru=t.title_ru,
        description=t.description,
        form_requirement=t.form_requirement,
        has_ru_template=bool(t.template_ru),
        version=t.version,
        source=t.source,
        questionnaire=t.questionnaire,
        legal_refs=t.legal_refs,
        library=[
            {
                "id": str(x.id),
                "code": x.code,
                "category": x.category,
                "title": x.title,
                "params_schema": x.params_schema,
                "risk_level": x.risk_level,
            }
            for x in lib
        ],
    )


# --- contracts -----------------------------------------------------------------------


@router.post("/contracts", response_model=ContractOut, status_code=status.HTTP_201_CREATED, summary="Yangi loyiha")
async def create_contract(body: ContractCreate, db: DB, user: CurrentUser) -> ContractOut:
    c = await service.create(
        db,
        user=user,
        type_code=body.type_code,
        title=body.title,
        my_role=body.my_role,
        company_id=body.company_id,
        represents=body.represents,
    )
    return contract_out(c)


@router.get("/contracts", response_model=list[ContractOut], summary="Shartnomalarim")
async def list_contracts(
    db: DB,
    user: CurrentUser,
    page: PageParams,
    tab: Literal["active", "pending", "expired", "completed", "disputed"] | None = None,
) -> list[ContractOut]:
    return [contract_out(c) for c in await service.list_for(db, user, tab, page.limit, page.offset)]


@router.post("/contracts/invitations/accept", response_model=ContractOut, summary="Taklifni qabul qilish")
async def accept_invitation(body: AcceptIn, db: DB, user: CurrentUser) -> ContractOut:
    return contract_out(await service.accept_invite(db, user, body.token))


async def _invitation_out(db: DB, party: ContractParty, c: Contract) -> InvitationOut:
    owner = await db.get(User, c.owner_id)
    inviter = (owner.profile.full_name if owner and owner.profile else None) or (
        f"{owner.phone[:6]}***{owner.phone[-2:]}" if owner and owner.phone else None
    )
    v = await db.get(ContractVersion, c.current_version_id) if c.current_version_id else None
    return InvitationOut(
        party_id=party.id,
        role=party.role,
        role_title=service.role_title(party.role),
        invited_at=party.invited_at,
        expires_at=party.invited_at + service.INVITE_TTL if party.invited_at else None,
        contract_id=c.id,
        contract_title=c.title,
        contract_status=c.status,
        type_code=c.contract_type.code if c.contract_type else None,
        total_amount=str(c.total_amount) if c.total_amount is not None else None,
        currency=c.currency,
        inviter_name=inviter,
        current_version=v.number if v else None,
        current_sha256=v.sha256 if v else None,
    )


@router.get(
    "/contracts/invitations",
    response_model=list[InvitationOut],
    summary="Menga kelgan takliflar (telefon raqamim bo'yicha)",
)
async def my_invitations(db: DB, user: CurrentUser) -> list[InvitationOut]:
    return [await _invitation_out(db, p, c) for p, c in await service.list_invitations(db, user)]


@router.get(
    "/contracts/invitations/{party_id}/preview",
    summary="Taklif qilingan shartnoma matnini qo'shilishdan oldin ko'rish",
)
async def invitation_preview(
    party_id: uuid.UUID, db: DB, user: CurrentUser, language: Literal["uz", "ru"] = "uz"
) -> dict[str, Any]:
    party = await service._open_invitation(db, user, party_id)
    c = await db.get(Contract, party.contract_id)
    assert c is not None
    content = await service.preview(db, c, language=language)
    report = await service.validate(db, c)
    # the invitee sees the risky/illegal points *before* joining
    return {
        **content,
        "warnings": [
            {k: f.get(k) for k in ("severity", "message", "law_ref", "fix_suggestion", "clause_index")}
            for f in report["findings"]
        ],
        "risk_counts": report["summary"]["counts"],
    }


@router.post(
    "/contracts/invitations/{party_id}/accept",
    response_model=ContractOut,
    summary="Taklifni qabul qilish (SMS-kodsiz: raqam OTP bilan tasdiqlangan)",
)
async def accept_invitation_by_id(party_id: uuid.UUID, db: DB, user: CurrentUser) -> ContractOut:
    return contract_out(await service.accept_invitation(db, user, party_id))


@router.post("/contracts/invitations/{party_id}/decline", status_code=204, summary="Taklifni rad etish")
async def decline_invitation(party_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    await service.decline_invitation(db, user, party_id)


@router.get("/contracts/{contract_id}", response_model=ContractDetail)
async def get_contract(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> ContractDetail:
    c, _ = await service.load_for(db, contract_id, user)
    return contract_out(c, ContractDetail)


@router.patch("/contracts/{contract_id}/answers", summary="Savolnoma javoblari (+ real vaqt tekshiruvi)")
async def patch_answers(contract_id: uuid.UUID, body: AnswersPatch, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    return await negotiation.update_answers(
        db,
        c,
        user,
        party,
        answers=body.answers,
        merge=body.merge,
        selected_clauses=(
            None if body.selected_clauses is None else [x.model_dump(mode="json") for x in body.selected_clauses]
        ),
    )


@router.get("/contracts/{contract_id}/preview", summary="Shartnoma matni (jonli ko'rinish, versiya yaratmaydi)")
async def preview(
    contract_id: uuid.UUID, db: DB, user: CurrentUser, language: Literal["uz", "ru"] = "uz"
) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    content = await service.preview(db, c, language=language)
    # Same digest the version will get if generated now: the user can see what they will sign.
    digest = sha256_hex(canonical_json({**content, "contract_id": str(c.id)}))
    return {**content, "content_sha256": digest}


class AIAskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post("/contracts/{contract_id}/ai/review", summary="AI tekshiruvi: qoidalar qamramagan xavflar va tavsiyalar")
async def ai_review_contract(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    await get_limiter().hit(f"ai:{user.id}", limit=40, window_s=3600)
    return await service.ai_review(db, c)


@router.post("/contracts/{contract_id}/ai/ask", summary="Shartnoma bo'yicha AI'ga savol")
async def ai_ask_contract(contract_id: uuid.UUID, body: AIAskIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    await get_limiter().hit(f"ai:{user.id}", limit=40, window_s=3600)
    return await service.ai_ask(db, c, body.question)


@router.post(
    "/contracts/{contract_id}/autofix",
    summary="Qonunga zid / xavfli qiymatlarni qoidalar tavsiyasi bo'yicha avtomatik tuzatish",
)
async def autofix_contract(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    service.require_editor(c, user, party)
    return await service.autofix(db, c, user)


@router.post("/contracts/{contract_id}/validate", summary="Qonuniylik tekshiruvi")
async def validate_contract(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    return await service.validate(db, c)


@router.post("/contracts/{contract_id}/generate", summary="DOCX/PDF generatsiya (yangi versiya)")
async def generate(contract_id: uuid.UUID, body: GenerateIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, party = await service.load_for(db, contract_id, user)
    negotiation.check_can_generate(c, user, party)
    v, report = await service.generate(db, c, user, language=body.language)
    await negotiation.after_generate(db, c, user, v.number, v.sha256)
    return {"version": VersionOut.model_validate(v).model_dump(mode="json"), "report": report}


@router.get("/contracts/{contract_id}/versions", response_model=list[VersionOut])
async def versions(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> list[VersionOut]:
    c, _ = await service.load_for(db, contract_id, user)
    rows = await db.scalars(
        select(ContractVersion).where(ContractVersion.contract_id == c.id).order_by(ContractVersion.number.desc())
    )
    return [VersionOut.model_validate(v) for v in rows]


@router.get("/contracts/{contract_id}/versions/{number}/content", summary="Versiya matni (strukturali)")
async def version_content(contract_id: uuid.UUID, number: int, db: DB, user: CurrentUser) -> dict[str, Any]:
    v = await _version(db, contract_id, number, user)
    approvals_ = await approvals.list_for_version(db, v.id)
    return {
        "number": v.number,
        "sha256": v.sha256,
        "content": v.content,
        "approvals": [
            {
                "party_id": str(a.party_id),
                "method": a.method.value,
                "signed_at": a.signed_at.isoformat(),
                "ip": a.ip,
                "device": a.device,
                "sha256": a.sha256,
                # E-IMZO evidence summary (never the raw PKCS#7 / full PINFL)
                "signer": {
                    k: a.proof.get(k)
                    for k in (
                        "signer_name",
                        "signer_pinfl",
                        "signer_tin",
                        "company_tin",
                        "cert_serial",
                        "signing_time",
                        "timestamp_time",
                    )
                }
                if a.method.value == "eimzo"
                else None,
            }
            for a in approvals_
        ],
        "signed_container_available": v.signed_container_file_id is not None,
    }


@router.get("/contracts/{contract_id}/versions/{number}/download", summary="DOCX yoki PDF yuklab olish")
async def download(
    contract_id: uuid.UUID,
    number: int,
    db: DB,
    user: CurrentUser,
    format_: Literal["docx", "pdf"] = Query("docx", alias="format"),
) -> Response:
    v = await _version(db, contract_id, number, user)
    file_id = v.file_id if format_ == "docx" else await service.version_pdf(db, v, user)
    assert file_id is not None
    row = await files.get_file(db, file_id)
    data = await files.read_bytes(row)
    return Response(
        content=data,
        media_type=row.mime,
        headers={
            "Content-Disposition": f'attachment; filename="{row.original_name}"',
            "X-Content-SHA256": v.sha256,
        },
    )


@router.get(
    "/contracts/{contract_id}/versions/{number}/signature.p7s",
    summary="Barcha tomonlarning E-IMZO imzolari (bitta PKCS#7 konteyner)",
)
async def signature_container(contract_id: uuid.UUID, number: int, db: DB, user: CurrentUser) -> Response:
    v = await _version(db, contract_id, number, user)
    if v.signed_container_file_id is None:
        raise NotFound("No E-IMZO signature container for this version", code="no_signature_container")
    row = await files.get_file(db, v.signed_container_file_id)
    return Response(
        content=await files.read_bytes(row),
        media_type="application/pkcs7-signature",
        headers={"Content-Disposition": f'attachment; filename="{row.original_name}"', "X-Content-SHA256": v.sha256},
    )


@router.get(
    "/contracts/{contract_id}/versions/{number}/anchor",
    summary="Blokcheyn isboti: xesh + Merkle yo'li + tranzaksiya (va sizning commitment ochqichingiz)",
)
async def anchor_proof(contract_id: uuid.UUID, number: int, db: DB, user: CurrentUser) -> dict[str, Any]:
    v = await _version(db, contract_id, number, user)
    return await anchoring.proof_package(db, kind=LeafKind.CONTRACT_SIGNED, ref_id=v.id, opening_for=str(user.id))


@router.get("/contracts/{contract_id}/versions/{number}/verify", summary="O'zgartirilmaganini tekshirish (SHA-256)")
async def verify(contract_id: uuid.UUID, number: int, db: DB, user: CurrentUser) -> dict[str, Any]:
    return service.verify_integrity(await _version(db, contract_id, number, user))


@router.post("/contracts/{contract_id}/invite", summary="Ikkinchi tomonni taklif qilish")
async def invite(contract_id: uuid.UUID, body: InviteIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    party, _token = await service.invite(
        db, c, user, phone=body.phone, role=body.role, represents=body.represents, display_name=body.display_name
    )
    # The token is delivered only by SMS; it is never returned to the inviter.
    return {"party_id": str(party.id), "role": party.role.value, "invited_at": party.invited_at}


@router.post("/contracts/{contract_id}/approve/otp", summary="Tasdiqlash uchun SMS-kod so'rash")
async def approve_otp(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, int]:
    c, _ = await service.load_for(db, contract_id, user)
    issued = await approvals.request_otp(db, c, user)
    return {"expires_in": issued.expires_in, "resend_in": issued.resend_in}


@router.get(
    "/contracts/{contract_id}/approve/eimzo",
    summary="E-IMZO: imzolanadigan hujjat (Base64) — EIMZOClient.createPkcs7 ga beriladi",
)
async def approve_eimzo_payload(contract_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    return await approvals.eimzo_payload(db, c, user)


@router.post("/contracts/{contract_id}/approve", summary="Tasdiqlash (OTP / E-IMZO)")
async def approve(contract_id: uuid.UUID, body: ApproveIn, db: DB, user: CurrentUser) -> dict[str, Any]:
    c, _ = await service.load_for(db, contract_id, user)
    return await approvals.approve(
        db, c, user, method=body.method, code=body.code, pkcs7=body.pkcs7, expected_sha256=body.sha256
    )


@router.post("/contracts/{contract_id}/status", response_model=ContractOut, summary="Yakunlash / nizo / bekor qilish")
async def change_status(contract_id: uuid.UUID, body: StatusIn, db: DB, user: CurrentUser) -> ContractOut:
    c, party = await service.load_for(db, contract_id, user)
    if party is None and c.owner_id != user.id:
        service.require_owner(c, user)
    return contract_out(await service.set_status(db, c, user, ContractStatus(body.status), body.reason))


async def _version(db: DB, contract_id: uuid.UUID, number: int, user: CurrentUser) -> ContractVersion:
    c, _ = await service.load_for(db, contract_id, user)
    v = await db.scalar(
        select(ContractVersion).where(ContractVersion.contract_id == c.id, ContractVersion.number == number)
    )
    if v is None:
        raise NotFound("Version not found")
    return v
