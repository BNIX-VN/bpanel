"""Redis per account: a memory limit on packages and custom accounts, and
each account's own switch

Redis per account addon (operator, 2026-10-27, DirectAdmin-style): an account
may run a Redis of its own. redis_memory_mb is how much it may hold (64 MB
unless the administrator changes it; 0 = not allowed), on the package and on
an account without one; redis_enabled is the customer's switch, off.

Revision ID: 0053_redis_per_account
Revises: 0052_website_proxy_mode
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0053_redis_per_account"
down_revision: Union[str, None] = "0052_website_proxy_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "redis_memory_mb" not in _columns("user_packages"):
        with op.batch_alter_table("user_packages") as batch:
            batch.add_column(sa.Column("redis_memory_mb", sa.Integer(), nullable=False, server_default=sa.text("64")))
    columns = _columns("users")
    with op.batch_alter_table("users") as batch:
        if "redis_memory_mb" not in columns:
            batch.add_column(sa.Column("redis_memory_mb", sa.Integer(), nullable=False, server_default=sa.text("64")))
        if "redis_enabled" not in columns:
            batch.add_column(sa.Column("redis_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if "redis_memory_mb" in _columns("user_packages"):
        with op.batch_alter_table("user_packages") as batch:
            batch.drop_column("redis_memory_mb")
    columns = _columns("users")
    with op.batch_alter_table("users") as batch:
        for name in ("redis_memory_mb", "redis_enabled"):
            if name in columns:
                batch.drop_column(name)
