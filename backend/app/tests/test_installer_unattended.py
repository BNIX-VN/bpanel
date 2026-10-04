"""An install or update never stops to ask a question nobody sees.

OPanel's installs "hung" twice (2026-10-04) right after needrestart's "No VM
guests are running outdated hypervisor (qemu) binaries": the installer then ran
apt with its output sent to /dev/null and downloaded the ionCube loaders
silently, once per PHP version, with up to five minutes each. BPanel's
installer had the same steps.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INSTALL = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
UPDATE = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def _first_apt_call(text: str) -> int:
    return min(m.start() for m in re.finditer(r"(?m)^\s*(?:DEBIAN_FRONTEND=\S+\s+)?(?:apt-get|apt_get) ", text))


def test_no_package_prompt_can_stop_an_install_or_an_update():
    for name, text in (("install.sh", INSTALL), ("update.sh", UPDATE)):
        env = text.index("NEEDRESTART_SUSPEND=1")
        assert env < _first_apt_call(text), f"{name}: needrestart must be suspended before apt runs"
        line = text[text.rindex("\n", 0, env):text.index("\n", env)]
        assert "DEBIAN_FRONTEND=noninteractive" in line and line.lstrip().startswith("export")
        assert '"--force-confdef"; "--force-confold"' in text, f"{name}: dpkg must not ask about config files"
        assert "DPkg::Lock::Timeout" in text
        assert "export APT_CONFIG=" in text


def test_ioncube_is_downloaded_once_and_cannot_stop_the_install():
    fetch = INSTALL[INSTALL.index("fetch_ioncube_loaders() {"):]
    fetch = fetch[:fetch.index("\n}\n")]
    assert "IONCUBE_TRIED" in fetch, "a second PHP version reuses the first download"
    assert "--max-time" in fetch and "fail " not in fetch
    install = INSTALL[INSTALL.index("install_ioncube_loader() {"):]
    install = install[:install.index("\n}\n")]
    assert "fetch_ioncube_loaders || return 0" in install
    assert "fail " not in install and "curl" not in install and "apt_get" not in install


def test_every_download_in_the_installer_has_a_time_limit():
    for line in INSTALL.splitlines():
        if re.search(r"\bcurl\s+-", line) and not line.lstrip().startswith(("echo", "#")):
            assert "--max-time" in line, line
