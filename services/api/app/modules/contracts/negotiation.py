"""Two-party negotiation on top of the contract draft.

Flow
  1. The initiator fills in their own data and the terms, invites the other side.
  2. The other side joins and fills in *their own* data (``party_b.*`` for B). Each side may edit only its
     own fields; shared terms can be edited by both, and every change of the terms voids previous consents.
  3. A side that disagrees files an objection (comment + optional proposed values). The other side accepts
     (values are applied) or rejects it; the author may withdraw it.
  4. Each side gives consent to the exact terms (hash of answers + clauses). When every joined signing party
     has consented to the same hash, the common contract is generated automatically and offered to both.
  5. Terms contrary to law (red rule findings) can neither be consented to nor generated.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import canonical_json, sha256_hex
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.timeutils import utcnow
from app.modules.audit import service as audit
from app.modules.contracts import service
from app.modules.contracts.models import (
    Contract,
    ContractEvent,
    ContractObjection,
    ContractParty,
    ContractStatus,
    ContractVersion,
    ObjectionStatus,
    PartyRole,
)
from app.modules.notifications.channels import Message
from app.modules.users.models import User

SIGNING = (PartyRole.A, PartyRole.B)
SIDE_TITLES = {"A": "A tomon", "B": "B tomon"}


# --- sides & fields ---------------------------------------------------------------------------------


def other_side(side: str) -> str:
    return "B" if side == "A" else "A"


def party_for(c: Contract, side: str) -> ContractParty | None:
    return next((p for p in c.parties if p.role.value == side), None)


def both_joined(c: Contract) -> bool:
    return all((p := party_for(c, s)) is not None and p.user_id is not None for s in ("A", "B"))


def my_side(c: Contract, user: User, party: ContractParty | None) -> str | None:
    if party is not None:
        if party.role in SIGNING:
            return party.role.value
        if party.role == PartyRole.LAWYER and party.represents in SIGNING:
            return party.represents.value  # type: ignore[union-attr]
        return None
    if c.owner_id == user.id or c.company_id is not None:
        owner_party = next((p for p in c.parties if p.user_id == c.owner_id), None)
        if owner_party is not None:
            return my_side(c, user, owner_party)
    return None


def require_participant(c: Contract, user: User, party: ContractParty | None) -> str:
    side = my_side(c, user, party)
    if side is None:
        raise Forbidden("Only a party of the contract can do this", code="not_participant")
    return side


def _fields(c: Contract) -> dict[str, dict[str, Any]]:
    ctype = c.contract_type
    return {f["key"]: f for f in service._fields((ctype.questionnaire if ctype else {}) or {})}


def field_side(fields: dict[str, dict[str, Any]], key: str) -> str | None:
    """A / B for a party's own data, None for shared terms. A field may override it with "side"."""
    root = key.split(".")[0]
    f = fields.get(key) or fields.get(root)
    if f is not None and f.get("side") in ("A", "B", "shared"):
        return None if f["side"] == "shared" else f["side"]
    if root == "party_a":
        return "A"
    if root == "party_b":
        return "B"
    return None


def key_known(fields: dict[str, dict[str, Any]], key: str) -> bool:
    if key in fields:
        return True
    root = key.split(".")[0]
    return fields.get(root, {}).get("type") == "party"


def leaf_paths(d: dict[str, Any], prefix: str = "") -> list[str]:
    out: list[str] = []
    for k, v in d.items():
        path = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            out += leaf_paths(v, path + ".")
        else:
            out.append(path)
    return out


def terms_hash(c: Contract) -> str:
    return sha256_hex(canonical_json({"answers": c.answers or {}, "clauses": c.selected_clauses or []}))


def _agreed(p: ContractParty | None, h: str) -> bool:
    return p is not None and p.agreed_terms_sha256 == h


def _reset_agreements(c: Contract) -> bool:
    had = any(p.agreed_terms_sha256 for p in c.parties)
    for p in c.parties:
        p.agreed_terms_sha256, p.agreed_at = None, None
    return had


async def _notify_others(db: AsyncSession, c: Contract, actor: User, *, event: str, title: str, body: str) -> None:
    await service.notify_parties(db, c, except_user=actor.id, event=event, title=title, body=body)


