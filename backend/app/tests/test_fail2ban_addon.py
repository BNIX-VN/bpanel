"""fail2ban, and the one thing that makes it worth installing.

A ban that never reaches iptables looks exactly like one that does: fail2ban
logs "Ban 1.2.3.4" when it decides, not when the kernel agrees. Debian picks
the ban action by probing the machine, and a server that once had ufw keeps
its chains long after the package is gone - enough evidence for fail2ban to
hand every ban to a firewall that is not running. Seen on a live customer
server: 18 ufw-* chains, no ufw binary, ufw service inactive.

So the addon pins the action and proves a ban lands before reporting success.
These tests hold it to that.
"""

from pathlib import Path

import pytest

from app.services import addons, fail2ban

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _function(name):
    start = HELPER.index(f"{name}() {{")
    return HELPER[start:HELPER.index("\n}\n", start)]


# --- the ufw trap -----------------------------------------------------------

def test_the_ban_action_is_pinned_not_detected():
    body = _function("write_fail2ban_jail")
    assert "banaction = iptables-multiport" in body, (
        "left to its own devices fail2ban can pick ufw on a machine that only "
        "has ufw's leftover chains, and every ban then goes nowhere"
    )


def test_the_install_proves_a_ban_reaches_the_kernel():
    body = _function("install_fail2ban")
    assert "fail2ban_ban_reaches_the_kernel" in body
    assert "deny " in body, "a ban that does not land has to fail the install"


def test_the_proof_looks_in_iptables_not_at_fail2bans_own_word():
    body = _function("fail2ban_ban_reaches_the_kernel")
    assert "iptables-save" in body
    assert "banip" in body and "unbanip" in body, "ban, check, then put it back"


def test_the_probe_address_can_inconvenience_nobody():
    """RFC 5737 TEST-NET-1. Never routed."""
    assert "FAIL2BAN_PROBE_IP=192.0.2.1" in HELPER


def test_status_rechecks_that_bans_still_land():
    body = _function("fail2ban_status")
    assert "bans_reach_kernel" in body, (
        "'active' is not the same as 'working'; the config can change under it"
    )


# --- not locking the server out of itself -----------------------------------

def test_the_machines_own_addresses_are_never_banned():
    body = _function("fail2ban_local_addresses")
    assert "127.0.0.1/8" in body and "::1" in body
    assert "scope global" in body, "every address the machine holds, not just loopback"
    assert "ignoreip" in _function("write_fail2ban_jail")


def test_turning_the_addon_off_keeps_everything():
    body = _function("remove_fail2ban")
    assert "systemctl disable --now fail2ban" in body
    assert "apt-get remove" not in body and "purge" not in body, (
        "uninstalling an addon must not delete what it created"
    )


# --- the verbs --------------------------------------------------------------

@pytest.mark.parametrize("verb", [
    "fail2ban-install)", "fail2ban-remove)", "fail2ban-status)",
    "fail2ban-banned)", "fail2ban-unban)",
])
def test_the_helper_exposes_the_verb(verb):
    assert verb in HELPER


def test_unban_refuses_anything_that_is_not_an_address():
    body = HELPER[HELPER.index("fail2ban-unban)"):]
    body = body[:body.index(";;")]
    assert "not an address" in body


# --- the service layer ------------------------------------------------------

def test_status_reads_the_helpers_key_value_output():
    parsed = fail2ban._parse(
        "installed=yes\nrunning=yes\njails=sshd\nbanned=7\n"
        "banaction=iptables-multiport\nbans_reach_kernel=yes\n"
    )
    assert parsed == {
        "installed": True, "running": True, "jails": ["sshd"], "banned": 7,
        "banaction": "iptables-multiport", "bans_reach_kernel": True,
    }


def test_a_running_service_whose_bans_do_not_land_is_called_out(monkeypatch):
    class _Result:
        stdout = ("installed=yes\nrunning=yes\njails=sshd\nbanned=3\n"
                  "banaction=ufw\nbans_reach_kernel=no\n")

    monkeypatch.setattr(fail2ban.shell, "privileged", lambda *a, **k: _Result())
    info = fail2ban.status()
    assert "warning" in info, (
        "a service that looks healthy and protects nothing is the failure this "
        "addon exists to avoid"
    )
    assert fail2ban.JAIL_FILE in info["warning"]


def test_a_healthy_service_carries_no_warning(monkeypatch):
    class _Result:
        stdout = ("installed=yes\nrunning=yes\njails=sshd\nbanned=3\n"
                  "banaction=iptables-multiport\nbans_reach_kernel=yes\n")

    monkeypatch.setattr(fail2ban.shell, "privileged", lambda *a, **k: _Result())
    assert "warning" not in fail2ban.status()


@pytest.mark.parametrize("bad", ["", "   ", "1.2.3.4; rm -rf /", "example.com", "a" * 60])
def test_unban_rejects_a_bad_address(bad, monkeypatch):
    called = []
    monkeypatch.setattr(fail2ban.shell, "privileged", lambda *a, **k: called.append(a))
    with pytest.raises(ValueError):
        fail2ban.unban(bad)
    assert called == [], "nothing may reach the helper until it parses as an address"


@pytest.mark.parametrize("good", ["1.2.3.4", "192.0.2.1", "2001:db8::1", "::1"])
def test_unban_accepts_an_address(good, monkeypatch):
    called = []
    monkeypatch.setattr(fail2ban.shell, "privileged",
                        lambda *a, **k: called.append(k.get("helper_args")))
    fail2ban.unban(good)
    assert called == [[good]]


def test_banned_refuses_a_jail_name_that_is_not_one(monkeypatch):
    monkeypatch.setattr(fail2ban.shell, "privileged", lambda *a, **k: None)
    with pytest.raises(ValueError):
        fail2ban.banned("sshd; cat /etc/shadow")


def test_banned_keeps_only_things_that_look_like_addresses(monkeypatch):
    class _Result:
        stdout = "1.2.3.4\n\n2001:db8::1\nStatus for the jail:\n5.6.7.8\n"

    monkeypatch.setattr(fail2ban.shell, "privileged", lambda *a, **k: _Result())
    assert fail2ban.banned() == ["1.2.3.4", "2001:db8::1", "5.6.7.8"]


# --- the addon itself -------------------------------------------------------

def test_it_is_in_the_catalogue_and_keeps_its_data():
    entry = addons.known(addons.FAIL2BAN)
    assert entry["keeps_data_on_uninstall"] is True
    assert entry["name"] == "Fail2ban"


def test_the_notes_tell_an_admin_about_the_ufw_trap():
    """The one thing someone debugging this at 2am needs to have been told."""
    notes = " ".join(addons.known(addons.FAIL2BAN)["notes"]).lower()
    assert "ufw" in notes and "iptables-multiport" in notes


def test_installing_the_addon_actually_installs_fail2ban():
    source = (PROJECT_ROOT / "backend" / "app" / "api" / "addons.py").read_text(encoding="utf-8")
    body = source[source.index("def install_addon"):source.index("def uninstall_addon")]
    assert "fail2ban.install()" in body
    assert body.index("fail2ban.install()") < body.index("addons.install(slug)"), (
        "record it as installed only after the install succeeded"
    )


def test_removing_the_addon_stops_the_service():
    source = (PROJECT_ROOT / "backend" / "app" / "api" / "addons.py").read_text(encoding="utf-8")
    body = source[source.index("def uninstall_addon"):]
    assert "fail2ban.stop()" in body
