"""A sub-account's chroot is not a way into another tenant's website (1.20.4).

The chroot /var/lib/bpanel-sftp/<sub> was root:root 0755, with the website
bind-mounted inside it. Any local user - every other tenant's PHP included -
could walk in and list and read the site past the owner's 0750 home (found on
a lab box, 2026-11-21). The chroot is now root:<owner group> 0750, and the
update fixes the chroots made before.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def _function(text: str, name: str) -> str:
    body = text[text.index(f"{name}() {{"):]
    return body[:body.index("\n}\n") + 3]


def test_the_helper_makes_the_chroot_reachable_by_the_owner_group_only():
    body = _function(HELPER, "ensure_sftp_account")
    assert 'install -d -o root -g "$owner_gid" -m 0750 "$chroot"' in body
    assert 'install -d -o root -g root -m 0755 "$chroot"' not in body
    # The account shares the owner's gid, which is what lets it in.
    assert 'useradd -o -u "$owner_uid" -g "$owner_gid"' in body


def test_the_update_fixes_the_chroots_made_before():
    call = UPDATE.index("\nmigrate_sftp_chroot_modes\n")
    assert UPDATE.index("migrate_sftp_chroot_modes() {") < call


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_update_step_sets_owner_group_0750_and_locks_orphans(tmp_path):
    root = tmp_path / "bpanel-sftp"
    for name in ("sftp_alice_ab12cd", "sftp_gone_ef34gh"):
        (root / name).mkdir(parents=True)
    (root / ".accounts").mkdir()  # not a sub-account: left alone
    calls = tmp_path / "calls"
    script = (
        "set -euo pipefail\n"
        f'CALLS="{calls.as_posix()}"\n'
        'id() { [[ "$1" == "-g" && "$2" == "sftp_alice_ab12cd" ]] && { echo 1001; return 0; }; return 1; }\n'
        'chown() { echo "chown $*" >>"$CALLS"; }\n'
        'chmod() { echo "chmod $*" >>"$CALLS"; }\n'
        f'BPANEL_SFTP_CHROOT_ROOT="{root.as_posix()}"\n'
        + _function(UPDATE, "migrate_sftp_chroot_modes")
        + "migrate_sftp_chroot_modes\n"
    )
    subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True)
    log = calls.read_text(encoding="utf-8")
    alice = (root / "sftp_alice_ab12cd").as_posix()
    gone = (root / "sftp_gone_ef34gh").as_posix()
    assert f"chown root:1001 {alice}" in log and f"chmod 0750 {alice}" in log
    assert f"chown root:root {gone}" in log and f"chmod 0700 {gone}" in log
    assert ".accounts" not in log
