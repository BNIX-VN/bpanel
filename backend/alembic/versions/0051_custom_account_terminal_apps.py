"""an account on a custom package has its own application limit

With no package an account could never run an application (the limit was
the package's only) and had no terminal switch the panel showed. The
terminal flag was already the account's; the application limit now is too
(operator, 2026-10-24).

Revision ID: 0051_custom_account_terminal_apps
Revises: 0050_open_basedir
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0051_custom_account_terminal_apps"
down_revision: Union[str, None] = "0050_open_basedir"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "node_apps_limit" not in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("node_apps_limit", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if "node_apps_limit" in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("node_apps_limit")
