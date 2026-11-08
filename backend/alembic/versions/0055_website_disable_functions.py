"""The PHP functions a website's pool disables

NULL is the default list (services/php_functions.py); a string is the site's
own comma list, "" when nothing is disabled (operator, 2026-11-08).

Revision ID: 0055_website_disable_functions
Revises: 0054_cloudflare_credential_owner
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0055_website_disable_functions"
down_revision: Union[str, None] = "0054_cloudflare_credential_owner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "disable_functions" in _columns("websites"):
        return
    with op.batch_alter_table("websites") as batch:
        batch.add_column(sa.Column("disable_functions", sa.Text(), nullable=True))


def downgrade() -> None:
    if "disable_functions" not in _columns("websites"):
        return
    with op.batch_alter_table("websites") as batch:
        batch.drop_column("disable_functions")
