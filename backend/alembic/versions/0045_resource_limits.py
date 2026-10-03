"""resource limits: CPU, memory, processes and disk I/O per account

The Resource limits addon (2026-10-04, ported from OPanel) puts every
hosting account in a systemd slice of its own and these are its limits;
0 = unlimited, which is what every existing account and package starts with.
group_* are a reseller's caps on its whole group - its own account and all
its customers together.

Revision ID: 0045_resource_limits
Revises: 0044_database_limit_oversell
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0045_resource_limits"
down_revision = "0044_database_limit_oversell"
branch_labels = None
depends_on = None

LIMITS = ("cpu_percent", "memory_mb", "process_limit", "io_read_mbps", "io_write_mbps")
USER_COLUMNS = LIMITS + tuple(f"group_{name}" for name in LIMITS)


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    for table, columns in (("users", USER_COLUMNS), ("user_packages", LIMITS)):
        existing = _columns(table)
        missing = [name for name in columns if name not in existing]
        if missing:
            with op.batch_alter_table(table) as batch:
                for name in missing:
                    batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    for table, columns in (("users", USER_COLUMNS), ("user_packages", LIMITS)):
        existing = _columns(table)
        with op.batch_alter_table(table) as batch:
            for name in columns:
                if name in existing:
                    batch.drop_column(name)
