"""reseller role: users.reseller_id, a reseller's pool, and resellers' own packages

A reseller sells hosting from its own share of the server. Its customers point
at it through users.reseller_id; the pool_* columns are its share (0 =
unlimited); user_packages.owner_id marks a package as one reseller's own, and
package names become unique per owner instead of across the server.

Revision ID: 0043_reseller
Revises: 0042_delete_revoked_tokens
Create Date: 2026-10-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0043_reseller"
down_revision = "0042_delete_revoked_tokens"
branch_labels = None
depends_on = None

POOL_COLUMNS = (
    "pool_user_limit",
    "pool_website_limit",
    "pool_storage_limit_mb",
    "pool_mail_accounts_limit",
    "pool_app_limit",
)


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    users = _columns("users")
    with op.batch_alter_table("users") as batch:
        if "reseller_id" not in users:
            batch.add_column(sa.Column("reseller_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_users_reseller_id", "users", ["reseller_id"], ["id"])
        for name in POOL_COLUMNS:
            if name not in users:
                batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
    if "ix_users_reseller_id" not in _indexes("users"):
        op.create_index("ix_users_reseller_id", "users", ["reseller_id"])

    packages = _columns("user_packages")
    with op.batch_alter_table("user_packages") as batch:
        if "owner_id" not in packages:
            batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_user_packages_owner_id", "users", ["owner_id"], ["id"])
    indexes = _indexes("user_packages")
    if "ix_user_packages_owner_id" not in indexes:
        op.create_index("ix_user_packages_owner_id", "user_packages", ["owner_id"])
    name_index = indexes.get("ix_user_packages_name")
    if name_index is not None and name_index.get("unique"):
        op.drop_index("ix_user_packages_name", table_name="user_packages")
        op.create_index("ix_user_packages_name", "user_packages", ["name"], unique=False)


def downgrade():
    indexes = _indexes("user_packages")
    if "ix_user_packages_owner_id" in indexes:
        op.drop_index("ix_user_packages_owner_id", table_name="user_packages")
    packages = _columns("user_packages")
    with op.batch_alter_table("user_packages") as batch:
        if "owner_id" in packages:
            batch.drop_constraint("fk_user_packages_owner_id", type_="foreignkey")
            batch.drop_column("owner_id")
    if "ix_users_reseller_id" in _indexes("users"):
        op.drop_index("ix_users_reseller_id", table_name="users")
    users = _columns("users")
    with op.batch_alter_table("users") as batch:
        for name in POOL_COLUMNS:
            if name in users:
                batch.drop_column(name)
        if "reseller_id" in users:
            batch.drop_constraint("fk_users_reseller_id", type_="foreignkey")
            batch.drop_column("reseller_id")
