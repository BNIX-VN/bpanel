"""bpanel-update fetches the updater of the release it installs, then runs it.

It used to be a full copy of update.sh from the release already installed, so
an update ran the steps of the release it was leaving. A server built from a
July image updated straight to v1.0.170 with its July steps: the iptables
firewall migration never ran, UFW stayed in charge, and the panel said the
firewall was off (2026-09-29). The operator's rule since: the command on a
server only fetches the updater from git, so what an update installs or
removes is decided in the repository.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = (PROJECT_ROOT / "installer" / "files" / "bpanel-update").read_text(encoding="utf-8")
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
INSTALL = (PROJECT_ROOT / "installer" / "install.sh").read_text(encoding="utf-8")


def test_the_launcher_fetches_the_updater_of_the_ref_being_installed():
    assert "raw.githubusercontent.com/${url#https://github.com/}/${url_ref}/installer/update.sh" in LAUNCHER
    assert "${repo_url%.git}/-/raw/${ref}/installer/update.sh" in LAUNCHER
    assert 'url_ref="refs/tags/${ref}"' in LAUNCHER and 'url_ref="refs/tags/${tag}"' in LAUNCHER
    assert 'url_ref="refs/heads/${branch}"' in LAUNCHER
    # The newest release, found as update.sh finds it.
    assert 'git ls-remote --tags --refs "$repo_url" "refs/tags/${pattern}"' in LAUNCHER
    assert 'RELEASE_PATTERN:-v[0-9]*.[0-9]*.[0-9]*' in LAUNCHER and "sort -V | tail -n 1" in LAUNCHER


def test_the_launcher_runs_nothing_it_has_not_checked():
    fetch = LAUNCHER.index('curl -fsSL')
    run = LAUNCHER.index('/bin/bash "$script" "${args[@]}"')
    checks = LAUNCHER[fetch:run]
    assert '[[ "$(head -n 1 "$script")" != "#!/usr/bin/env bash" ]]' in checks
    assert "grep -q 'BPANEL_UPDATE_STABLE_COPY' \"$script\"" in checks
    assert 'bash -n "$script"' in checks
    # The ref names a git ref, nothing else.
    assert '[[ "$ref" =~ ^[A-Za-z0-9._/-]+$ && "$ref" != -* && "$ref" != *..* ]]' in LAUNCHER


def test_the_launcher_hands_on_every_argument_and_says_why_it_failed():
    assert 'local args=("$@")' in LAUNCHER and '"${args[@]}"' in LAUNCHER
    # A failure the panel's Update page can show, rather than an update
    # that seems to run forever.
    assert 'last_update_status="failed"' in LAUNCHER and "UPDATE_STATE_FILE" in LAUNCHER


def test_the_launcher_can_be_replaced_while_it_runs():
    # bash reads a script as it goes: all of it sits in main, called and
    # exited on one line, so the update it starts may replace the file.
    lines = [line for line in LAUNCHER.strip().splitlines() if line.strip() and not line.startswith("#")]
    assert lines[-1] == 'main "$@"; exit $?'
    assert re.search(r"^main\(\) \{$", LAUNCHER, re.M)


def test_install_and_update_leave_the_launcher_as_the_command():
    assert 'install -m 0755 -o root -g root "${SCRIPT_DIR}/files/bpanel-update" /usr/local/sbin/bpanel-update' in INSTALL
    assert '"${SCRIPT_DIR}/update.sh" /usr/local/sbin/bpanel-update' not in INSTALL
    body = UPDATE.split("install_update_command() {")[1].split("\n}\n")[0]
    assert '"$SOURCE_DIR/installer/files/bpanel-update" /usr/local/sbin/bpanel-update' in body
    # Twice: once the source is readable, and again with the other commands.
    assert UPDATE.count("\ninstall_update_command\n") == 2


def _updater_url(repo_url, ref="v1.8.1", url_ref="refs/tags/v1.8.1"):
    """Runs the launcher's own lines that pick the updater's URL."""
    import shutil
    import subprocess

    import pytest

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash here")
    start = LAUNCHER.index('  if [[ -n "${BPANEL_UPDATER_URL:-}" ]]; then')
    end = LAUNCHER.index("\n  fi\n", start) + len("\n  fi\n")
    script = ('fail() { echo "FAIL: $1"; exit 1; }\n'
              f'repo_url={repo_url!r} ref={ref!r} url_ref={url_ref!r}\n'
              + LAUNCHER[start:end] + 'echo "$url"\n')
    return subprocess.run([bash, "-c", script], capture_output=True, text=True, env={}).stdout.strip()


def test_the_launcher_finds_the_updater_on_gitlab_and_on_github():
    # 160.236.192.167, 2026-10-24: v1.7.2 moved the panel to GitLab, the
    # helper passes that REPO_URL, and the launcher knew GitHub only.
    assert 'repo_url="${REPO_URL:-https://gitlab.sieunhim.com/bnix/bpanel.git}"' in LAUNCHER
    assert _updater_url("https://gitlab.sieunhim.com/bnix/bpanel.git") == \
        "https://gitlab.sieunhim.com/bnix/bpanel/-/raw/v1.8.1/installer/update.sh"
    assert _updater_url("git@gitlab.sieunhim.com:bnix/bpanel.git", "main", "refs/heads/main") == \
        "https://gitlab.sieunhim.com/bnix/bpanel/-/raw/main/installer/update.sh"
    assert _updater_url("https://github.com/BNIX-VN/bpanel.git") == \
        "https://raw.githubusercontent.com/BNIX-VN/bpanel/refs/tags/v1.8.1/installer/update.sh"
    assert _updater_url("git@github.com:BNIX-VN/bpanel.git") == \
        "https://raw.githubusercontent.com/BNIX-VN/bpanel/refs/tags/v1.8.1/installer/update.sh"
    assert _updater_url("file:///srv/bpanel").startswith("FAIL: Cannot tell where the updater")