# --- answers with ownership ----------------------------------------------------------------------------


async def update_answers(
    db: AsyncSession,
    c: Contract,
    user: User,
    party: ContractParty | None,
    *,
    answers: dict[str, Any],
    merge: bool,
    selected_clauses: list[dict[str, Any]] | None,
    enforce_sides: bool = True,
) -> dict[str, Any]:
    side = require_participant(c, user, party)
    if c.status not in service.EDITABLE:
        raise Conflict("Contract can no longer be edited", code="contract_locked")
    other = party_for(c, other_side(side))
    other_joined = other is not None and other.user_id is not None
    expanded = service.expand_dotted(answers)
    paths = leaf_paths(expanded)
    if enforce_sides and other_joined:
        if not merge:
            raise ValidationFailed("Both parties are in the contract: send changes only", code="merge_required")
        fields = _fields(c)
        locked = sorted({p for p in paths if field_side(fields, p) == other_side(side)})
        if locked:
            raise Forbidden(
                "These fields belong to the other party", code="field_not_yours", details={"fields": locked}
            )
    before = terms_hash(c)
    report = await service.patch_answers(db, c, user, answers=expanded, merge=merge, selected_clauses=selected_clauses)
    changed = terms_hash(c) != before
    report["terms_changed"] = changed
    report["agreements_reset"] = False
    if changed:
        report["agreements_reset"] = _reset_agreements(c)
        await service.log_event(
            db,
            c,
            actor_id=user.id,
            side=side,
            kind="terms_changed",
            payload={"fields": paths[:100]},
            merge_window_s=600,
        )
        if other_joined and report["agreements_reset"]:
            await _notify_others(
                db,
                c,
                user,
                event="contract.terms_changed",
                title="Shartlar o'zgartirildi",
                body=f'"{c.title}": {SIDE_TITLES[side]} shartlarni o\'zgartirdi — '
                "ko'rib chiqib, qayta rozilik bering.",
            )
    report["terms_sha256"] = terms_hash(c)
    return report


# --- consent -------------------------------------------------------------------------------------------


async def agree(db: AsyncSession, c: Contract, user: User, party: ContractParty | None) -> dict[str, Any]:
    side = require_participant(c, user, party)
    me = party_for(c, side)
    if me is None or (me.user_id != user.id and not (party is not None and party.role == PartyRole.LAWYER)):
        raise Forbidden("Only the party itself (or its lawyer) can consent", code="not_signing_party")
    if c.status != ContractStatus.DRAFT:
        raise Conflict("Terms are not open for consent", code="not_draft")
    report = await service.validate(db, c)
    if report["summary"]["blocking"]:
        raise ValidationFailed(
            "Contract contains clauses contrary to law",
            code="illegal_clauses",
            details=[f for f in report["findings"] if f["severity"] == "red"],
        )
    if not report["ready"]:
        raise ValidationFailed(
            "Questionnaire is incomplete",
            code="answers_incomplete",
            details={"missing": report["missing_fields"], "errors": report["field_errors"]},
        )
    h = terms_hash(c)
    me.agreed_terms_sha256, me.agreed_at = h, utcnow()
    # agreeing means the side's own open objections are settled
    for o in await db.scalars(
        select(ContractObjection).where(
            ContractObjection.contract_id == c.id,
            ContractObjection.side == side,
            ContractObjection.status == ObjectionStatus.OPEN,
        )
    ):
        o.status, o.resolved_by, o.resolved_at = ObjectionStatus.WITHDRAWN, user.id, utcnow()
    await service.log_event(db, c, actor_id=user.id, side=side, kind="agreed", payload={"terms_sha256": h})
    await audit.record(
        db, action="contract.agree", entity="contract", entity_id=c.id, actor_id=user.id, meta={"terms_sha256": h}
    )
    waiting = [s for s in ("A", "B") if not _agreed(party_for(c, s), h)]
    generated = None
    if both_joined(c) and not waiting:
        v, _ = await service.generate(db, c, user, language=c.language or "uz")
        generated = {"number": v.number, "sha256": v.sha256}
        await service.log_event(
            db, c, actor_id=user.id, side=side, kind="generated", payload={"version": v.number, "sha256": v.sha256}
        )
        await service.notify_parties(
            db,
            c,
            except_user=None,
            event="contract.ready_to_sign",
            title="Umumiy shartnoma tayyor",
            body=f'"{c.title}": ikkala tomon shartlarga rozi bo\'ldi. Yakuniy hujjat (v{v.number}) tayyor — '
            "ko'rib chiqing va imzolang.",
        )
    elif both_joined(c):
        await _notify_others(
            db,
            c,
            user,
            event="contract.agreed_by_party",
            title="Shartlarga rozilik bildirildi",
            body=f'"{c.title}": {SIDE_TITLES[side]} shartlarga rozi. Sizning roziligingiz kutilmoqda.',
        )
    return {"agreed": True, "terms_sha256": h, "waiting_for": waiting if both_joined(c) else [], "generated": generated}


