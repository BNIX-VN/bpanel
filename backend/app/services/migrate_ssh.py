"""Accounts pulled off a DirectAdmin, cPanel or FastPanel server over SSH as
root (the migration addons, operator 2026-10-27 - as OPanel's, whose
migrate_ssh.py this follows).

The Migration pages' "<panel> server" source. The panel signs in as root - the
login is typed in for this import and kept in memory only, like any other
server's in Restore - lists the accounts, and for each one picked has that
server make the account's backup the way it would itself: an admin backup
through DirectAdmin's task queue, pkgacct on cPanel; FastPanel has no backup
that keeps files and databases together, so a script packs the account in the
DirectAdmin layout (services/fastpanel_import.py). The archive comes down over
the same login's SFTP, its folder on the other server is removed, and it is
imported like an uploaded one.

Nothing typed in reaches a shell unchecked: account names are matched against
a narrow pattern, the work folder is the one mktemp printed, and every value
put in a command is quoted. The login itself never reaches a command line, a
log or the disk.
"""
from __future__ import annotations

import json
import posixpath
import re
import shlex
import time
from pathlib import PurePosixPath
from typing import Callable, Optional

PANELS = {"directadmin": "DirectAdmin", "cpanel": "cPanel", "fastpanel": "FastPanel"}
ACCOUNT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
# What mktemp makes on the other server, and the only folder ever removed there.
WORK_RE = re.compile(r"^/(?:home|backup)/bpanel-migrate\.[A-Za-z0-9]{6,16}$")
LIST_TIMEOUT = 120
# A big account takes a long time to pack; a stuck pack still has to end.
PACK_TIMEOUT = 6 * 3600
# How long the backup may make no progress at all (no archive appearing and no
# growth) before we give up, instead of waiting out PACK_TIMEOUT. A real backup
# of a large account keeps the archive growing, which resets this; only a task
# that silently produced nothing sits still this long.
PACK_STALL_GRACE = 300
DA_USERS = "/usr/local/directadmin/data/users"

StatusFn = Optional[Callable[[str], None]]
ProgressFn = Optional[Callable[[int, int], None]]


class MigrateError(RuntimeError):
    """The other server said no, phrased for the panel."""


def check_account(name: str) -> str:
    if not ACCOUNT_RE.fullmatch(name or ""):
        raise ValueError(f"Not an account name: {name!r}")
    return name


def _exec(client, command: str, timeout: float) -> tuple[int, str, str]:
    """Run one command, reading both streams as they come so neither fills up.
    A connection that is gone raises ConnectionLost, which Link answers by
    signing in again."""
    transport = client.get_transport() if client is not None else None
    if transport is None or not getattr(transport, "is_active", lambda: True)():
        raise ConnectionLost("The SSH connection to the other server closed")
    try:
        channel = transport.open_session()
        channel.exec_command(command)
    except (EOFError, OSError) as exc:
        raise ConnectionLost(f"The SSH connection to the other server closed ({exc})") from None
    except Exception as exc:  # noqa: BLE001 - paramiko.SSHException, without importing it here
        if type(exc).__name__ in {"SSHException", "ChannelException"}:
            raise ConnectionLost(f"The SSH connection to the other server closed ({exc})") from None
        raise
    out, err = bytearray(), bytearray()
    deadline = time.monotonic() + timeout
    while True:
        while channel.recv_ready():
            out.extend(channel.recv(65536))
        while channel.recv_stderr_ready():
            err.extend(channel.recv_stderr(65536))
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            break
        if time.monotonic() > deadline:
            channel.close()
            raise MigrateError("The other server took too long to answer")
        time.sleep(0.2)
        # Keep only the end of a long log: pkgacct prints a line per file.
        if len(out) > 4 * 1024 * 1024:
            del out[: len(out) - 1024 * 1024]
    code = channel.recv_exit_status()
    channel.close()
    if code == -1 and not getattr(transport, "is_active", lambda: True)():
        # The connection died under the command: no status came back.
        raise ConnectionLost("The SSH connection to the other server closed while it worked")
    return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _must(client, command: str, timeout: float, what: str) -> str:
    code, out, err = _exec(client, command, timeout)
    if code != 0:
        detail = (err or out).strip().splitlines()[-1:] or [f"exit {code}"]
        raise MigrateError(f"{what} failed on the other server: {detail[0][:300]}")
    return out


# --- listing ------------------------------------------------------------------------

_CPANEL_LIST = (
    "if [ -x /usr/local/cpanel/bin/whmapi1 ]; then "
    "/usr/local/cpanel/bin/whmapi1 --output=json listaccts want=user,domain,diskused,suspended 2>/dev/null; "
    "elif [ -r /etc/trueuserdomains ]; then echo TRUEUSERDOMAINS; cat /etc/trueuserdomains; "
    "else echo NOT_CPANEL; fi"
)

