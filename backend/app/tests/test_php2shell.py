"""php2shell: PHP's own mitigation (operator, 2026-10-24).

session.upload_progress.enabled=0 everywhere, fatal_error_backtraces=0 on
8.5: in every PHP's conf.d, and in every site's pool as php_admin_value, which
a site's .user.ini cannot turn back on.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _function(name):
    start = HELPER.index(f"\n{name}() {{\n") + 1
    return HELPER[start:HELPER.index("\n}\n", start)]


def test_every_pool_carries_it_as_an_admin_value():
    pool = _function("ensure_php_pool")
    assert "php_admin_value[session.upload_progress.enabled] = 0" in pool
    assert 'php2shell_pool_extra="php_admin_value[fatal_error_backtraces] = 0"' in pool
    assert '"$php_version" == 8.5' in pool


def test_every_php_gets_it_in_conf_d():
    lines = _function("php2shell_ini_lines")
    assert 'echo "session.upload_progress.enabled = 0"' in lines
    assert 'echo "fatal_error_backtraces = 0"' in lines
    fn = _function("ensure_php2shell_ini")
    assert "/etc/php/${version}/${sapi}/conf.d/97-bpanel-php2shell.ini" in fn
    assert "cmp -s" in fn and 'systemctl reload "php${version}-fpm"' in fn
    assert "  php2shell-ini)\n" in HELPER


def test_it_runs_on_install_update_and_a_new_php():
    assert "bpanel-helper php2shell-ini" in (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
    assert "bpanel-helper php2shell-ini" in (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
    assert "ensure_php2shell_ini >/dev/null || true" in _function("install_php_version")


def test_bodies_read_by_the_waf_are_never_refused():
    base = _function("write_modsec_base_conf")
    assert 'echo "SecRequestBodyAccess Off"' in base
    assert 'echo "SecRequestBodyLimitAction ProcessPartial"' in base
