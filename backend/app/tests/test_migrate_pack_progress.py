"""A cPanel account is pulled as SNPanel pulls it (operator, 2026-11-14,
.232: a 14 GB account read "Packing thanhnam1 on the other server" for half
an hour, the connection silent, pkgacct tied to it; "Tham khảo bên snpanel").

pkgacct runs detached there and is looked at until it ends; the connection is
made again when it drops, without starting pkgacct twice; the archive comes
down in pieces, picked up where it stopped, and is checked against its
SHA-256 before anything there is removed. And the page picks a running
restore up again after a reload."""
import hashlib
import io
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import migrate_ssh, restore_sources

FOLDER = "/home/bpanel-migrate.Ab12Cd34Ef"
DATA = b"x" * 5000 + b"y" * 5000


class _Server:
    """The other server: what it answers, what it was asked, and a connection
    that can be made to drop."""

    def __init__(self, states=None, data=DATA, drop_on=(), digest=None):
        self.states = list(states or ["running", "exit 0"])
        self.data, self.drop_on, self.commands, self.connections = data, list(drop_on), [], 0
        self.digest = digest or hashlib.sha256(data).hexdigest()
        self.reads_before_drop = None

    def connect(self):
        server = self

        @contextmanager
        def opened():
            server.connections += 1
            yield SimpleNamespace(open_sftp=server.open_sftp, get_transport=lambda: SimpleNamespace(is_active=lambda: True))

        return opened()

    def run(self, client, command, timeout):
        self.commands.append(command)
        for marker in list(self.drop_on):
            if marker in command:
                self.drop_on.remove(marker)
                raise migrate_ssh.ConnectionLost("dropped")
        if command.startswith("umask 077; mktemp"):
            return 0, FOLDER + "\n", ""
        if "setsid nohup nice -n 10" in command:
            return 0, "4242\n", ""
        if command.startswith(f"cat {FOLDER}/run.pid"):
            return 0, "4242\n", ""
        if command.startswith("if [ -s ") and "STATE" in command:
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            size = 2684354560 if state == "running" else len(self.data)
            return 0, f"STATE {state}\nLOG pkgacct working ... Copying homedir\nSIZE {size}\n", ""
        if command.startswith("stat --printf"):
            return 0, f"{FOLDER}/cpmove-bob.tar.gz\t{len(self.data)}\n", ""
        if command.startswith("sha256sum "):
            return 0, f"{self.digest}  {FOLDER}/cpmove-bob.tar.gz\n", ""
        if command.startswith("P=$(cat ") or command.startswith("rm -rf -- "):
            return 0, "", ""
        if command.startswith("df -Pk"):
            return 0, "/dev/sda1 100 0 99999999 1% /\n", ""
        raise AssertionError(command)

    def open_sftp(self):
        server = self

        class Handle(io.BytesIO):
            def prefetch(self, *args, **kwargs):
                pass

            def read(self, size=-1):
                if server.reads_before_drop is not None:
                    if server.reads_before_drop == 0:
                        server.reads_before_drop = None
                        raise EOFError("connection reset")
                    server.reads_before_drop -= 1
                return super().read(min(size, 1000))

        return SimpleNamespace(open=lambda remote, mode="rb": Handle(server.data), close=lambda: None)


@pytest.fixture
def server(monkeypatch):
    made = _Server()
    monkeypatch.setattr(migrate_ssh, "_exec", lambda client, command, timeout: made.run(client, command, timeout))
    monkeypatch.setattr(migrate_ssh.time, "sleep", lambda _s: None)
    return made


def _pull(server, tmp_path, heard=None, size_hint=0):
    link = migrate_ssh.Link(connect=server.connect).open()

    def stage(name, pull):
        destination = tmp_path / name
        pull(str(destination))
        return str(destination)

    return migrate_ssh.pack_and_fetch(link, "cpanel", "bob", stage, lambda size: None,
                                      on_status=(heard.append if heard is not None else None), size_hint=size_hint)


def test_pkgacct_runs_detached_and_the_row_hears_how_far_it_is(server, tmp_path):
    heard = []
    got = _pull(server, tmp_path, heard)
    assert Path(got).read_bytes() == DATA
    start = next(c for c in server.commands if "setsid nohup" in c)
    assert f"/usr/local/cpanel/scripts/pkgacct bob {FOLDER}" in start and "ionice -c2 -n7" in start
    assert f"echo $! > {FOLDER}/run.pid" in start and "run.exit" in start
    assert ("Packing bob on the other server (2.5 GB so far): pkgacct working ... Copying homedir") in heard
    assert any(text.startswith("Downloading cpmove-bob.tar.gz: ") and "(100%)" in text for text in heard)
    assert server.commands[-1] == f"rm -rf -- {FOLDER}", "removed there only once it is checked here"


