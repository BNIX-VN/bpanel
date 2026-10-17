"""an account's terminal is its package's again

0030 switched the terminal on for every account that existed then, so the
allowlisted one-command terminal they already had was not taken away. The
terminal is now a real shell (operator, 2026-10-17), off by default and the
package's to give: each account takes its package's setting, and an account
with no package has none until the administrator puts it on one that has.

Revision ID: 0048_terminal_follows_package
Revises: 0047_git_repositories
Create Date: 2026-10-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0048_terminal_follows_package"
down_revision: Union[str, None] = "0047_git_repositories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FOLLOW_PACKAGE = (
    "UPDATE users SET terminal_enabled = COALESCE("
    "(SELECT user_packages.terminal_enabled FROM user_packages WHERE user_packages.id = users.package_id), 0)"
)


def upgrade() -> None:
    op.execute(FOLLOW_PACKAGE)


def downgrade() -> None:
    # What each account had before cannot be told apart from what 0030 gave it.
    pass
