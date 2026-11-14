"""A cPanel pack says how far it is (operator, 2026-11-14, .232: the restore
row read "Packing thanhnam1 on the other server" for a quarter of an hour,
pkgacct writing its log over there and nothing said on the connection), and
the connection is kept alive meanwhile."""
from pathlib import Path

from app.services import migrate_ssh, restore_sources


class _Channel:
    def __init__(self, command: str, polls: int, out: bytes = b""):
        self.command, self.polls, self.out = command, polls, out

    def exec_command(self, command):
        self.command = command

    def recv_ready(self):
        return bool(self.out) and self.polls <= 0

    def recv(self, _size):
        out, self.out = self.out, b""
        return out

    def recv_stderr_ready(self):
        return False

    def exit_status_ready(self):
        self.polls -= 1
        return self.polls < 0

    def recv_exit_status(self):
        return 0

    def close(self):
        pass


class _Transport:
    def __init__(self):
        self.commands = []

    def open_session(self):
        transport = self

        class Opened(_Channel):
            def exec_command(self, command):
                transport.commands.append(command)
                if "pkgacct" in command and "tail -n 1" not in command:
                    self.polls = 4               # the pack: a few looks before it is done
                elif "tail -n 1" in command:
                    self.out = b"pkgacct working ... Copying homedir\n2621440\t/home/bpanel-migrate.abc123\n"
                    self.polls = 0
                else:                            # find: the archive it left
                    self.out = b"cpmove-thanhnam1.tar.gz\t123\n"
                    self.polls = 0

        return Opened("", 0)


class _Client:
    def __init__(self):
        self.transport = _Transport()

    def get_transport(self):
        return self.transport


def test_the_row_hears_what_pkgacct_is_on_and_how_much_it_has_packed(monkeypatch):
    monkeypatch.setattr(migrate_ssh.time, "sleep", lambda _s: None)
    real_exec = migrate_ssh._exec
    monkeypatch.setattr(migrate_ssh, "_exec", lambda client, command, timeout, on_tick=None, tick_every=20.0:
                        real_exec(client, command, timeout, on_tick=on_tick, tick_every=0))
    heard = []

    name = migrate_ssh._pack_cpanel(_Client(), "thanhnam1", "/home/bpanel-migrate.abc123", heard.append)

    assert name == "cpmove-thanhnam1.tar.gz"
    assert heard and heard[0] == ("Packing thanhnam1 on the other server (2.5 GB so far): "
                                  "pkgacct working ... Copying homedir")


def test_without_anyone_listening_it_does_not_look():
    client = _Client()
    migrate_ssh._pack_cpanel(client, "thanhnam1", "/home/bpanel-migrate.abc123")
    assert not any("tail -n 1" in command for command in client.transport.commands)


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


def test_the_migration_login_keeps_its_connection_alive():
    source = Path(restore_sources.__file__).read_text(encoding="utf-8")
    body = source.split("def _transport(")[1].split("\ndef ")[0]
    assert 'getattr(transport, "set_keepalive", None)' in body and "keepalive(30)" in body