def check_can_generate(c: Contract, user: User, party: ContractParty | None) -> None:
    """Manual generation: solo drafts by the initiator/lawyer; with both sides in, only after both consented."""
    if both_joined(c):
        require_participant(c, user, party)
        h = terms_hash(c)
        waiting = [s for s in ("A", "B") if not _agreed(party_for(c, s), h)]
        if waiting:
            raise Conflict(
                "Both parties must consent to the same terms first",
                code="agreement_required",
                details={"waiting_for": waiting},
            )
        return
    service.require_editor(c, user, party)


async def after_generate(db: AsyncSession, c: Contract, user: User, number: int, sha: str) -> None:
    await service.log_event(
        db, c, actor_id=user.id, side=None, kind="generated", payload={"version": number, "sha256": sha}
    )
    await _notify_others(
        db,
        c,
        user,
        event="contract.ready_to_sign",
        title="Shartnoma imzolashga tayyor",
        body=f'"{c.title}": yakuniy hujjat (v{number}) tayyor — ko\'rib chiqing va imzolang.',
    )


# --- objections ------------------------------------------------------------------------------------------


def objection_out(o: ContractObjection) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "side": o.side,
        "author_id": str(o.author_id),
        "comment": o.comment,
        "fields": o.fields or [],
        "proposed": o.proposed or {},
        "status": o.status.value,
        "resolution_note": o.resolution_note,
        "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
        "created_at": o.created_at.isoformat(),
    }


async def object_to(
    db: AsyncSession,
    c: Contract,
    user: User,
    party: ContractParty | None,
    *,
    comment: str,
    fields: list[str],
    proposed: dict[str, Any],
) -> dict[str, Any]:
    side = require_participant(c, user, party)
    if c.status not in service.EDITABLE:
        raise Conflict(
            "Only drafts and contracts awaiting signature can be objected to; use the dispute status for active ones",
            code="contract_locked",
        )
    known = _fields(c)
    proposed = {k: v for k, v in proposed.items()}
    unknown = sorted(k for k in [*fields, *proposed] if not key_known(known, k))
    if unknown:
        raise ValidationFailed("Unknown questionnaire fields", code="unknown_fields", details={"fields": unknown})
    o = ContractObjection(
        contract_id=c.id,
        party_id=party.id if party else None,
        author_id=user.id,
        side=side,
        comment=comment.strip(),
        fields=sorted(set(fields) | set(proposed)),
        proposed=proposed,
    )
    db.add(o)
    me = party_for(c, side)
    if me is not None:
        me.agreed_terms_sha256, me.agreed_at = None, None
    if c.status == ContractStatus.PENDING_APPROVAL:
        # The generated version is no longer agreed: back to negotiation, a new version will follow.
        c.status = ContractStatus.DRAFT
        for p in c.parties:
            p.confirmed_at = None
    await db.flush()
    await service.log_event(
        db,
        c,
        actor_id=user.id,
        side=side,
        kind="objection",
        payload={"objection_id": str(o.id), "comment": o.comment[:500], "fields": o.fields},
    )
    await audit.record(
        db,
        action="contract.objection",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"objection_id": str(o.id), "fields": o.fields},
    )
    await _notify_others(
        db,
        c,
        user,
        event="contract.objection",
        title="Norozilik bildirildi",
        body=f'"{c.title}": {SIDE_TITLES[side]} — {o.comment[:160]}',
    )
    return objection_out(o)


