"""per-account database limit, a reseller's database share, and its oversell switch

Packages have carried database_limit since they were added, but no account
had one and nothing counted databases. users.database_limit now holds it
(copied from the package like the other limits; 0 = unlimited, as in
OPanel). Existing accounts start at 0, so nobody loses a database or the
ability to make one by updating; assigning or editing a package applies its
value.

pool_database_limit is a reseller's share of databases; pool_oversell lets
it oversell, as cPanel and DirectAdmin do: its limits are then not added
up, and what its accounts actually hold is checked against the share.

Revision ID: 0044_database_limit_oversell
Revises: 0043_reseller
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0044_database_limit_oversell"
down_revision = "0043_reseller"
branch_labels = None
depends_on = None


def upgrade():
    users = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    with op.batch_alter_table("users") as batch:
        if "database_limit" not in users:
            batch.add_column(sa.Column("database_limit", sa.Integer(), nullable=False, server_default="0"))
        if "pool_database_limit" not in users:
            batch.add_column(sa.Column("pool_database_limit", sa.Integer(), nullable=False, server_default="0"))
        if "pool_oversell" not in users:
            batch.add_column(sa.Column("pool_oversell", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("pool_oversell")
        batch.drop_column("pool_database_limit")
        batch.drop_column("database_limit")
