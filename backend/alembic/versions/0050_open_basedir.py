"""open_basedir per website and per package, off by default

open_basedir cost a third of every uncached WordPress page (.88, 2026-10-23).
It is now each site's, off unless the site or its package turns it on
(services/php_isolation.py); /home/<user> 0750 keeps customers apart.

Revision ID: 0050_open_basedir
Revises: 0049_wordpress_manager
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0050_open_basedir"
down_revision: Union[str, None] = "0049_wordpress_manager"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table in ("websites", "user_packages"):
        if "open_basedir" not in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("open_basedir", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    for table in ("websites", "user_packages"):
        if "open_basedir" in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column("open_basedir")
