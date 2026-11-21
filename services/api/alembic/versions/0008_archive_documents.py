"""archive documents: payment receipts / addenda filed by the user in the personal archive

Revision ID: 0008_archive_documents
Revises: 0007_negotiation_archive
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_archive_documents"
down_revision: str | None = "0007_negotiation_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "archive_documents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("archive_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_archive_documents_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["archive_id"],
            ["archived_contracts.id"],
            name=op.f("fk_archive_documents_archive_id_archived_contracts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_archive_documents_file_id_files"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_archive_documents")),
    )
    with op.batch_alter_table("archive_documents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_archive_documents_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_archive_documents_archive_id"), ["archive_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_archive_documents_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("archive_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_archive_documents_created_at"))
        batch_op.drop_index(batch_op.f("ix_archive_documents_archive_id"))
        batch_op.drop_index(batch_op.f("ix_archive_documents_user_id"))
    op.drop_table("archive_documents")
