"""Updates › Service versions: each service's version, updated one at a time or all.

The operator asked for it on 2026-10-21, right after finding that PHP from the
ondrej PPA never updated on its own. The page must name the version a service
runs and the one apt offers, and an update must touch only that service's
packages: the helper re-checks the names, this module chooses them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import service_versions
from app.services.shell import CommandResult

ROOT = Path(__file__).resolve().parents[3]
HELPER = (ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")

LISTING = """== installed
nginx 1.24.0-2ubuntu7.18
nginx-common 1.24.0-2ubuntu7.18
libnginx-mod-http-ndk 1:0.3.3-1build5
php8.3-fpm 8.3.35-1+ubuntu24.04.1+deb.sury.org+1
php8.3-mysql 8.3.35-1+ubuntu24.04.1+deb.sury.org+1
php8.4-cli 8.4.26-1+ubuntu24.04.1+deb.sury.org+1
php8.4-fpm 8.4.26-1+ubuntu24.04.1+deb.sury.org+1
php8.4-mysql 8.4.26-1+ubuntu24.04.1+deb.sury.org+1
mariadb-server 1:10.11.14-0ubuntu0.24.04.1
libmariadb3:amd64 1:10.11.14-0ubuntu0.24.04.1
docker-ce 5:29.9.2-1~ubuntu.24.04~noble
containerd.io 2.1.5-1~ubuntu.24.04~noble
== upgradable
nginx 1.24.0-2ubuntu7.19
nginx-common 1.24.0-2ubuntu7.19
php8.4-fpm 8.4.27-1+ubuntu24.04.1+deb.sury.org+1
php8.4-mysql 8.4.27-1+ubuntu24.04.1+deb.sury.org+1
containerd.io 2.1.6-1~ubuntu.24.04~noble
tmux 3.4-1ubuntu0.2
== state
inactive
== log
bpanel-service-update: started 2026-10-21T01:00:00Z for nginx
bpanel-service-update: finished (exit 1)
"""


def _fake(monkeypatch, stdout=LISTING):
    calls = []

    def privileged(command, helper_args=None, check=True, fallback=None, **_):
        calls.append((command, list(helper_args or [])))
        if command == "service-packages":
            return CommandResult(command, 0, stdout, "")
        return CommandResult(command, 0, "Service update started for 3 package(s)\n", "")

    monkeypatch.setattr(service_versions.shell, "privileged", privileged)
    return calls


def test_each_service_shows_installed_and_offered_version(monkeypatch):
    _fake(monkeypatch)
    result = service_versions.status()
    services = {item["key"]: item for item in result["services"]}
    assert list(services) == ["nginx", "php84", "php83", "mariadb", "docker"]
    assert services["php84"]["label"] == "PHP 8.4"
    assert services["php84"]["package"] == "php8.4-fpm"
    assert (services["php84"]["installed_short"], services["php84"]["available_short"]) == ("8.4.26", "8.4.27")
    assert [u["name"] for u in services["php84"]["updates"]] == ["php8.4-fpm", "php8.4-mysql"]
    # Ubuntu's fix keeps 1.24.0, so the revision is what tells them apart.
    assert services["nginx"]["installed_short"] == "1.24.0-2ubuntu7.18"
    assert services["nginx"]["available_short"] == "1.24.0-2ubuntu7.19"
    assert services["docker"]["available"] == ""
    assert [u["name"] for u in services["docker"]["updates"]] == ["containerd.io"]
    assert result["pending"] == 5, "tmux is an OS package, not a service"
    assert result["last_result"] == {"ok": False, "exit_code": 1}


def test_refresh_asks_apt_for_new_lists(monkeypatch):
    calls = _fake(monkeypatch)
    service_versions.status(refresh=True)
    assert calls == [("service-packages", ["refresh"])]


def test_one_service_updates_only_its_own_packages(monkeypatch):
    calls = _fake(monkeypatch)
    result = service_versions.run(["php84"])
    assert calls[-1] == ("service-packages-upgrade", ["php8.4-fpm", "php8.4-mysql"])
    assert result["services"] == ["php84"]


def test_update_all_takes_every_service_package_and_nothing_else(monkeypatch):
    calls = _fake(monkeypatch)
    service_versions.run(None)
    assert calls[-1] == ("service-packages-upgrade",
                         ["containerd.io", "nginx", "nginx-common", "php8.4-fpm", "php8.4-mysql"])


def test_nothing_to_do_and_unknown_services_are_refused(monkeypatch):
    _fake(monkeypatch)
    with pytest.raises(ValueError, match="Already up to date"):
        service_versions.run(["php83"])
    with pytest.raises(ValueError, match="Unknown service"):
        service_versions.run(["openlitespeed"])


def test_a_second_run_waits_for_the_first(monkeypatch):
    _fake(monkeypatch, LISTING.replace("== state\ninactive", "== state\nactive"))
    with pytest.raises(ValueError, match="already running"):
        service_versions.run(None)


def test_short_versions_drop_epoch_and_revision():
    assert service_versions.short_version("1:10.11.14-0ubuntu0.24.04.1") == "10.11.14"
    assert service_versions.short_version("8.4.26-1+ubuntu24.04.1+deb.sury.org+1") == "8.4.26"
    assert service_versions.short_version("1:2.3.21+dfsg1-2ubuntu6.5") == "2.3.21"


def test_helper_allow_list_covers_every_service_package():
    """The helper refuses anything outside its list; a service the page shows
    but the helper refuses would fail only when someone presses Update."""
    block = HELPER[HELPER.index("SERVICE_PACKAGE_GLOBS=("):]
    block = block[:block.index(")\n")]
    found = re.findall(r"'([^']+)'|([a-z0-9][a-z0-9.+-]*)", block.split("(", 1)[1])
    helper_globs = {quoted or bare for quoted, bare in found}
    page_globs = {pattern for *_, patterns in service_versions.SERVICES for pattern in patterns}
    assert page_globs <= helper_globs
    assert "php8.*" in helper_globs


def test_helper_checks_every_name_before_root_runs_apt():
    body = HELPER[HELPER.index("service_packages_upgrade() {"):]
    body = body[:body.index("\n}\n")]
    assert "service_package_allowed" in body and "install ok installed" in body
    assert "^[a-z0-9][a-z0-9+.-]*$" in body
    assert "--only-upgrade" in body, "never installs a package that is not there"
    assert body.index("deny \"a service update is already running\"") < body.index("systemd-run")
    assert "systemctl start" in body, "a daemon the upgrade left stopped is started again"


# --- System packages: what "Update OS now" upgrades (2026-10-24, as OPanel 1.36.2) -------
# "Update OS now" showed one notice that went away, and nothing said whether
# the packages were updated; and apt's list names packages Ubuntu is phasing
# in, which an upgrade leaves alone.

OS_LISTING = LISTING.replace("tmux 3.4-1ubuntu0.2\n", "tmux 3.4-1ubuntu0.2 3.4-1ubuntu0.1\nlibc6 2.39-0ubuntu8.6 2.39-0ubuntu8.5\n") + """== os-plan
install nginx
install nginx-common
install php8.4-fpm
install php8.4-mysql
install containerd.io
install libc6
phasing tmux
== os-state
inactive
== os-log
bpanel-os-update: started 2026-10-24T01:00:00Z
Setting up libc6 (2.39-0ubuntu8.6) ...
bpanel-os-update: finished (exit 0)
"""


def test_the_system_packages_are_what_an_upgrade_installs(monkeypatch):
    _fake(monkeypatch, OS_LISTING)
    system = service_versions.status()["system"]
    assert system["pending"] == 6
    assert system["others"] == [{"name": "libc6", "to": "2.39-0ubuntu8.6", "from": "2.39-0ubuntu8.5"}]
    assert system["deferred"] == [{"name": "tmux", "to": "3.4-1ubuntu0.2", "from": "3.4-1ubuntu0.1", "reason": "phasing"}]


def test_the_os_update_is_followed_to_its_end(monkeypatch):
    _fake(monkeypatch, OS_LISTING)
    system = service_versions.status()["system"]
    assert system["running"] is False and system["last_result"] == {"ok": True, "exit_code": 0}
    assert "Setting up libc6 (2.39-0ubuntu8.6) ..." in system["log"]
    _fake(monkeypatch, OS_LISTING.replace("== os-state\ninactive", "== os-state\nactive").replace("bpanel-os-update: finished (exit 0)\n", ""))
    system = service_versions.status()["system"]
    assert system["running"] is True and system["last_result"] is None
    _fake(monkeypatch, OS_LISTING.replace("finished (exit 0)", "finished (exit 100)"))
    assert service_versions.status()["system"]["last_result"] == {"ok": False, "exit_code": 100}


def test_the_helper_reports_the_os_update_and_what_an_upgrade_would_do():
    run = HELPER.split("\nrun_os_update() {\n", 1)[1].split("\n}\n", 1)[0]
    assert 'echo "bpanel-os-update: finished (exit $status)"' in run
    status = HELPER.split("\nservice_packages_status() {\n", 1)[1].split("\n}\n", 1)[0]
    assert "apt-get -s -o Debug::NoLocking=1 upgrade" in status
    assert "systemctl is-active bpanel-os-update.service" in status and "journalctl -u bpanel-os-update.service" in status
