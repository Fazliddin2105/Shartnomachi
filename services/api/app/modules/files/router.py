from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import Response

from app.api.deps import DB, CurrentUser
from app.core.errors import NotFound
from app.core.rbac import Perm, has_perm
from app.modules.files import service

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Fayl yuklash (shifrlangan saqlash)")
async def upload(db: DB, user: CurrentUser, file: UploadFile = File(...)) -> dict[str, Any]:
    row = await service.save_bytes(
        db,
        data=await file.read(),
        filename=file.filename or "file",
        declared_mime=file.content_type,
        owner_id=user.id,
        purpose="upload",
    )
    return {"id": str(row.id), "mime": row.mime, "size": row.size, "sha256": row.sha256}


@router.get("/{file_id}", summary="Faylni yuklab olish (faqat egasi)")
async def download(file_id: uuid.UUID, db: DB, user: CurrentUser) -> Response:
    row = await service.get_file(db, file_id)
    # Public samples (blank contract templates) are readable by everyone authenticated.
    if row.owner_id != user.id and row.purpose != "sample" and not has_perm(user.role, Perm.USERS_ADMIN):
        raise NotFound("File not found")
    data = await service.read_bytes(row)
    return Response(
        content=data,
        media_type=row.mime,
        headers={"Content-Disposition": f'attachment; filename="{row.original_name}"', "X-Content-SHA256": row.sha256},
    )
