"""drop the reseller share columns 1.2.0 stopped reading

0043 gave a reseller's share five totals. Since 0044 (BPanel 1.2.0) a share is
customers and disk only; the website, mail account and application totals
stayed in the table, unread. They go now, values and all - nothing has looked
at them since 1.2.0, and keeping them only invites code to start reading them
again.

pool_database_limit goes too where it exists: a draft of 0044 added it, and
the servers that ran that draft before its release (test servers) kept it
when the released 0044 stopped adding it.

ALTER TABLE ... DROP COLUMN (SQLite 3.35+; Ubuntu 22.04 ships 3.37) rather
than a batch copy of the users table, which every other table points at.

Revision ID: 0046_drop_unused_pool_columns
Revises: 0045_resource_limits
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0046_drop_unused_pool_columns"
down_revision = "0045_resource_limits"
branch_labels = None
depends_on = None

UNUSED = ("pool_website_limit", "pool_mail_accounts_limit", "pool_app_limit")
# Never in a released 0044, so a downgrade does not bring it back.
DRAFT_ONLY = ("pool_database_limit",)


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}


def upgrade() -> None:
    present = _columns()
    for name in UNUSED + DRAFT_ONLY:
        if name in present:
            op.drop_column("users", name)


def downgrade() -> None:
    present = _columns()
    for name in UNUSED:
        if name not in present:
            op.add_column("users", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