def test_a_dropped_connection_is_made_again_and_pkgacct_is_not_started_twice(server, tmp_path):
    server.states = ["running", "running", "exit 0"]
    server.drop_on = ["STATE"]
    _pull(server, tmp_path)
    assert server.connections == 2
    assert sum("setsid nohup" in c for c in server.commands) == 1


def test_a_lost_reply_to_the_start_finds_the_running_pkgacct(server, tmp_path):
    server.drop_on = ["setsid nohup"]
    _pull(server, tmp_path)
    assert sum("setsid nohup" in c for c in server.commands) == 1, "a lost reply is never a reason to start it again"
    assert any(c.startswith(f"cat {FOLDER}/run.pid") for c in server.commands)


def test_a_download_that_drops_is_picked_up_where_it_stopped(server, tmp_path):
    server.reads_before_drop = 4          # 4000 bytes in, then the connection resets
    heard = []
    got = _pull(server, tmp_path, heard)
    assert Path(got).read_bytes() == DATA and server.connections == 2
    assert any("picking it up again" in text for text in heard)


def test_a_download_that_does_not_match_is_not_imported(server, tmp_path):
    server.digest = "0" * 64
    with pytest.raises(migrate_ssh.MigrateError, match="checksum differs"):
        _pull(server, tmp_path)
    assert server.commands[-1] == f"rm -rf -- {FOLDER}"


@pytest.mark.parametrize("state, says", [("exit 1", "failed on the other server .exit 1."),
                                         ("gone", "stopped on the other server before it finished")])
def test_a_pkgacct_that_fails_or_vanishes_says_so_and_is_cleaned_up(server, tmp_path, state, says):
    server.states = ["running", state]
    with pytest.raises(migrate_ssh.MigrateError, match=says):
        _pull(server, tmp_path)
    assert any(c.startswith("P=$(cat ") for c in server.commands), "a run still going there is stopped"
    assert server.commands[-1] == f"rm -rf -- {FOLDER}"


def test_the_other_servers_disk_is_asked_before_packing(server, tmp_path):
    server.run_df = True
    with pytest.raises(migrate_ssh.MigrateError, match="Not enough disk space on the other server"):
        _pull(server, tmp_path, size_hint=200 * 1024 ** 3)
    assert not any("setsid nohup" in c for c in server.commands)


def test_the_archive_names_pkgacct_may_use_are_all_known():
    assert migrate_ssh._cpanel_archive_names("bob") == ["cpmove-bob.tar.gz", "bob.tar.gz", "cpmove-bob.tar"]
    assert migrate_ssh.WORK_RE.fullmatch("/backup/bpanel-migrate.Ab12Cd34Ef")


def test_sizes_read_as_people_say_them():
    assert migrate_ssh._size_label(512) == "512 KB"
    assert migrate_ssh._size_label(5 * 1024) == "5.0 MB"
    assert migrate_ssh._size_label(3 * 1024 * 1024 + 512 * 1024) == "3.5 GB"


def test_a_reloaded_page_picks_the_running_restore_up_again():
    """.232, 2026-11-14: "reload cái mất tích" - the import ran on, the page
    had forgotten it."""
    app = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    enter = app.split("function enterRestoreMode(mode) {")[1].split("\n  }\n")[0]
    assert "adoptRunningRestore();" in enter
    adopt = app.split("async function adoptRunningRestore() {")[1].split("\n  }\n")[0]
    assert "job.kind === 'user_restore'" in adopt and "setRestoreJob(" in adopt
    assert "RESTORE_MODES[kind] ? kind : 'bpanel'" in adopt, "a cPanel import shows on the cPanel page"


def test_the_migration_login_keeps_its_connection_alive_and_is_signed_in_again():
    source = Path(restore_sources.__file__).read_text(encoding="utf-8")
    body = source.split("def _transport(")[1].split("\ndef ")[0]
    assert 'getattr(transport, "set_keepalive", None)' in body and "keepalive(30)" in body
    fetch = source.split("def _fetch_over_ssh(")[1].split("\ndef ")[0]
    assert "migrate_ssh.Link(connect=connect)" in fetch and 'pinned=source["host_key"]' in fetch
