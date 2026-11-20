"""audit_log append-only trigger (PostgreSQL)

Revision ID: 0002_audit_append_only
Revises: 0001_initial
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_audit_append_only"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Spec §10: the audit log must be impossible to modify. The hash chain detects tampering;
    # this trigger prevents it at the database level. (SQLite dev DBs rely on the hash chain only.)
    # One statement per execute(): asyncpg runs each as a prepared statement.
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