_DA_LIST = (
    f"D={DA_USERS}; [ -d \"$D\" ] || {{ echo NOT_DIRECTADMIN; exit 0; }}; "
    "for f in \"$D\"/*/user.conf; do [ -f \"$f\" ] || continue; u=$(basename \"$(dirname \"$f\")\"); "
    "v() { grep -m1 \"^$1=\" \"$2\" 2>/dev/null | cut -d= -f2-; }; "
    "printf '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \"$u\" \"$(v usertype \"$f\")\" \"$(v creator \"$f\")\" "
    "\"$(v domain \"$f\")\" \"$(v suspended \"$f\")\" \"$(v quota \"$D/$u/user.usage\")\"; done"
)


def _megabytes(value) -> int:
    """'123M', '1.5G', 'none', 123.4 -> bytes (a bare number is megabytes)."""
    text = str(value or "").strip().upper()
    match = re.match(r"^([0-9.]+)\s*([KMGT]?)", text)
    if not match:
        return 0
    try:
        number = float(match.group(1))
    except ValueError:
        return 0
    scale = {"": 1024 ** 2, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[match.group(2)]
    return int(number * scale)


def _row(panel: str, account: str, domain: str, size: int, note: str = "") -> dict:
    """One account, in the shape of restore_sources' rows: the key is the
    account name, which the other server packs when the restore runs."""
    return {"name": domain or account, "key": account, "size": int(size or 0), "modified": "",
            "username": account, "kind": panel, "where": "ssh", "domain": domain, "note": note}


def parse_cpanel_accounts(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("NOT_CPANEL"):
        raise MigrateError("That server has no cPanel (no whmapi1 and no /etc/trueuserdomains)")
    rows = []
    if text.startswith("TRUEUSERDOMAINS"):
        for line in text.splitlines()[1:]:
            domain, _, user = line.partition(":")
            user = user.strip()
            if ACCOUNT_RE.fullmatch(user):
                rows.append(_row("cpanel", user, domain.strip().lower(), 0))
        return rows
    try:
        data = json.loads(text[text.index("{"):]) if "{" in text else {}
    except ValueError as exc:
        raise MigrateError("cPanel's account list could not be read") from exc
    for account in ((data.get("data") or {}).get("acct") or []):
        user = str(account.get("user") or "")
        if not ACCOUNT_RE.fullmatch(user):
            continue
        suspended = str(account.get("suspended") or "0") not in {"0", "", "False", "false"}
        rows.append(_row("cpanel", user, str(account.get("domain") or "").lower(),
                         _megabytes(account.get("diskused")), "suspended" if suspended else ""))
    return rows


def parse_directadmin_accounts(text: str) -> list[dict]:
    if text.strip().startswith("NOT_DIRECTADMIN"):
        raise MigrateError(f"That server has no DirectAdmin ({DA_USERS} is missing)")
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 6 or not ACCOUNT_RE.fullmatch(parts[0]):
            continue
        user, usertype, _creator, domain, suspended, quota = parts[:6]
        notes = [usertype] if usertype in {"admin", "reseller"} else []
        if suspended.strip().lower() == "yes":
            notes.append("suspended")
        rows.append(_row("directadmin", user, domain.strip().lower(), _megabytes(quota), ", ".join(notes)))
    return rows


def list_accounts(client, panel: str) -> list[dict]:
    if panel == "cpanel":
        return parse_cpanel_accounts(_must(client, _CPANEL_LIST, LIST_TIMEOUT, "Listing the accounts"))
    if panel == "directadmin":
        return parse_directadmin_accounts(_must(client, _DA_LIST, LIST_TIMEOUT, "Listing the accounts"))
    if panel == "fastpanel":
        return parse_fastpanel_accounts(_must(client, _FASTPANEL_LIST, LIST_TIMEOUT, "Listing the accounts"))
    raise ValueError(f"Unknown panel: {panel}")


# --- packing one account ---------------------------------------------------------------

def _work_folder(client) -> str:
    folder = _must(client, "umask 077; mktemp -d /home/bpanel-migrate.XXXXXXXXXX", LIST_TIMEOUT,
                   "Making a work folder").strip().splitlines()[-1:]
    folder = folder[0].strip() if folder else ""
    if not WORK_RE.fullmatch(folder):
        raise MigrateError(f"Unexpected work folder on the other server: {folder!r}")
    return folder


def _remove_work_folder(client, folder: str) -> None:
    if WORK_RE.fullmatch(folder or ""):
        try:
            _exec(client, f"rm -rf -- {shlex.quote(folder)}", LIST_TIMEOUT)
        except Exception:  # noqa: BLE001 - best effort; the folder is root's and private
            pass


def _archives(client, folder: str) -> list[tuple[str, int]]:
    out = _must(client, f"find {shlex.quote(folder)} -maxdepth 1 -type f -name '*.tar*' -printf '%f\\t%s\\n'",
                LIST_TIMEOUT, "Looking for the backup")
    found = []
    for line in out.splitlines():
        name, _, size = line.partition("\t")
        if name and "/" not in name and size.isdigit():
            found.append((name, int(size)))
    return found


def _size_label(kib: int) -> str:
    for unit, step in (("GB", 1024 * 1024), ("MB", 1024)):
        if kib >= step:
            return f"{kib / step:.1f} {unit}"
    return f"{kib} KB"


def _bytes_label(size: int) -> str:
    return _size_label(max(int(size) // 1024, 0))


# --- cPanel, as SNPanel pulls it (operator, 2026-11-14, .232) ---------------------------
#
# A big account (14 GB and more) packs for most of an hour and downloads for
# as long. pkgacct used to run in the foreground of the SSH channel: the
# connection said nothing the whole time, a drop or a panel restart lost the
# pack, and a download that failed half way threw the archive away on both
# sides. Now, as SNPanel's cpanel_pull does: pkgacct runs in a session of its
# own on the other server (setsid nohup, nice, ionice) with its pid, exit
# status and log in files; the panel looks at those every CPANEL_POLL seconds,
# signing in again when the connection drops; the archive comes down in
# pieces, picked up where it stopped, and is checked against its SHA-256
# there before anything over there is removed.

CPANEL_POLL = 10
# A pkgacct still alive after this is not going to finish.
CPANEL_PACK_CAP = 24 * 3600
DOWNLOAD_ATTEMPTS = 4
# Room kept on the other server beyond the account's own size while it packs.
SOURCE_MARGIN = 512 * 1024 * 1024


class ConnectionLost(MigrateError):
    """The SSH connection to the other server went away."""


class Link:
    """The login to the other server, signed in again when it drops.

    ``connect()`` returns a context manager that yields a signed-in client (the
    host key checked against the pin every time). Built around a client alone
    - the tests, a caller with no way to sign in again - a drop is final.
    Only what is safe to do twice is done again; starting pkgacct is not.
    """

    RETRY_WAITS = (0, 5, 20)

    def __init__(self, client=None, connect: Optional[Callable[[], object]] = None):
        self.client, self._connect, self._opened = client, connect, None

    def open(self) -> "Link":
        if self.client is None:
            opened = self._connect()
            self.client = opened.__enter__()
            self._opened = opened
        return self

    def close(self) -> None:
        opened, self._opened = self._opened, None
        if opened is not None:
            self.client = None
            try:
                opened.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - it is gone either way
                pass

    def reconnect(self) -> None:
        if self._connect is None:
            raise ConnectionLost("The SSH connection to the other server was lost")
        self.close()
        last: Exception | None = None
        for wait in self.RETRY_WAITS:
            time.sleep(wait)
            try:
                self.open()
                return
            except Exception as exc:  # noqa: BLE001 - every way of not getting back in
                last = exc
        raise ConnectionLost(f"The SSH connection to the other server was lost and could not be made again ({last})")

    def run(self, command: str, timeout: float, *, again: bool = True) -> tuple[int, str, str]:
        try:
            return _exec(self.client, command, timeout)
        except ConnectionLost:
            if not again:
                raise
        self.reconnect()
        return _exec(self.client, command, timeout)

    def must(self, command: str, timeout: float, what: str) -> str:
        code, out, err = self.run(command, timeout)
        if code != 0:
            detail = (err or out).strip().splitlines()[-1:] or [f"exit {code}"]
            raise MigrateError(f"{what} failed on the other server: {detail[0][:300]}")
        return out


def _cpanel_archive_names(account: str) -> list[str]:
    """The names pkgacct may give the archive, the usual first."""
    return [f"cpmove-{account}.tar.gz", f"{account}.tar.gz", f"cpmove-{account}.tar"]


def _cpanel_work_folder(link: Link, need: int) -> str:
    """A private folder for the pack, on /home or /backup - whichever has room
    for the account (its size as listed) plus a margin, /home first."""
    base = "/home"
    if need:
        out = link.must("df -Pk /home /backup 2>/dev/null | tail -n +2", LIST_TIMEOUT, "Checking the disk space")
        free = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 6 and parts[3].isdigit() and parts[5] in ("/home", "/backup"):
                free[parts[5]] = int(parts[3]) * 1024
        if not free:
            # df names the mount the folder is on, not the folder: / for both.
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[3].isdigit():
                    free.setdefault("/home", int(parts[3]) * 1024)
        wanted = need + SOURCE_MARGIN
        roomy = [path for path in ("/home", "/backup") if free.get(path, 0) >= wanted]
        if not roomy and free:
            most = max(free.values())
            raise MigrateError(f"Not enough disk space on the other server to pack it: about "
                               f"{_bytes_label(wanted)} needed, {_bytes_label(most)} free")
        base = roomy[0] if roomy else "/home"
    folder = link.must(f"umask 077; mktemp -d {base}/bpanel-migrate.XXXXXXXXXX", LIST_TIMEOUT,
                       "Making a work folder").strip().splitlines()[-1:]
    folder = folder[0].strip() if folder else ""
    if not WORK_RE.fullmatch(folder):
        raise MigrateError(f"Unexpected work folder on the other server: {folder!r}")
    return folder


def _start_detached(link: Link, folder: str, command: str) -> None:
    """``command`` started in ``folder`` in a session of its own, so it outlives
    this connection: its output in run.log, its exit status in run.exit, its
    pid in run.pid. Started once: a lost reply is answered by looking for the
    pid, never by starting it again."""
    inner = shlex.quote(f"{command} > {folder}/run.log 2>&1; echo $? > {folder}/run.exit")
    script = (f"cd {folder} && rm -f run.exit run.pid && L=''; "
              f"command -v ionice >/dev/null 2>&1 && L='ionice -c2 -n7'; "
              f"setsid nohup nice -n 10 $L sh -c {inner} </dev/null >/dev/null 2>&1 & "
              f"echo $! > {folder}/run.pid; cat {folder}/run.pid")
    try:
        code, out, err = link.run(script, LIST_TIMEOUT, again=False)
    except ConnectionLost:
        link.reconnect()
        _code, out, _err = link.run(f"cat {folder}/run.pid 2>/dev/null", LIST_TIMEOUT)
        if out.strip().isdigit():
            return
        code, out, err = link.run(script, LIST_TIMEOUT, again=False)
    if code != 0 or not out.strip().splitlines()[-1:] or not out.strip().splitlines()[-1].strip().isdigit():
        raise MigrateError(f"pkgacct could not be started on the other server: {(err or out).strip()[-300:]}")


def _detached_status(link: Link, folder: str, names: list[str]) -> tuple[str, str, int]:
    """How the detached run stands - "running", "exit <code>" or "gone" - the
    last line of its log worth reading, and how big its archive is so far."""
    stats = " ".join(f"{folder}/{shlex.quote(name)}" for name in names)
    command = (f"if [ -s {folder}/run.exit ]; then echo \"STATE exit $(cat {folder}/run.exit)\"; "
               f"elif P=$(cat {folder}/run.pid 2>/dev/null) && [ -n \"$P\" ] && kill -0 \"$P\" 2>/dev/null; "
               f"then echo 'STATE running'; else echo 'STATE gone'; fi; "
               f"printf 'LOG %s\\n' \"$(tail -c 4000 {folder}/run.log 2>/dev/null | tr '\\r' '\\n' "
               f"| grep -v '^[[:space:].]*$' | tail -n 1)\"; "
               f"printf 'SIZE %s\\n' \"$(stat -c %s {stats} 2>/dev/null | head -n 1)\"")
    _code, out, _err = link.run(command, LIST_TIMEOUT)
    state, step, size = "gone", "", 0
    for line in out.splitlines():
        if line.startswith("STATE "):
            state = line[6:].strip()
        elif line.startswith("LOG "):
            step = re.sub(r"\s+", " ", line[4:]).strip()[:160]
        elif line.startswith("SIZE ") and line[5:].strip().isdigit():
            size = int(line[5:].strip())
    return state, step, size


def _stop_detached(link: Link, folder: str) -> None:
    """The detached run stopped, if it is still going and still ours: its
    process group, after its command line is seen to name this folder."""
    try:
        link.run(f"P=$(cat {folder}/run.pid 2>/dev/null); [ -n \"$P\" ] && kill -0 \"$P\" 2>/dev/null && "
                 f"tr '\\0' ' ' < /proc/$P/cmdline | grep -qF {folder} && kill -TERM -- -\"$P\" 2>/dev/null; true",
                 LIST_TIMEOUT)
    except Exception:  # noqa: BLE001 - best effort, on the way out
        pass


def _pack_cpanel(link: Link, account: str, folder: str, on_status: StatusFn = None) -> tuple[str, int]:
    """pkgacct, started detached and followed until it ends; the archive's
    name and size."""
    names = _cpanel_archive_names(account)
    _start_detached(link, folder,
                    f"/usr/local/cpanel/scripts/pkgacct {shlex.quote(account)} {shlex.quote(folder)}")
    started = time.monotonic()
    while True:
        state, step, size = _detached_status(link, folder, names)
        if on_status:
            text = f"Packing {account} on the other server"
            if size:
                text += f" ({_bytes_label(size)} so far)"
            if step:
                text += f": {step}"
            on_status(text)
        if state.startswith("exit"):
            code = state[4:].strip()
            if code == "0":
                break
            raise MigrateError(f"pkgacct {account} failed on the other server (exit {code}): {step or 'no detail'}")
        if state != "running":
            raise MigrateError(f"pkgacct {account} stopped on the other server before it finished: {step or 'no detail'}")
        if time.monotonic() - started > CPANEL_PACK_CAP:
            raise MigrateError(f"pkgacct {account} was still running after {CPANEL_PACK_CAP // 3600} hours")
        time.sleep(CPANEL_POLL)
    stats = " ".join(f"{folder}/{shlex.quote(name)}" for name in names)
    out = link.must(f"stat --printf '%n\\t%s\\n' {stats} 2>/dev/null; true", LIST_TIMEOUT, "Looking for the backup")
    for line in out.splitlines():
        path, _, size = line.partition("\t")
        name = posixpath.basename(path)
        if name in names and size.isdigit():
            return name, int(size)
    raise MigrateError(f"pkgacct finished, but no archive of {account} is in {folder}")


def _remote_sha256(link: Link, remote: str, size: int) -> str:
    out = link.must(f"sha256sum {shlex.quote(remote)}", 120 + size / (20 * 1024 * 1024),
                    "Checking the backup")
    digest = out.strip().split()[:1]
    if not digest or not re.fullmatch(r"[0-9a-f]{64}", digest[0]):
        raise MigrateError(f"Could not read the backup's checksum on the other server: {out.strip()[:200]}")
    return digest[0]


def _download(link: Link, remote: str, size: int, destination: str, digest: str, name: str,
              on_status: StatusFn = None, on_progress: ProgressFn = None) -> None:
    """``remote`` into ``destination``, picked up where it stopped when the
    connection drops (DOWNLOAD_ATTEMPTS times), and checked against
    ``digest``."""
    import hashlib
    import os

    import paramiko

    attempt = 0
    last_said = [0.0, 0, time.monotonic()]

    def said(done: int) -> None:
        if on_progress:
            on_progress(done, size)
        now = time.monotonic()
        if on_status and (now - last_said[0] >= 2 or done >= size):
            rate = (done - last_said[1]) / max(now - last_said[2], 0.001) if last_said[0] else 0
            last_said[:] = [now, done, now]
            pct = int(done * 100 / size) if size else 100
            text = f"Downloading {name}: {_bytes_label(done)} of {_bytes_label(size)} ({pct}%)"
            if rate:
                text += f", {_bytes_label(int(rate))}/s"
            on_status(text)

    while True:
        done = os.path.getsize(destination) if os.path.exists(destination) else 0
        if done > size:
            raise MigrateError(f"The download of {name} is bigger than the backup on the other server")
        try:
            if done < size:
                sftp = link.client.open_sftp()
                try:
                    with sftp.open(remote, "rb") as source, open(destination, "ab") as target:
                        source.seek(done)
                        try:
                            source.prefetch(size, max_concurrent_requests=64)
                        except TypeError:  # paramiko before 3.3
                            source.prefetch(size)
                        while done < size:
                            chunk = source.read(min(1024 * 1024, size - done))
                            if not chunk:
                                break
                            target.write(chunk)
                            done += len(chunk)
                            said(done)
                finally:
                    sftp.close()
            if done < size:
                raise ConnectionLost(f"the transfer stopped at {_bytes_label(done)}")
            break
        except (ConnectionLost, EOFError, OSError, paramiko.SSHException) as exc:
            attempt += 1
            if attempt >= DOWNLOAD_ATTEMPTS:
                raise MigrateError(f"The download of {name} kept failing ({exc})") from None
            if on_status:
                on_status(f"Downloading {name}: the connection dropped at {_bytes_label(done)}, "
                          f"picking it up again ({attempt}/{DOWNLOAD_ATTEMPTS - 1})")
            time.sleep(5 * attempt)
            link.reconnect()
    if on_status:
        on_status(f"Checking {name}")
    sha = hashlib.sha256()
    with open(destination, "rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            sha.update(block)
    if sha.hexdigest() != digest:
        raise MigrateError(f"The download of {name} does not match the backup on the other server "
                           "(checksum differs); it was not imported")


def _pull_cpanel(link: Link, account: str, stage, ensure_room, on_status: StatusFn = None,
                 on_progress: ProgressFn = None, size_hint: int = 0) -> str:
    """One cPanel account: packed there (detached), downloaded (resumable,
    checked), and only then removed there. Whatever happens, the run there is
    stopped and its folder removed - signing in again for it if need be."""
    if size_hint:
        ensure_room(size_hint)
    folder = _cpanel_work_folder(link, size_hint)
    try:
        if on_status:
            on_status(f"Packing {account} on the other server")
        name, size = _pack_cpanel(link, account, folder, on_status)
        ensure_room(size)
        remote = posixpath.join(folder, name)
        if on_status:
            on_status(f"Checking {name} on the other server")
        digest = _remote_sha256(link, remote, size)
        # Imported under the name cPanel's importer knows, whatever pkgacct
        # called it.
        local_name = f"cpmove-{account}.tar" if name.endswith(".tar") else f"cpmove-{account}.tar.gz"
        return stage(local_name, lambda destination: _download(
            link, remote, size, destination, digest, name, on_status, on_progress))
    finally:
        try:
            _stop_detached(link, folder)
            link.run(f"rm -rf -- {shlex.quote(folder)}", LIST_TIMEOUT)
        except Exception:  # noqa: BLE001 - best effort; the folder is root's and private
            pass


def _da_admin(client) -> str:
    out = _must(client, f"grep -l '^usertype=admin' {DA_USERS}/*/user.conf 2>/dev/null | head -n 1",
                LIST_TIMEOUT, "Finding the DirectAdmin admin")
    admin = PurePosixPath(out.strip()).parent.name if out.strip() else ""
    if not ACCOUNT_RE.fullmatch(admin):
        raise MigrateError("No DirectAdmin admin account was found on that server")
    return admin


def _pack_directadmin(client, account: str, folder: str, on_status: StatusFn) -> str:
    admin = _da_admin(client)
    _must(client, f"chown {shlex.quote(admin)}: {shlex.quote(folder)} && chmod 0700 {shlex.quote(folder)}",
          LIST_TIMEOUT, "Preparing the work folder")
    # DirectAdmin's own "Admin Backup" of one account, to a local folder.
    #
    # `what=select` means "back up the selected data categories", so every
    # category has to be named with an option* field. Without them DirectAdmin
    # writes a metadata-only archive (user.conf + history, no domains, no
    # databases, no email) - which then restores as an empty account. option0
    # (%30) is the domains directory, i.e. the actual website files. option13
    # (trash) is deliberately left out.
    task = (
        "action=backup&when=now&where=local"
        f"&local%5Fpath={folder.replace('/', '%2F')}&owner={admin}"
        f"&type=admin&value=multiple&what=select&select%30={account}"
        "&option%30=domain&option1=subdomain&option2=email&option3=forwarder"
        "&option4=autoresponder&option5=vacation&option6=list&option7=emailsettings"
        "&option8=ftp&option9=ftpsettings&option10=database&option11=database%5Fdata"
        "&option12=email%5Fdata"
    )
    quoted = shlex.quote(task)
    # Submit through DirectAdmin's task queue and run dataskq. The newer
    # `directadmin taskq --run <task>` subcommand does NOT exist on older DA
    # (seen on 1.62.x): it prints "Invalid option: --run" yet still exits 0, so
    # `_must` reads success while nothing was queued and the wait below times
    # out after hours. Appending to task.queue and running dataskq is the
    # long-standing mechanism and works on every DA version.
    command = (
        f"echo {quoted} >> /usr/local/directadmin/data/task.queue "
        "&& /usr/local/directadmin/dataskq"
    )
    out = _must(client, command, PACK_TIMEOUT, f"DirectAdmin backup of {account}")
    # Old DA accepts an unknown argument, prints "Invalid option", and still
    # exits 0 - so a command can "succeed" while doing nothing. Treat that (and
    # a DirectAdmin usage dump) as a failure rather than waiting for an archive
    # that will never appear.
    if re.search(r"invalid option|unknown option|^usage:", out, re.IGNORECASE | re.MULTILINE):
        line = next((l.strip() for l in out.splitlines() if l.strip()), "")
        raise MigrateError(
            f"DirectAdmin rejected the backup command for {account} (likely an old DA version): {line[:200]}")
    # dataskq normally runs the backup synchronously, so the archive is already
    # in place; when DirectAdmin's own cron grabbed the task first, wait for it
    # to appear and settle. Give up once it makes no progress for PACK_STALL_GRACE
    # instead of sitting here for PACK_TIMEOUT.
    deadline = time.monotonic() + PACK_TIMEOUT
    last: dict[str, int] = {}
    steady = 0
    last_progress = time.monotonic()
    while time.monotonic() < deadline:
        current = {name: size for name, size in _archives(client, folder) if f".{account}.tar" in name}
        if current and sum(current.values()) != sum(last.values()):
            last_progress = time.monotonic()  # appearing or growing == progress
        if current and current == last:
            steady += 1
            if steady >= 2:
                archive = sorted(current)[0]
                _verify_da_backup_full(client, folder, archive, account)
                return archive
        else:
            steady = 0
        if time.monotonic() - last_progress > PACK_STALL_GRACE:
            raise MigrateError(
                f"DirectAdmin produced no backup of {account} after {PACK_STALL_GRACE // 60} min with no "
                "progress - the admin backup task likely failed (old DA version, or a backup error on that "
                "server). Check the DirectAdmin task and backup logs.")
        last = current
        if on_status:
            on_status(f"Waiting for DirectAdmin to back up {account}" if not current
                      else f"Backing up {account}")
        time.sleep(10)
    raise MigrateError(f"DirectAdmin did not write a backup of {account}")


def _verify_da_backup_full(client, folder: str, archive: str, account: str) -> None:
    """Fail if DirectAdmin wrote only the account metadata and none of its data.

    `what=select` with no data categories yields a ~20 KB archive of backup/
    (user.conf + history) that restores as an empty account. A real backup also
    carries the domains' files and the mailboxes, so look for one of those.
    """
    path = shlex.quote(posixpath.join(folder, archive))
    # Decompress by extension, list entries, and stop at the first data path
    # (grep -m1 closes the pipe, so tar is not read to the end).
    command = (
        f"f={path}; case \"$f\" in "
        "*.zst) D='zstd -dc' ;; *.gz|*.tgz) D='gzip -dc' ;; "
        "*.bz2|*.tbz2) D='bzip2 -dc' ;; *.xz|*.txz) D='xz -dc' ;; *) D='cat' ;; esac; "
        "$D \"$f\" 2>/dev/null | tar -tf - 2>/dev/null "
        "| grep -m1 -E '/public_html|/private_html|/email/data|^domains/|/domains/' || true"
    )
    out = _must(client, command, LIST_TIMEOUT, f"Checking the backup of {account}")
    if not out.strip():
        raise MigrateError(
            f"DirectAdmin wrote only a metadata backup of {account} (no website files or mail) - it would "
            "restore as an empty account. The backup's data categories were not included; check the DA version.")


# --- FastPanel -----------------------------------------------------------------------
# FastPanel 2 keeps each account's sites in /var/www/<user>/data/www/<domain>
# and their nginx configs in /etc/nginx/fastpanel2-sites/<user>/<domain>.conf.
# Its own backups split files and databases, so the account is packed here, in
# the DirectAdmin layout the importer reads (services/fastpanel_import.py).

_FASTPANEL_LIST = (
    "[ -d /usr/local/fastpanel2 ] || [ -d /etc/nginx/fastpanel2-sites ] || { echo NOT_FASTPANEL; exit 0; }; "
    "for home in /var/www/*/; do u=$(basename \"$home\"); [ -d \"$home/data/www\" ] || continue; "
    "id -u \"$u\" >/dev/null 2>&1 || continue; "
    "sites=$(find \"$home/data/www\" -mindepth 1 -maxdepth 1 -type d -printf '%f,' 2>/dev/null); "
    "size=$(timeout 20 du -sb \"$home/data\" 2>/dev/null | cut -f1); "
    "printf '%s\\t%s\\t%s\\n' \"$u\" \"${sites%,}\" \"${size:-0}\"; done"
)


def parse_fastpanel_accounts(text: str) -> list[dict]:
    if text.strip().startswith("NOT_FASTPANEL"):
        raise MigrateError("That server has no FastPanel (/usr/local/fastpanel2 is missing)")
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not ACCOUNT_RE.fullmatch(parts[0]):
            continue
        sites = [site.lower() for site in parts[1].split(",") if DOMAIN_RE.fullmatch(site.lower())]
        if not sites:
            continue
        size = int(parts[2]) if parts[2].isdigit() else 0
        rows.append(_row("fastpanel", parts[0], sites[0], size,
                         f"{len(sites)} site(s)" if len(sites) > 1 else ""))
    return rows


# Run as root on the FastPanel server with U (the account) and W (the work
# folder) set. Prints the archive's name on its last line.
_FASTPANEL_PACK = r"""
set -eu
H="/var/www/$U"; P="$W/pack"
[ -d "$H/data/www" ] || { echo "no sites for $U" >&2; exit 1; }
mkdir -p "$P/backup" "$P/mysql" "$P/bpanel"
printf 'username=%s\nemail=\n' "$U" > "$P/backup/user.conf"
: > "$P/backup/domains.list"; : > "$P/bpanel/aliases.tsv"
transforms=(); paths=()
for d in "$H"/data/www/*/; do
  dom=$(basename "$d")
  printf '%s' "$dom" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' || continue
  echo "$dom" >> "$P/backup/domains.list"
  transforms+=("--transform=s#^var/www/$U/data/www/${dom//./\\.}#domains/$dom/public_html#")
  paths+=("var/www/$U/data/www/$dom")
  conf="/etc/nginx/fastpanel2-sites/$U/$dom.conf"
  [ -f "$conf" ] || continue
  names=$(grep -hE '^\s*server_name\s' "$conf" | head -n 1 | sed -E 's/^\s*server_name\s+//; s/;.*$//')
  printf '%s\t%s\n' "$dom" "$names" >> "$P/bpanel/aliases.tsv"
  crt=$(grep -hE '^\s*ssl_certificate\s' "$conf" | head -n 1 | awk '{print $2}' | tr -d ';')
  key=$(grep -hE '^\s*ssl_certificate_key\s' "$conf" | head -n 1 | awk '{print $2}' | tr -d ';')
  if [ -n "$crt" ] && [ -n "$key" ] && [ -f "$crt" ] && [ -f "$key" ]; then
    mkdir -p "$P/backup/$dom"; cp "$crt" "$P/backup/$dom/domain.cert"; cp "$key" "$P/backup/$dom/domain.key"
  fi
done
[ ${#paths[@]} -gt 0 ] || { echo "no sites for $U" >&2; exit 1; }
# The databases: those the sites' configs name, and those named after the account.
mysql_ok=1; mysql -NBe 'SELECT 1' >/dev/null 2>&1 || mysql_ok=0
if [ "$mysql_ok" = 1 ]; then
  {
    find "$H/data/www" -maxdepth 4 -name wp-config.php -type f -exec grep -hoE "define\(\s*['\"]DB_NAME['\"]\s*,\s*['\"][A-Za-z0-9_]+" {} + 2>/dev/null | sed -E "s/.*['\"]//"
    find "$H/data/www" -maxdepth 4 -name .env -type f -exec grep -hoE '^DB_DATABASE=["'"'"']?[A-Za-z0-9_]+' {} + 2>/dev/null | sed -E "s/^DB_DATABASE=[\"']?//"
    mysql -NBe 'SHOW DATABASES' | grep -E "^${U}(_|$)" || true
  } | sort -u | while read -r db; do
    printf '%s' "$db" | grep -Eq '^[A-Za-z0-9_]{1,64}$' || continue
    mysql -NBe 'SHOW DATABASES' | grep -qx "$db" || continue
    mysqldump --single-transaction --quick --routines --events --triggers "$db" > "$P/mysql/$db.sql"
  done
else
  echo "MySQL could not be read as root: the account is packed without its databases" >&2
fi
tar -C / -czf "$W/fastpanel-$U.tar.gz" "${transforms[@]}" "${paths[@]}" -C "$P" backup mysql bpanel
echo "fastpanel-$U.tar.gz"
"""


def _pack_fastpanel(client, account: str, folder: str) -> str:
    command = f"U={shlex.quote(account)} W={shlex.quote(folder)} bash -c {shlex.quote(_FASTPANEL_PACK)}"
    out = _must(client, command, PACK_TIMEOUT, f"Packing {account}")
    name = (out.strip().splitlines() or [""])[-1].strip()
    if name != f"fastpanel-{account}.tar.gz":
        raise MigrateError(f"Packing {account} on the FastPanel server left no archive")
    return name


def pack_and_fetch(client, panel: str, account: str,
                   stage: Callable[[str, Callable[[str], None]], str],
                   ensure_room: Callable[[int], None],
                   on_status: StatusFn = None, on_progress: ProgressFn = None, size_hint: int = 0) -> str:
    """Have the other server back up ``account``, download it, clean up there.

    ``client`` is a signed-in client or a Link (which signs in again when the
    connection drops). ``stage(name, pull)`` puts the archive where its kind
    is imported from - calling ``pull(destination)`` to fill the file - and
    returns that path; ``ensure_room(size)`` refuses an archive the disk here
    cannot take; ``size_hint`` is the account's size as listed, when known.
    The folder on the other server goes whatever happens.
    """
    check_account(account)
    link = client if isinstance(client, Link) else Link(client=client)
    if panel == "cpanel":
        return _pull_cpanel(link, account, stage, ensure_room, on_status, on_progress, size_hint)
    client = link.client
    folder = _work_folder(client)
    try:
        if on_status:
            on_status(f"Packing {account} on the other server")
        if panel == "directadmin":
            name = _pack_directadmin(client, account, folder, on_status)
        elif panel == "fastpanel":
            name = _pack_fastpanel(client, account, folder)
        else:
            raise ValueError(f"Unknown panel: {panel}")
        remote = posixpath.join(folder, name)
        sftp = client.open_sftp()
        try:
            total = sftp.stat(remote).st_size or 0
            ensure_room(total)
            if on_status:
                on_status(f"Downloading {name}")

            def pull(destination: str) -> None:
                sftp.get(remote, destination, callback=on_progress)

            return stage(name, pull)
        finally:
            sftp.close()
    finally:
        _remove_work_folder(client, folder)