async def list_objections(db: AsyncSession, c: Contract) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(ContractObjection).where(ContractObjection.contract_id == c.id).order_by(ContractObjection.created_at)
    )
    return [objection_out(o) for o in rows]


async def resolve_objection(
    db: AsyncSession,
    c: Contract,
    user: User,
    party: ContractParty | None,
    objection_id: uuid.UUID,
    *,
    action: str,
    note: str | None,
) -> dict[str, Any]:
    side = require_participant(c, user, party)
    o = await db.get(ContractObjection, objection_id)
    if o is None or o.contract_id != c.id:
        raise NotFound("Objection not found")
    if o.status != ObjectionStatus.OPEN:
        raise Conflict("Objection is already resolved", code="objection_closed")
    if action == "withdraw":
        if o.side != side:
            raise Forbidden("Only the author can withdraw", code="not_author")
        o.status = ObjectionStatus.WITHDRAWN
    elif action in ("accept", "reject"):
        if o.side == side:
            raise Forbidden("The other party decides on an objection", code="own_objection")
        if action == "accept":
            if c.status not in service.EDITABLE:
                raise Conflict("Contract can no longer be edited", code="contract_locked")
            if o.proposed:
                await update_answers(
                    db, c, user, party, answers=dict(o.proposed), merge=True, selected_clauses=None, enforce_sides=False
                )
            o.status = ObjectionStatus.ACCEPTED
        else:
            o.status = ObjectionStatus.REJECTED
    else:
        raise ValidationFailed("Unknown action", code="action_invalid")
    o.resolved_by, o.resolved_at, o.resolution_note = user.id, utcnow(), (note or "").strip() or None
    await service.log_event(
        db,
        c,
        actor_id=user.id,
        side=side,
        kind=f"objection_{o.status.value}",
        payload={"objection_id": str(o.id), "note": (o.resolution_note or "")[:300]},
    )
    if action != "withdraw":
        verdict = "qabul qilindi — shartlar yangilandi" if action == "accept" else "rad etildi"
        await service._notify(
            db,
            o.author_id,
            Message(
                type=f"contract.objection_{o.status.value}",
                title="Norozilikka javob",
                body=f'"{c.title}": norozilik {verdict}.'
                + (f" Izoh: {o.resolution_note}" if o.resolution_note else ""),
                payload={"contract_id": str(c.id), "objection_id": str(o.id)},
            ),
        )
    return objection_out(o)


# --- state for the UI -------------------------------------------------------------------------------------

_NEXT_TEXT = {
    "invite_other_party": "Shartlarni to'ldiring va ikkinchi tomonni taklif qiling",
    "fill_your_data": "O'zingizga tegishli ma'lumotlarni to'ldiring",
    "fix_illegal_terms": "Qonunga zid shartlarni tuzating — aks holda shartnoma tuzilmaydi",
    "wait_other_party_join": "Ikkinchi tomon taklifni qabul qilishi kutilmoqda",
    "wait_other_party_data": "Ikkinchi tomon o'z ma'lumotlarini kiritishi kutilmoqda",
    "resolve_objections": "Ikkinchi tomonning norozilik/taklifiga javob bering",
    "wait_objection_answer": "Norozilingizga javob kutilmoqda",
    "agree": "Shartlarni ko'rib chiqing va rozilik bildiring",
    "wait_other_party_agreement": "Ikkinchi tomonning roziligi kutilmoqda",
    "generate": "Shartnomani yarating (yoki ikkinchi tomonni taklif qiling)",
    "sign": "Yakuniy hujjatni SMS-kod bilan imzolang",
    "wait_signatures": "Ikkinchi tomonning imzosi kutilmoqda",
    "active": "Shartnoma kuchda — arxivingizda saqlangan",
    "completed": "Shartnoma yakunlangan",
    "disputed": "Shartnoma bo'yicha nizo ochilgan",
    "expired": "Shartnoma muddati tugagan",
    "cancelled": "Shartnoma bekor qilingan",
}


