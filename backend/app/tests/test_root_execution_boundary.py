"""Root must never execute a file the panel account can write.

installer/files/bpanel-sudoers hands `bpanel` a NOPASSWD wildcard on
bpanel-helper, and the helper's whole design is that it validates the argv it
receives. That boundary is worth nothing if root separately reads bytes the
same account owns.

installer/update.sh runs as root and does, with the cwd set to backend/:
    source .venv/bin/activate      - runs the file in the root shell
    .venv/bin/pip install ...      - runs a binary from the venv
    .venv/bin/python -m py_compile - `python -m` puts the cwd on sys.path

while both installers used to `chown -R bpanel:bpanel $APP_DIR/backend`, venv
included. Ownership alone is enough: an owner can always chmod. And the same
account can fire the root execution itself, because the `updates-panel-run`
helper verb takes no arguments and has no guard beyond SUDO_USER=bpanel.

rsync carries --filter='protect /.venv', so anything planted there survives an
update; and the recreate guard only fires when .venv/bin/uvicorn is missing,
which on a healthy install it never is.
"""

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = PROJECT_ROOT / "installer" / "install.sh"
UPDATE_SCRIPT = PROJECT_ROOT / "installer" / "update.sh"

# `chown -R <anything> <...>/backend` with nothing excluding the venv.
BARE_BACKEND_CHOWN = re.compile(
    r"""chown\s+-R\s+bpanel:bpanel\s+["']?\$\{?APP_DIR\}?/backend["']?\s*$""",
    re.MULTILINE,
)


def _scripts() -> list[tuple[str, str]]:
    return [
        (p.name, p.read_text(encoding="utf-8"))
        for p in (INSTALL_SCRIPT, UPDATE_SCRIPT)
    ]


def test_no_installer_hands_the_virtualenv_to_the_panel_account():
    for name, src in _scripts():
        hit = BARE_BACKEND_CHOWN.search(src)
        assert hit is None, (
            f"{name} recursively chowns backend/ to bpanel without excluding "
            f".venv: {hit.group(0).strip() if hit else ''!r}. Root sources and "
            "executes files from that venv."
        )


def test_both_installers_prune_the_venv_from_the_backend_chown():
    for name, src in _scripts():
        assert '-path "$APP_DIR/backend/.venv" -prune' in src or (
            '-path "$dir/.venv" -prune' in src
        ), f"{name} must prune .venv when chowning backend/"


def test_both_installers_reclaim_a_venv_an_older_build_gave_away():
    """Existing servers already have a bpanel-owned venv; the fix has to undo it."""
    for name, src in _scripts():
        assert "chown -R root:root" in src and ".venv" in src, (
            f"{name} must chown the venv back to root, or upgraded servers keep "
            "the weakness forever"
        )


def test_the_update_verb_that_fires_root_execution_is_still_argument_free():
    """Not a regression guard - a tripwire.

    This finding's severity rests on `bpanel` being able to trigger the root
    updater itself with no argv to validate. If someone later gives the verb
    arguments, the reasoning in the audit record needs revisiting.
    """
    helper = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(
        encoding="utf-8"
    )
    assert "updates-panel-run)" in helper
