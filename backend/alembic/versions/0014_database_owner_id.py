"""database belongs to user, not website

Revision ID: 0014_database_owner_id
Revises: 0013_website_http_flood
Create Date: 2026-06-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_database_owner_id"
down_revision: Union[str, None] = "0013_website_http_flood"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("database_accounts", sa.Column("owner_id", sa.Integer(), nullable=True))
    # Backfill owner_id from website.owner_id for existing rows
    op.execute(
        "UPDATE database_accounts SET owner_id = ("
        "  SELECT websites.owner_id FROM websites WHERE websites.id = database_accounts.website_id"
        ")"
    )
    op.alter_column("database_accounts", "owner_id", nullable=False)
    op.alter_column("database_accounts", "website_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key("fk_database_accounts_owner_id", "database_accounts", "users", ["owner_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_database_accounts_owner_id", "database_accounts", type_="foreignkey")
    op.alter_column("database_accounts", "website_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("database_accounts", "owner_id")