async def state(db: AsyncSession, c: Contract, user: User, party: ContractParty | None) -> dict[str, Any]:
    side = my_side(c, user, party)
    report = await service.validate(db, c)
    h = terms_hash(c)
    fields = _fields(c)
    objections = await list_objections(db, c)
    open_obj = [o for o in objections if o["status"] == "open"]
    other = other_side(side) if side else None
    other_party = party_for(c, other) if other else None
    other_joined = other_party is not None and other_party.user_id is not None

    missing_by_side: dict[str, list[str]] = {"A": [], "B": [], "shared": []}
    for key in report["missing_fields"]:
        s = field_side(fields, key)
        missing_by_side[s or "shared"].append(key)

    def editable(key: str) -> bool:
        if side is None or c.status not in service.EDITABLE:
            return False
        s = field_side(fields, key)
        return s in (None, side) or not other_joined

    if c.status != ContractStatus.DRAFT and c.status != ContractStatus.PENDING_APPROVAL:
        nxt = c.status.value
    elif c.status == ContractStatus.PENDING_APPROVAL:
        me = party_for(c, side) if side else None
        nxt = "wait_signatures" if me is not None and me.confirmed_at else "sign"
    elif not other_joined:
        if side and missing_by_side[side] + missing_by_side["shared"]:
            nxt = "fill_your_data"
        elif report["summary"]["blocking"]:
            nxt = "fix_illegal_terms"
        elif other_party is not None and other_party.invite_token_hash:
            nxt = "wait_other_party_join"
        else:
            nxt = "invite_other_party" if c.owner_id == user.id else "generate"
    elif any(o["side"] == other for o in open_obj):
        nxt = "resolve_objections"
    elif side and missing_by_side[side]:
        nxt = "fill_your_data"
    elif report["summary"]["blocking"]:
        nxt = "fix_illegal_terms"
    elif other and missing_by_side[other]:
        nxt = "wait_other_party_data"
    elif any(o["side"] == side for o in open_obj):
        nxt = "wait_objection_answer"
    elif side and not _agreed(party_for(c, side), h):
        nxt = "agree"
    else:
        nxt = "wait_other_party_agreement"

    return {
        "contract_id": str(c.id),
        "status": c.status.value,
        "my_side": side,
        "terms_sha256": h,
        "both_joined": both_joined(c),
        "parties": [
            {
                "role": p.role.value,
                "side": p.represents.value if p.represents else p.role.value,
                "joined": p.user_id is not None,
                "invited": p.invite_token_hash is not None,
                "is_me": p.user_id == user.id,
                "agreed": _agreed(p, h),
                "agreed_at": p.agreed_at.isoformat() if p.agreed_at and _agreed(p, h) else None,
                "signed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
            }
            for p in c.parties
        ],
        "fields": [{"key": k, "side": field_side(fields, k) or "shared", "editable": editable(k)} for k in fields],
        "missing_by_side": missing_by_side,
        "objections_open": open_obj,
        "validation": report,
        "next_action": nxt,
        "next_action_text": _NEXT_TEXT.get(nxt, ""),
    }


# --- timeline ---------------------------------------------------------------------------------------------

_EVENT_TEXT = {
    "created": "Shartnoma qoralamasi yaratildi",
    "invited": "Ikkinchi tomon taklif qilindi",
    "invite_revoked": "Taklif bekor qilindi",
    "joined": "shartnomaga qo'shildi",
    "terms_changed": "shartlarni o'zgartirdi",
    "objection": "norozilik bildirdi",
    "objection_accepted": "norozilikni qabul qildi",
    "objection_rejected": "norozilikni rad etdi",
    "objection_withdrawn": "norozilikni qaytarib oldi",
    "agreed": "shartlarga rozi bo'ldi",
    "generated": "Yakuniy hujjat yaratildi",
    "signed": "imzoladi",
    "activated": "Shartnoma kuchga kirdi va arxivga saqlandi",
    "cancelled": "Shartnoma bekor qilindi",
    "renamed": "Shartnoma nomi o'zgartirildi",
    "duplicated_from": "Boshqa shartnoma asosida yaratildi",
}


async def timeline(db: AsyncSession, c: Contract) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(ContractEvent).where(ContractEvent.contract_id == c.id).order_by(ContractEvent.created_at)
    )
    out = []
    for e in rows:
        text = _EVENT_TEXT.get(e.kind, e.kind)
        if e.side and text and text[0].islower():
            text = f"{SIDE_TITLES.get(e.side, e.side)} {text}"
        if e.kind == "generated" and (e.payload or {}).get("version"):
            text += f" (v{e.payload['version']})"
        out.append(
            {"kind": e.kind, "side": e.side, "text": text, "payload": e.payload or {}, "at": e.created_at.isoformat()}
        )
    return out


