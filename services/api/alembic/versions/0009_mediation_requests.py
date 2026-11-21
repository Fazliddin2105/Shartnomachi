"""mediation requests: applications to a mediator drafted by the user (O'RQ-482)

Revision ID: 0009_mediation_requests
Revises: 0008_archive_documents
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_mediation_requests"
down_revision: str | None = "0008_archive_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mediation_requests",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("form", sa.Text(), nullable=False),
        sa.Column("ai_draft", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_mediation_requests_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contracts.id"],
            name=op.f("fk_mediation_requests_contract_id_contracts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mediation_requests")),
    )
    with op.batch_alter_table("mediation_requests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_mediation_requests_owner_id"), ["owner_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_mediation_requests_contract_id"), ["contract_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_mediation_requests_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("mediation_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mediation_requests_created_at"))
        batch_op.drop_index(batch_op.f("ix_mediation_requests_contract_id"))
        batch_op.drop_index(batch_op.f("ix_mediation_requests_owner_id"))
    op.drop_table("mediation_requests")
