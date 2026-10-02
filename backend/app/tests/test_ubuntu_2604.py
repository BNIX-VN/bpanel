"""What Ubuntu 26.04 needs from the installer, the updater and the backend.

Checked in ubuntu:26.04 containers (2026-10-02): its default sudo is sudo-rs,
which rejects `requiretty`; its python3 is 3.14, which has no `crypt` module
and leaves a 3.12 venv unusable after do-release-upgrade; and ppa:ondrej/php
has no resolute build, while the archive itself only has PHP 8.5.
"""
import re
from pathlib import Path

import pytest

from app.core import security

ROOT = Path(__file__).resolve().parents[3]
INSTALL = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
UPDATE = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
SUDOERS = (ROOT / "installer" / "files" / "bpanel-sudoers").read_text(encoding="utf-8")


def test_the_installer_accepts_both_lts_releases():
    gate = INSTALL.split("source /etc/os-release", 1)[1].split("fi\n", 1)[0]
    assert '"${VERSION_ID}" != "24.04"' in gate and '"${VERSION_ID}" != "26.04"' in gate


def test_the_sudoers_file_uses_only_settings_sudo_rs_knows():
    rules = [line for line in SUDOERS.splitlines() if line.strip() and not line.startswith("#")]
    assert not any("requiretty" in line for line in rules)
    # sudo-rs accepts a trailing * as "any arguments", and nothing else.
    assert "bpanel ALL=(root) NOPASSWD: /usr/local/sbin/bpanel-helper *" in rules


def test_a_venv_from_another_python_is_rebuilt():
    assert "venv_python_mismatch() {" in UPDATE
    check = UPDATE.split("venv_needs_recreate=false", 1)[1].split("\nfi\n", 1)[0]
    assert 'elif venv_python_mismatch "$APP_DIR/backend/.venv"; then' in check
    webmail = HELPER.split("mail_install_webmail() {", 1)[1].split('python3 -m venv "$WEBMAIL_HOME/venv"', 1)[0]
    assert '"$venv_pyver" != "$pyver"' in webmail and 'rm -rf "$WEBMAIL_HOME/venv"' in webmail


@pytest.mark.parametrize("cfg, version", [
    ("home = /usr/bin\nversion = 3.12.3\n", "3.12"),
    ("home = /usr/bin\nversion_info = 3.14.3.final.0\n", "3.14"),
])
def test_the_venv_version_is_read_from_pyvenv_cfg(cfg, version):
    pattern = UPDATE.split("have=\"$(sed -n 's/", 1)[1].split("/\\2/p'", 1)[0]
    regex = pattern.replace("\\(", "(").replace("\\)", ")").replace("\\{0,1\\}", "?")
    assert re.search(regex, cfg, re.M).group(2) == version


def test_the_ppa_is_only_added_where_it_publishes_this_release():
    install_php = INSTALL.split("install_php() {", 1)[1].split("\n}\n", 1)[0]
    assert install_php.index("if ondrej_php_available; then") < install_php.index("add-apt-repository -y ppa:ondrej/php")
    # Without the PPA, the archive's PHP, unless the operator chose versions.
    assert 'if [[ -z "$PHP_VERSIONS_CHOSEN" && -n "$archive_version" ]]; then' in install_php
    assert "DEFAULT_PHP_VERSION=${PHP_DEFAULT}" in INSTALL
    helper = HELPER.split("install_php_version() {", 1)[1].split("\n}\n", 1)[0]
    assert helper.index("ppa.launchpadcontent.net/ondrej/php/ubuntu/dists/${codename}/Release") < helper.index(
        "add-apt-repository -y ppa:ondrej/php")
    assert "/etc/apt/sources.list.d/*.sources" in helper


def test_the_archive_php_version_comes_from_php_fpm():
    line = INSTALL.split("archive_php_version() {", 1)[1].split("\n}", 1)[0]
    pattern = line.split("sed -n 's/", 1)[1].split("/\\1/p'", 1)[0]
    regex = pattern.replace("\\(", "(").replace("\\)", ")")
    assert re.search(regex, "Depends: php8.5-fpm").group(1) == "8.5"


@pytest.mark.skipif(security._crypt_rn is None, reason="no libcrypt here")
def test_a_shadow_hash_still_verifies_without_the_crypt_module(monkeypatch):
    from passlib.hash import sha512_crypt

    hashed = sha512_crypt.using(rounds=5000).hash("correct horse")
    monkeypatch.setattr(security, "unix_crypt", None)
    assert security.verify_shadow_password("correct horse", hashed)
    assert not security.verify_shadow_password("wrong", hashed)