# --- housekeeping: delete / cancel / rename / revoke / duplicate ---------------------------------------


async def delete_or_cancel(db: AsyncSession, c: Contract, user: User) -> dict[str, Any]:
    service.require_owner(c, user)
    has_versions = await db.scalar(select(ContractVersion.id).where(ContractVersion.contract_id == c.id).limit(1))
    if c.status == ContractStatus.DRAFT and not has_versions:
        await db.execute(delete(ContractEvent).where(ContractEvent.contract_id == c.id))
        await db.execute(delete(ContractObjection).where(ContractObjection.contract_id == c.id))
        await audit.record(db, action="contract.delete", entity="contract", entity_id=c.id, actor_id=user.id)
        others = [p.user_id for p in c.parties if p.user_id and p.user_id != user.id]
        title = c.title
        await db.delete(c)
        await db.flush()
        for uid in others:
            await service._notify(
                db,
                uid,
                Message(
                    type="contract.deleted", title="Qoralama o'chirildi", body=f'"{title}" qoralamasi o\'chirildi.'
                ),
            )
        return {"deleted": True, "status": None}
    if c.status in service.EDITABLE:
        c.status = ContractStatus.CANCELLED
        await service.log_event(db, c, actor_id=user.id, side=None, kind="cancelled")
        await audit.record(db, action="contract.cancel", entity="contract", entity_id=c.id, actor_id=user.id)
        await _notify_others(
            db, c, user, event="contract.cancelled", title="Shartnoma bekor qilindi", body=f'"{c.title}" bekor qilindi.'
        )
        return {"deleted": False, "status": "cancelled"}
    if c.status == ContractStatus.CANCELLED:
        raise Conflict("A cancelled contract with versions is kept as evidence", code="contract_kept")
    raise Conflict("A signed contract cannot be deleted; complete it or open a dispute", code="contract_signed")


async def rename(db: AsyncSession, c: Contract, user: User, title: str) -> Contract:
    service.require_owner(c, user)
    old = c.title
    c.title = title.strip()[:255]
    await service.log_event(db, c, actor_id=user.id, side=None, kind="renamed", payload={"from": old, "to": c.title})
    return c


async def revoke_invitation(db: AsyncSession, c: Contract, user: User, party_id: uuid.UUID) -> None:
    service.require_owner(c, user)
    p = next((x for x in c.parties if x.id == party_id), None)
    if p is None or p.user_id is not None or p.invite_token_hash is None:
        raise NotFound("No pending invitation for this party", code="invite_invalid")
    p.invite_token_hash = p.invite_phone_hash = p.invite_phone = None
    p.invited_at = None
    await service.log_event(db, c, actor_id=user.id, side=None, kind="invite_revoked", payload={"role": p.role.value})
    await audit.record(
        db,
        action="contract.invite_revoked",
        entity="contract",
        entity_id=c.id,
        actor_id=user.id,
        meta={"party_id": str(p.id)},
    )


async def duplicate(db: AsyncSession, c: Contract, user: User, party: ContractParty | None) -> Contract:
    """«Shu asosida yangi shartnoma»: same type and terms; the other side's personal data is not copied."""
    side = require_participant(c, user, party)
    if c.contract_type is None:
        raise ValidationFailed("Contract has no type", code="type_missing")
    fields = _fields(c)
    other = other_side(side)
    answers = {k: v for k, v in (c.answers or {}).items() if field_side(fields, k) != other}
    new = await service.create(
        db,
        user=user,
        type_code=c.contract_type.code,
        title=f"{c.title} (yangi)"[:255],
        my_role=PartyRole(side),
        company_id=c.company_id if c.owner_id == user.id else None,
        represents=None,
    )
    if answers:
        await service.patch_answers(db, new, user, answers=answers, merge=False, selected_clauses=None)
    new.selected_clauses = list(c.selected_clauses or [])
    await service.log_event(
        db, new, actor_id=user.id, side=side, kind="duplicated_from", payload={"source_contract_id": str(c.id)}
    )
    return new
