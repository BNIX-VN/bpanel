"""Delete revoked MCP and API tokens.

Revoking a token used to keep its row, listed as "Revoked". A revoked token
is now deleted outright, as OPanel does (operator, 2026-09-30); the rows left
from before go the same way. None of them can sign anything in.

Revision ID: 0042_delete_revoked_tokens
Revises: 0041_mail_domains
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0042_delete_revoked_tokens"
down_revision = "0041_mail_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "mcp_tokens" in tables:
        op.execute("DELETE FROM mcp_tokens WHERE revoked_at IS NOT NULL")
    if "api_tokens" in tables:
        op.execute("DELETE FROM api_tokens WHERE is_active = 0 OR revoked_at IS NOT NULL")


def downgrade() -> None:
    # Deleted rows are not coming back.
    pass
