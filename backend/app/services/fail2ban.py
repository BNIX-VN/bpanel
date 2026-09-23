"""SSH brute-force protection, as an addon.

A panel-managed server sits on a public address with sshd answering, and that
collects password attempts whether or not anyone is watching. A live customer
machine showed 679 failed root logins in 24 hours from six sources, with
fail2ban absent and nothing else in the way.

This module is a thin reader and writer over the helper. Everything that
touches the machine - apt, the jail file, the service, the ban list - happens
there, because that is the only code that runs as root.

Two facts worth carrying in your head when reading this:

  **A ban that does not reach the kernel looks exactly like one that does.**
  fail2ban logs "Ban 1.2.3.4" the moment it decides, not when iptables agrees.
  Debian picks the ban action by probing the machine, and a server that once
  had ufw keeps its chains long after the package is gone - enough evidence for
  fail2ban to hand every ban to a firewall that is not running. So the helper
  pins the action and proves a ban lands before calling the install a success,
  and `status()` re-checks it rather than trusting "active".

  **BPanel's own firewall does not fight this.** Its chain RETURNs the traffic
  it allows instead of ACCEPTing it, so packets fall through to fail2ban's
  chain further down INPUT. That was deliberate; see the firewall engine's
  header in bpanel-helper.
"""

from __future__ import annotations

import re

from app.services.shell import shell

JAIL_FILE = "/etc/fail2ban/jail.local"
IP_RE = re.compile(r"^[0-9a-fA-F:.]{3,45}$")


def _parse(stdout: str) -> dict:
    info: dict = {
        "installed": False,
        "running": False,
        "jails": [],
        "banned": 0,
        "banaction": "",
        "bans_reach_kernel": False,
        "filter_sees_journal": False,
        "ssh_unit": "",
        "total_failed": 0,
    }
    for line in (stdout or "").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key in {"installed", "running", "bans_reach_kernel", "filter_sees_journal"}:
            info[key] = value == "yes"
        elif key in {"banned", "total_failed"}:
            info[key] = int(value) if value.isdigit() else 0
        elif key == "ssh_unit":
            info["ssh_unit"] = value
        elif key == "jails":
            info["jails"] = [part for part in (value or "").split(",") if part]
        elif key == "banaction":
            info["banaction"] = value
    return info


def status() -> dict:
    """What fail2ban is doing, and whether its bans actually bite."""
    result = shell.privileged(
        "fail2ban-status",
        check=False,
        fallback=["bash", "-lc", "echo installed=no; echo running=no; echo banned=0"],
    )
    info = _parse(result.stdout or "")
    info["jail_file"] = JAIL_FILE
    # Two ways to run and protect nothing, and they are independent. Either
    # one alone is enough to make the service useless while looking healthy.
    if info["installed"] and info["running"]:
        if not info["bans_reach_kernel"]:
            info["warning"] = (
                "fail2ban đang chạy nhưng lệnh ban không tới được iptables. "
                f"Kiểm tra banaction trong {JAIL_FILE}."
            )
        elif not info["filter_sees_journal"]:
            info["warning"] = (
                "fail2ban đang chạy và ban được, nhưng bộ lọc đang đọc một "
                f"unit systemd không có log ({info['ssh_unit'] or 'không rõ'}). "
                "Nó sẽ không bao giờ thấy một lần đăng nhập sai nào."
            )
    return info


def install() -> dict:
    """Install, configure and prove it works. Raises if the proof fails."""
    shell.privileged("fail2ban-install", fallback=["true"])
    return status()


def stop() -> dict:
    """Stop protecting. Keeps the package, the jail file and the ban history."""
    shell.privileged("fail2ban-remove", fallback=["true"])
    return status()


def banned(jail: str = "sshd", limit: int = 50, offset: int = 0) -> dict:
    """A page of the ban list, plus how many there are.

    Paged because the page that shows this should not grow with the list. A
    server under sustained scanning holds hundreds of addresses, and sending
    all of them on every status poll costs the panel more than the operator
    gets from seeing them.
    """
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", jail or ""):
        raise ValueError("Invalid jail name")
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    result = shell.privileged(
        "fail2ban-banned", helper_args=[jail], check=False, fallback=["true"],
    )
    every = [line.strip() for line in (result.stdout or "").splitlines()
             if IP_RE.fullmatch(line.strip())]
    return {"items": every[offset:offset + limit], "total": len(every),
            "offset": offset, "limit": limit}


def unban(address: str) -> None:
    value = (address or "").strip()
    if not IP_RE.fullmatch(value):
        raise ValueError("IP không hợp lệ")
    shell.privileged("fail2ban-unban", helper_args=[value], fallback=["true"])
