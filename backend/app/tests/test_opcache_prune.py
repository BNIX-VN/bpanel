"""The wp-cli OPcache file cache is pruned every night (operator, 2026-11-06).

PHP never prunes its file cache: the compiled copy of a file stays after the
file, its plugin or its website is gone.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
INSTALL = (PROJECT_ROOT / "installer" / "install.sh").read_text(encoding="utf-8")


def _function() -> str:
    fn = HELPER[HELPER.index("ensure_opcache_prune_timer() {"):]
    return fn[:fn.index("\n}\n")]


def test_entries_nothing_has_read_for_two_weeks_go():
    fn = _function()
    assert "OPCACHE_PRUNE_ROOT=/var/lib/php/wpcli-opcache" in HELPER and "OPCACHE_PRUNE_DAYS=14" in HELPER
    assert "-mindepth 2 -type f -atime +${OPCACHE_PRUNE_DAYS} -delete" in fn
    assert "-mindepth 2 -type d -empty -delete" in fn, "each account's own directory stays"
    assert " -L " not in fn and "-follow" not in fn, "links are never followed"
    assert "Nice=19" in fn and "IOSchedulingClass=idle" in fn and "Persistent=true" in fn
    assert 'systemctl enable --now "${OPCACHE_PRUNE_UNIT}.timer"' in fn


def test_the_installer_and_every_update_install_the_timer():
    assert "  opcache-prune-timer-install)\n" in HELPER
    for script in (UPDATE, INSTALL):
        assert "bpanel-helper opcache-prune-timer-install" in script
