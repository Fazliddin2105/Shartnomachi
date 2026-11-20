from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import DB, PageParams, require
from app.core.rbac import Perm
from app.modules.anchoring import service
from app.modules.anchoring.models import AnchorBatch, BatchStatus
from app.modules.users.models import User

router = APIRouter(tags=["blockchain"])


class VerifyIn(BaseModel):
    root: str = Field(pattern=r"^[0-9a-f]{64}$", description="Merkle ildizi (hex)")
    proof: list[dict[str, str]] = Field(description='[{"side": "L"|"R", "hash": "<hex>"}]')
    payload: dict[str, Any] | None = Field(default=None, description="Barg mazmuni (isbot paketidagi leaf.payload)")
    leaf_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    merkle_root: str
    leaf_count: int
    status: BatchStatus
    network: str
    chain_id: int | None
    tx_hash: str | None
    block_number: int | None
    block_timestamp: datetime | None
    attempts: int
    last_error: str | None
    created_at: datetime


@router.post("/anchors/verify", summary="Ochiq tekshiruv: hujjat blokcheynda qayd etilganmi (sud, kontragent)")
async def verify(body: VerifyIn) -> dict[str, Any]:
    return await service.verify_package(
        proof=body.proof, root=body.root, payload=body.payload, leaf_hash_hex=body.leaf_hash
    )


@router.get("/admin/anchors", response_model=list[BatchOut], summary="Blokcheyn partiyalari holati")
async def list_batches(
    db: DB, page: PageParams, _: Annotated[User, Depends(require(Perm.AUDIT_READ))], status_: BatchStatus | None = None
) -> list[BatchOut]:
    stmt = select(AnchorBatch).order_by(AnchorBatch.created_at.desc()).limit(page.limit).offset(page.offset)
    if status_:
        stmt = stmt.where(AnchorBatch.status == status_)
    return [BatchOut.model_validate(b) for b in await db.scalars(stmt)]
