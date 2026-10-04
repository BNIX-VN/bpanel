"""Every helper subcommand the backend calls must exist in the helper.

Suspension called ``panel-user-lock`` and ``panel-user-unlock`` from the start,
and the helper had no case label for either: the calls reached the dispatch's
default arm, which fails, and because the callers passed ``check=False`` the
failure was discarded. A suspended customer kept SFTP and SSH, and nothing
reported a problem. OPanel found the same defect the same way; a name-level
diff catches the whole class and costs nothing.
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh"
BACKEND_APP = PROJECT_ROOT / "backend" / "app"


def _helper_case_labels() -> set[str]:
    """Every label in the helper's dispatch case, alternations expanded
    (``  nginx-reload|nginx-test)`` at two-space indentation)."""
    text = HELPER.read_text(encoding="utf-8")
    labels: set[str] = set()
    for match in re.finditer(r"(?m)^  ([a-z0-9][a-z0-9|-]*)\)", text):
        labels.update(name for name in match.group(1).split("|") if name)
    return labels


def _privileged_subcommands() -> dict[str, set[str]]:
    """Subcommand -> the "file:line"s that call it: the first argument of
    ``shell.privileged(...)``, on one line or the next."""
    calls: dict[str, set[str]] = {}
    pattern = re.compile(r"""shell\.privileged\(\s*\n?\s*["']([a-z0-9][a-z0-9-]*)["']""")
    for path in sorted(BACKEND_APP.rglob("*.py")):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            calls.setdefault(match.group(1), set()).add(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{lineno}")
    return calls


def test_every_called_subcommand_exists_in_the_helper() -> None:
    labels = _helper_case_labels()
    called = _privileged_subcommands()
    assert called, "found no shell.privileged calls -- the scanner is broken"
    missing = {name: sorted(where) for name, where in called.items() if name not in labels}
    assert not missing, (
        "These helper subcommands are called but have no case label in "
        "installer/files/bpanel-helper.sh, so they fail as unknown commands:\n"
        + "\n".join(f"  {name}  <- {', '.join(where)}" for name, where in sorted(missing.items()))
    )


def test_the_suspension_subcommands_are_implemented() -> None:
    """Pinned, so a rename cannot quietly drop them again."""
    labels = _helper_case_labels()
    for name in ("panel-user-lock", "panel-user-unlock"):
        assert name in labels, f"{name} must be implemented in the helper"


def test_locking_validates_the_user_and_ends_open_sessions() -> None:
    text = HELPER.read_text(encoding="utf-8")
    lock = text[text.index("  panel-user-lock)"):text.index("  panel-user-unlock)")]
    assert 'require_linux_user "$1"' in lock, "the lock must refuse system and panel accounts"
    assert 'usermod -L "$1"' in lock
    # usermod -L stops the next login only; an open SFTP session keeps going.
    assert 'pkill -KILL -u "$1"' in lock
