"""Scope Cloudflare credentials per owner

A Cloudflare API token is one account's secret, but cloudflare_credentials had
no owner column and a single global-unique index on zone, so any account whose
website was a suffix match of a saved zone could spend another tenant's token
to issue and attach that tenant's wildcard certificate. Add owner_id (a lookup
for a website uses the website owner's row only) and move uniqueness from zone
alone to (owner_id, zone). Existing rows get owner_id NULL: they match no owner
and must be re-saved, which is the point - nobody knew whose they were.

Revision ID: 0054_cloudflare_credential_owner
Revises: 0053_redis_per_account
Create Date: 2026-10-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0054_cloudflare_credential_owner"
down_revision: Union[str, None] = "0053_redis_per_account"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "owner_id" in _columns("cloudflare_credentials"):
        return
    # Drop the old UNIQUE index on zone first; uniqueness becomes (owner_id, zone).
    if "ix_cloudflare_credentials_zone" in _indexes("cloudflare_credentials"):
        op.drop_index("ix_cloudflare_credentials_zone", table_name="cloudflare_credentials")
    with op.batch_alter_table("cloudflare_credentials", recreate="always") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_cloudflare_credentials_owner", "users", ["owner_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_cloudflare_credentials_zone", ["zone"], unique=False)
        batch.create_index("ix_cloudflare_credentials_owner_id", ["owner_id"], unique=False)
        batch.create_unique_constraint("uq_cloudflare_owner_zone", ["owner_id", "zone"])


def downgrade() -> None:
    if "owner_id" not in _columns("cloudflare_credentials"):
        return
    with op.batch_alter_table("cloudflare_credentials", recreate="always") as batch:
        batch.drop_constraint("uq_cloudflare_owner_zone", type_="unique")
        batch.drop_index("ix_cloudflare_credentials_owner_id")
        batch.drop_index("ix_cloudflare_credentials_zone")
        batch.drop_constraint("fk_cloudflare_credentials_owner", type_="foreignkey")
        batch.drop_column("owner_id")
        batch.create_index("ix_cloudflare_credentials_zone", ["zone"], unique=True)
