"""The Shared blocklist addon: what it reads from the box, what it sends, that
turning it off leaves nothing behind, and that a failed refresh keeps the
firewall's last list."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import addons, shared_blocklist

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _function(name):
    start = HELPER.index(f"{name}() {{")
    return HELPER[start:HELPER.index("\n}\n", start) + 3]


def _events_script() -> str:
    body = _function("shared_blocklist_events")
    return body[body.index("<<'PY'\n") + len("<<'PY'\n"):body.index("\nPY\n")]


def test_the_helper_reads_bans_and_only_attack_only_waf_rules(tmp_path):
    db = tmp_path / "fail2ban.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE bans (jail TEXT, ip TEXT, timeofban INTEGER, bantime INTEGER)")
    conn.executemany("INSERT INTO bans VALUES (?,?,?,?)", [
        ("sshd", "80.94.95.115", 1792800000, 3600), ("sshd", "80.94.95.116", 1700000000, 3600)])
    conn.commit()
    conn.close()
    logs = tmp_path / "nginx"
    logs.mkdir()
    (logs / "site.vn.error.log").write_text(
        '2026/10/24 16:59:06 [error] 1#1: *1 [client 159.89.127.165] ModSecurity: Access denied with code 403 (phase 1). '
        'Matched ... [id "1001301"] [msg "BPanel blocked"]\n'
        '2026/10/24 17:05:12 [error] 1#1: *2 [client 14.225.208.202] ModSecurity: Access denied with code 403 (phase 1). '
        'Matched ... [id "1090001"] [msg "bad bot"]\n'
        '2026/10/24 17:06:00 [error] 1#1: *3 [client 10.0.0.9] ModSecurity: Access denied with code 403 (phase 2). '
        'Matched ... [id "1003002"] [msg "php2shell"]\n'
        '2026/10/24 17:13:32 [error] 1#1: *4 openat() "/home/x/favicon.ico" failed (2: No such file or directory), client: 34.12.243.235\n',
        encoding="utf-8")
    out = subprocess.run([sys.executable, "-", "1750000000", str(db), str(logs)], input=_events_script(),
                         capture_output=True, text=True, check=True).stdout.splitlines()
    rows = [line.split("\t") for line in out]
    # The old ban, the bad bot rule and the private address are left out.
    assert ["1792800000", "fail2ban:sshd", "80.94.95.115"] in rows
    assert any(row[1:] == ["waf:1001301", "159.89.127.165"] for row in rows)
    assert len(rows) == 2


def test_a_refresh_with_a_dead_source_keeps_the_last_list():
    run = _function("firewall_blocklist_run")
    assert "failed=1" in run
    guard = run.index("if (( failed == 1 && previous > 0 && count * 2 < previous )); then")
    assert guard < run.index('install -m 0640 -o root -g root "$tmp" "$FIREWALL_BLOCKLIST_WORK"')
    # And a list never puts loopback or a private range in the firewall.
    assert "network.is_loopback or network.is_private" in run


@pytest.fixture
def box(tmp_path, monkeypatch):
    """The addon against a fake collector and a fake firewall."""
    monkeypatch.setattr(shared_blocklist, "STATE_FILE", tmp_path / "shared-blocklist.json")
    on = {"value": True}
    monkeypatch.setattr(shared_blocklist, "enabled", lambda: on["value"])
    calls = []
    urls = set()
    from app.services import firewall

    def ok(text=""):
        return SimpleNamespace(returncode=0, stdout=text, stderr="")

    monkeypatch.setattr(firewall, "blocklists", lambda: ok("URLs:\n" + "\n".join(sorted(urls))))
    monkeypatch.setattr(firewall, "add_blocklist_url", lambda url: (urls.add(url), ok())[1])
    monkeypatch.setattr(firewall, "delete_blocklist_url", lambda url: (urls.discard(url), ok())[1])
    monkeypatch.setattr(firewall, "update_blocklists", lambda: (calls.append(("refresh",)), ok())[1])
    collector = {"status": "pending", "reports": []}

    def call(method, path, body=None, key=""):
        calls.append((method, path))
        if path == "/v1/register":
            assert body["panel"] == "bpanel"
            return 201, {"id": 7, "key": "bbl_x", "status": "pending"}
        if path == "/v1/me":
            return 200, {"status": collector["status"]}
        if path == "/v1/report":
            if collector["status"] != "approved":
                return 403, {"detail": "waiting"}
            collector["reports"].append(body["items"])
            return 200, {"accepted": len(body["items"])}
        raise AssertionError(path)

    monkeypatch.setattr(shared_blocklist, "_call", call)
    found = [{"at": int(time.time()), "source": "fail2ban:sshd", "ip": "80.94.95.115"}]
    monkeypatch.setattr(shared_blocklist, "events", lambda since: list(found))
    return SimpleNamespace(on=on, calls=calls, urls=urls, collector=collector)


def test_turning_it_on_registers_and_subscribes(box):
    shared_blocklist.reconcile()
    state = json.loads(shared_blocklist.STATE_FILE.read_text())
    assert state["key"] == "bbl_x" and state["status"] == "pending"
    assert shared_blocklist.LIST_URL in box.urls and ("refresh",) in box.calls
    assert box.collector["reports"] == []


def test_once_approved_it_reports_what_it_saw_once(box):
    shared_blocklist.reconcile()
    box.collector["status"] = "approved"
    shared_blocklist.check_now()
    shared_blocklist.reconcile()
    shared_blocklist.reconcile()
    assert box.collector["reports"] == [[{"ip": "80.94.95.115", "source": "fail2ban:sshd"}]]


def test_turning_it_off_leaves_nothing_behind(box):
    shared_blocklist.reconcile()
    box.on["value"] = False
    shared_blocklist.reconcile()
    assert shared_blocklist.LIST_URL not in box.urls
    assert not shared_blocklist.STATE_FILE.exists()


def test_a_server_that_never_had_it_does_nothing(box):
    box.on["value"] = False
    shared_blocklist.reconcile()
    assert box.calls == []


def test_the_key_is_readable_by_the_panel_only(box):
    shared_blocklist.reconcile()
    if os.name != "nt":
        assert shared_blocklist.STATE_FILE.stat().st_mode & 0o077 == 0


def test_it_is_an_addon_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(addons, "ADDONS_FILE", tmp_path / "addons.json")
    assert addons.SHARED_BLOCKLIST in addons.CATALOGUE
    assert addons.is_installed(addons.SHARED_BLOCKLIST) is False
