"""A sub-account opens inside its site folder, not on its chroot root (1.20.5).

The chroot root /var/lib/bpanel-sftp/<sub> must be root's - sshd's rule for
ChrootDirectory - so it takes no uploads. WinSCP opened there, showing only
the site folder, and customers who dropped files next to it got "Permission
denied" (2026-11-23). sshd now runs internal-sftp -d %d and the account's home
is "/<site>", a path inside the chroot. usermod cannot change the home of an
account that shares the owner's uid (the owner's PHP keeps it "in use"), so an
account whose home must change is made again with the same password hash.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
SCRIPTS = {
    "install.sh": (PROJECT_ROOT / "installer" / "install.sh").read_text(encoding="utf-8"),
    "update.sh": UPDATE,
    "bpanelctl": (PROJECT_ROOT / "installer" / "files" / "bpanelctl").read_text(encoding="utf-8"),
}


def _function(text: str, name: str) -> str:
    body = text[text.index(f"\n{name}() {{") + 1:]
    return body[:body.index("\n}\n") + 3]


def _code(text: str, name: str) -> str:
    return "\n".join(line for line in _function(text, name).splitlines() if not line.strip().startswith("#"))


def _block(src: str) -> str:
    # The heredoc, not the sed line above it that names the same markers.
    start = src.index("\n# BEGIN BPANEL SFTP USERS\n")
    return src[start:src.index("\n# END BPANEL SFTP USERS\n", start)]


def test_every_sshd_block_starts_a_sub_account_in_its_home():
    for name, src in SCRIPTS.items():
        block = _block(src)
        main, sub = block.split("Match Group bpanel-sftp-site", 1)
        assert "ForceCommand internal-sftp -d /\n" in main, f"{name}: the panel user still starts at /"
        assert "ForceCommand internal-sftp -d %d\n" in sub, f"{name}: a sub-account must start in its home"
        assert "ChrootDirectory /var/lib/bpanel-sftp/%u" in sub, name


def test_fix_permissions_keeps_the_sub_account_block():
    # bpanelctl fix-permissions rewrote the whole block with the panel-user
    # half only, which took the sub-accounts' chroot away.
    ctl = SCRIPTS["bpanelctl"]
    block = _block(ctl)
    assert block.index("Match Group bpanel-sftp\n") < block.index("Match Group bpanel-sftp-site")
    for directive in ("PermitTTY no", "AllowTcpForwarding no", "PermitTunnel no", "X11Forwarding no"):
        assert block.count(directive) == 2, directive


def test_a_new_sub_account_gets_its_site_as_home():
    code = _code(HELPER, "ensure_sftp_account")
    assert '-M -d "/$domain" -s /usr/sbin/nologin "$sub"' in code
    assert 'sftp_account_set_home "$sub" "$owner_uid" "$owner_gid" "/$domain"' in code
    assert "-d / -s" not in code


def test_the_home_is_changed_without_usermod():
    code = _code(HELPER, "sftp_account_set_home")
    assert "usermod" not in code and "userdel -r" not in code
    assert code.index("getent shadow") < code.index("userdel -f") < code.index("useradd -o") < code.index("chpasswd -e")
    assert '-G "$BPANEL_SFTP_SITE_GROUP"' in code


def test_the_update_moves_the_accounts_made_before():
    call = UPDATE.index("\nmigrate_sftp_start_dirs\n")
    assert UPDATE.index("migrate_sftp_start_dirs() {") < call
    assert "usermod" not in _code(UPDATE, "migrate_sftp_start_dirs")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_update_step_remakes_only_accounts_with_a_stale_home(tmp_path):
    root = tmp_path / "bpanel-sftp"
    (root / "sftp_alice_ab12cd" / "alice.test").mkdir(parents=True)   # home "/": moved
    (root / "sftp_bob_cd34ef" / "bob.test").mkdir(parents=True)       # already right
    (root / "sftp_multi_gh56ij" / "a.test").mkdir(parents=True)       # two folders: left alone
    (root / "sftp_multi_gh56ij" / "b.test").mkdir(parents=True)
    (root / "sftp_gone_kl78mn" / "gone.test").mkdir(parents=True)     # no such account
    calls = tmp_path / "calls"
    stubs = r"""
getent() {
  case "$1:$2" in
    passwd:sftp_alice_ab12cd) echo "sftp_alice_ab12cd:x:1001:1001::/:/usr/sbin/nologin" ;;
    shadow:sftp_alice_ab12cd) echo 'sftp_alice_ab12cd:!$6$salt$hash:20000:0:99999:7:::' ;;
    passwd:sftp_bob_cd34ef) echo "sftp_bob_cd34ef:x:1002:1002::/bob.test:/usr/sbin/nologin" ;;
    passwd:sftp_multi_gh56ij) echo "sftp_multi_gh56ij:x:1003:1003::/:/usr/sbin/nologin" ;;
    *) return 2 ;;
  esac
}
userdel() { echo "userdel $*" >>"$CALLS"; }
useradd() { echo "useradd $*" >>"$CALLS"; }
chpasswd() { echo "chpasswd $* $(cat)" >>"$CALLS"; }
"""
    script = (
        "set -euo pipefail\n"
        f'CALLS="{calls.as_posix()}"\n'
        + stubs
        + f'BPANEL_SFTP_CHROOT_ROOT="{root.as_posix()}"\n'
        + _function(UPDATE, "migrate_sftp_start_dirs")
        + "migrate_sftp_start_dirs\n"
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    log = calls.read_text(encoding="utf-8").splitlines()
    assert log == [
        "userdel -f sftp_alice_ab12cd",
        "useradd -o -u 1001 -g 1001 -G bpanel-sftp-site -M -d /alice.test -s /usr/sbin/nologin sftp_alice_ab12cd",
        # The hash comes back as it was: a locked account stays locked.
        "chpasswd -e sftp_alice_ab12cd:!$6$salt$hash",
    ]
    assert "WARNING" not in result.stdout
