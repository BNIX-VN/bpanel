"""BPanel updates and installs from its own GitLab, and servers installed before the move follow.

The source moved from github.com/BNIX-VN to gitlab.sieunhim.com/bnix on
2026-10-22 (operator's request). Every server already installed has a REPO_URL
default (and, on the branch channel, a checkout remote) that is the GitHub
address, and the helper of the release before the move hands that address to
update.sh itself. The installers found the newest v* tag through api.github.com.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
UPDATE = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
UPDATES_PY = (ROOT / "backend" / "app" / "services" / "updates.py").read_text(encoding="utf-8")
INSTALLERS = [ROOT / "install.sh", ROOT / "installer" / "install.sh"]
GITLAB = "https://gitlab.sieunhim.com/bnix/bpanel.git"
GITHUB = "https://github.com/BNIX-VN/bpanel.git"
HAVE_SHELL = shutil.which("bash") is not None and shutil.which("git") is not None


def test_every_default_points_at_gitlab():
    assert f'DEFAULT_REPO_URL="{GITLAB}"' in UPDATE
    assert f'"BPANEL_REPO_URL", "{GITLAB}"' in UPDATES_PY
    assert HELPER.count(f"${{REPO_URL:-{GITLAB}}}") == 2
    assert GITHUB not in HELPER and GITHUB not in UPDATES_PY
    assert 'WEBMAIL_REPO="https://gitlab.sieunhim.com/bnix/webmail.git"' in HELPER
    for path in INSTALLERS:
        text = path.read_text(encoding="utf-8")
        assert "https://gitlab.sieunhim.com/bnix/bpanel" in text
        assert "api.github.com" not in text.split("bpanel_latest_tag() {")[0], path


def test_an_old_github_repo_url_is_read_as_the_new_default():
    body = UPDATE[UPDATE.index("LEGACY_REPO_URLS=("):]
    body = body[:body.index("\ndone\n")]
    assert GITHUB in body and 'REPO_URL="$DEFAULT_REPO_URL"' in body


@pytest.mark.skipif(not HAVE_SHELL, reason="needs bash and git")
def test_a_checkout_on_github_moves_and_any_other_remote_stays(tmp_path):
    function = UPDATE[UPDATE.index("ensure_git_remote() {"):]
    function = function[:function.index("\n}\n") + 3]
    legacy = UPDATE[UPDATE.index("LEGACY_REPO_URLS=("):].split("\n", 1)[0]
    script = tmp_path / "t.sh"
    script.write_text(
        "set -euo pipefail\nlog() { :; }\n"
        f'REPO_URL="{GITLAB}"\nGIT_REMOTE=origin\n{legacy}\n{function}'
        "cd \"$1\"\nensure_git_remote\ngit remote get-url origin\n",
        encoding="utf-8",
    )

    def remote_after(url, name):
        repo = tmp_path / name
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)
        return subprocess.run(["bash", str(script), str(repo)], capture_output=True, text=True,
                              check=True).stdout.strip()

    assert remote_after(GITHUB, "a") == GITLAB
    assert remote_after("https://github.com/BNIX-VN/bpanel", "b") == GITLAB
    assert remote_after("https://example.com/fork.git", "c") == "https://example.com/fork.git"


@pytest.mark.skipif(not HAVE_SHELL, reason="needs bash")
@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_the_installers_build_gitlab_and_github_tarball_urls(path):
    text = path.read_text(encoding="utf-8")
    block = text[text.index('BPANEL_SOURCE="${BPANEL_SOURCE:-'):]
    block = block[:block.index("bpanel_tarball_url() {")]
    tarball = text[text.index("bpanel_tarball_url() {"):]
    tarball = tarball[:tarball.index("\n}\n") + 3]

    def url(env):
        return subprocess.run(["bash", "-c", f"set -euo pipefail\n{block}{tarball}bpanel_tarball_url v1.7.1"],
                              capture_output=True, text=True, check=True, env={**env, "PATH": "/usr/bin:/bin"}).stdout.strip()

    assert url({}) == "https://gitlab.sieunhim.com/bnix/bpanel/-/archive/v1.7.1/bpanel-v1.7.1.tar.gz"
    assert url({"BPANEL_GITHUB": "https://github.com/BNIX-VN/bpanel"}) == \
        "https://github.com/BNIX-VN/bpanel/archive/refs/tags/v1.7.1.tar.gz"


def test_release_archives_know_gitlab():
    release = UPDATE[UPDATE.index("release_archive_url() {"):]
    release = release[:release.index("\n}\n")]
    assert "https://gitlab.sieunhim.com/*)" in release and "/-/archive/" in release
