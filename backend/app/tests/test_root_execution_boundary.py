"""Root must never execute a file the panel account can write.

installer/files/bpanel-sudoers hands `bpanel` a NOPASSWD wildcard on
bpanel-helper, and the helper's whole design is that it validates the argv it
receives. That boundary is worth nothing if root separately executes bytes the
same account owns - and `bpanel` can fire the root updater itself, because the
`updates-panel-run` helper verb takes no arguments and has no guard beyond
SUDO_USER=bpanel.

Two installers, two different ways to hold the line:

- install.sh runs at first install, before the bpanel account exists, so it
  builds the venv and the frontend AS ROOT and keeps .venv and node_modules
  root-owned (chown_backend_except_venv / chown_frontend_except_node_modules).
  Root builds a tree only root can write - safe. The whole-tree chown excludes
  the venv/node_modules and reclaims them to root for servers upgraded from an
  older build that had handed them to bpanel.

- update.sh runs as root (via updates-panel-run) on a live box where the bpanel
  account exists and may be compromised, so it must NOT execute the venv or
  node_modules itself. It delegates every build - venv creation, pip,
  py_compile, npm install and the vite build - to `sudo -u bpanel`, and the
  bpanel-api and scheduler units run as User=bpanel. Root never executes that
  tree, so it is owned by bpanel (which also lets the bpanel-run pip/npm write
  it; a root-owned venv would make `sudo -u bpanel pip install` fail the moment
  a dependency changed). The invariant holds by delegation, not by ownership.

These tests pin install.sh to the root-owned model and update.sh to the
delegated model, and keep the updates-panel-run tripwire.
"""

from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = PROJECT_ROOT / "installer" / "install.sh"
UPDATE_SCRIPT = PROJECT_ROOT / "installer" / "update.sh"

# `chown -R bpanel:bpanel <...>/backend` with nothing excluding the venv.
BARE_BACKEND_CHOWN = re.compile(
    r"""chown\s+-R\s+bpanel:bpanel\s+["']?\$\{?APP_DIR\}?/backend["']?\s*$""",
    re.MULTILINE,
)
# `chown -R bpanel:bpanel <...>/frontend` in any trailing form.
BARE_FRONTEND_CHOWN = re.compile(
    r"""chown\s+-R\s+bpanel:bpanel\s+["']?\$\{?APP_DIR\}?/frontend["']?""",
)


# --- install.sh: root builds, venv and node_modules stay root-owned ----------

def test_install_does_not_hand_the_virtualenv_to_bpanel():
    src = INSTALL_SCRIPT.read_text(encoding="utf-8")
    hit = BARE_BACKEND_CHOWN.search(src)
    assert hit is None, (
        "install.sh recursively chowns backend/ to bpanel without excluding "
        f".venv: {hit.group(0).strip() if hit else ''!r}. install.sh builds and "
        "executes the venv as root, so the venv must stay root-owned."
    )


def test_install_prunes_the_venv_and_reclaims_it_to_root():
    src = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert ('-path "$APP_DIR/backend/.venv" -prune' in src
            or '-path "$dir/.venv" -prune' in src), "install.sh must prune .venv when chowning backend/"
    assert "chown -R root:root" in src and ".venv" in src, (
        "install.sh must reclaim the venv to root for servers upgraded from a "
        "build that had handed it to bpanel"
    )


def test_install_does_not_hand_node_modules_to_bpanel():
    src = INSTALL_SCRIPT.read_text(encoding="utf-8")
    hit = BARE_FRONTEND_CHOWN.search(src)
    assert hit is None, (
        "install.sh recursively chowns frontend/ to bpanel without excluding "
        f"node_modules: {hit.group(0).strip() if hit else ''!r}. Root runs "
        "`npm run build` there, which executes node_modules/.bin/vite."
    )


def test_install_prunes_node_modules_and_reclaims_it_to_root():
    src = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert ('-path "$APP_DIR/frontend/node_modules" -prune' in src
            or '-path "$dir/node_modules" -prune' in src), "install.sh must prune node_modules when chowning frontend/"
    assert re.search(r"chown -R root:root .*node_modules", src), (
        "install.sh must reclaim node_modules to root for upgraded servers"
    )


def test_install_builds_the_frontend_as_root():
    """A tripwire, not a guard.

    install.sh builds before the bpanel account exists, so the build is a bare
    root `npm run build` and node_modules is root-owned throughout. Downgrading
    it with runuser would leave dist/ owned by bpanel. If someone changes this,
    revisit why install.sh keeps node_modules root-owned."""
    src = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r"^\s*VITE_API_URL=/api npm run build", src, re.MULTILINE), (
        "install.sh's frontend build is no longer a bare root `npm run build`; "
        "re-check whether install-time node_modules still needs to be root-owned"
    )


# --- update.sh: root delegates every build to bpanel, executes nothing -------

# The build commands update.sh runs; each must be delegated to bpanel so the
# root updater never executes the (bpanel-owned) venv or node_modules. These
# are the command forms, not prose, so a log/comment that happens to say
# "pip install" is not mistaken for an invocation.
_UPDATE_BUILD_STEPS = (r"\.venv/bin/pip install", r"\bnpm install\b", r"\bnpm run build\b", r"-m py_compile")


def test_update_delegates_every_build_to_bpanel():
    src = UPDATE_SCRIPT.read_text(encoding="utf-8")
    for pattern in _UPDATE_BUILD_STEPS:
        for match in re.finditer(rf"^.*{pattern}.*$", src, re.MULTILINE):
            line = match.group(0)
            stripped = line.lstrip()
            if stripped.startswith(("#", "log ", "echo ")):
                continue  # a comment or a message, not a command
            assert "sudo -u bpanel" in line, (
                f"update.sh runs `{pattern}` as root: {line.strip()!r}. It must "
                "run via `sudo -u bpanel`, or root executes a tree bpanel owns."
            )


def test_update_never_activates_the_venv_in_the_root_shell():
    src = UPDATE_SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(source|\.)\s+\S*\.venv/bin/activate", src, re.MULTILINE), (
        "update.sh sources the venv's activate in the root shell; that runs a "
        "bpanel-owned file as root. Call .venv/bin/* via sudo -u bpanel instead."
    )


def test_the_update_verb_that_fires_root_execution_is_still_argument_free():
    """Not a regression guard - a tripwire.

    The whole finding's severity rests on `bpanel` being able to trigger the
    root updater itself with no argv to validate. If someone later gives the
    verb arguments, the reasoning in the audit record needs revisiting.
    """
    helper = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
    assert "updates-panel-run)" in helper
