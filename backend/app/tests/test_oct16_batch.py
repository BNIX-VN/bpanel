"""The operator's list of 2026-10-16.

1. phpMyAdmin would not open for a database imported from DirectAdmin: the
   panel never knows those passwords, so each visit now gets a login of its own.
2. A disk limit of 0 is unlimited, as the forms say; it meant 0 bytes.
3. Panel SSL failed for an administrator still on admin@example.com.
4. People were thrown out: a sign-out ended every session of the account,
   sessions lasted two hours, and nothing said why a credential was refused;
   a page opened while the API restarted showed the sign-in form.
5. No backup schedule is not a warning.
6. OPcache sizes can be set on the PHP page.
"""
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api import auth as auth_api
from app.api import deps
from app.core.config import settings
from app.models.entities import User
from app.schemas.schemas import PhpConfigUpdate
from app.services import mariadb, panel_settings, php, storage_quota

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


# --- 1. phpMyAdmin --------------------------------------------------------------------

def test_each_phpmyadmin_visit_gets_a_login_of_its_own(tmp_path, monkeypatch):
    statements = []
    monkeypatch.setattr(mariadb, "SSO_STATE_FILE", tmp_path / "logins.json")
    monkeypatch.setattr(mariadb, "_run_sql", lambda sql, check=True: statements.append(sql))
    monkeypatch.setattr(mariadb.shell, "run", lambda *a, **k: SimpleNamespace(stdout="", returncode=0))
    user, password = mariadb.create_sso_login("shop_db")
    assert re.fullmatch(r"bpsso_[0-9a-f]{10}", user) and len(password) == 32
    assert f"CREATE USER '{user}'@'localhost'" in statements[-1]
    assert "GRANT ALL PRIVILEGES ON `shop\\_db`.* TO" in statements[-1], "_ is a wildcard in a database grant"
    assert user in json.loads((tmp_path / "logins.json").read_text())


def test_logins_past_their_time_and_lost_ones_are_dropped(tmp_path, monkeypatch):
    statements = []
    state = tmp_path / "logins.json"
    state.write_text(json.dumps({"bpsso_aaaaaaaaaa": 1.0, "bpsso_bbbbbbbbbb": 9e18}))
    monkeypatch.setattr(mariadb, "SSO_STATE_FILE", state)
    monkeypatch.setattr(mariadb, "_run_sql", lambda sql, check=True: statements.append(sql))
    monkeypatch.setattr(mariadb.shell, "run", lambda *a, **k: SimpleNamespace(
        stdout="bpsso_aaaaaaaaaa\nbpsso_bbbbbbbbbb\nbpsso_cccccccccc\n", returncode=0))
    assert mariadb.drop_expired_sso_logins() == 2
    assert "bpsso_aaaaaaaaaa" in statements[-1] and "bpsso_cccccccccc" in statements[-1]
    assert "bpsso_bbbbbbbbbb" not in statements[-1]
    assert list(json.loads(state.read_text())) == ["bpsso_bbbbbbbbbb"]


def test_the_sso_route_no_longer_reads_the_sites_password():
    import inspect
    from app.api import databases
    source = inspect.getsource(databases.create_phpmyadmin_sso)
    assert "mariadb.create_sso_login(item.db_name)" in source and "decrypt(" not in source
    scheduler = (PROJECT_ROOT / "backend" / "app" / "services" / "backup_scheduler.py").read_text(encoding="utf-8")
    assert "mariadb.drop_expired_sso_logins()" in scheduler


# --- 2. disk limit 0 -------------------------------------------------------------------

def test_a_disk_limit_of_zero_is_unlimited():
    assert storage_quota.user_storage_limit_bytes(User(role="end_user", storage_limit_mb=0)) is None
    assert storage_quota.user_storage_limit_bytes(User(role="end_user", storage_limit_mb=10)) == 10 * 1024 * 1024


def test_a_restore_keeps_an_unlimited_disk():
    source = (PROJECT_ROOT / "backend" / "app" / "services" / "backup.py").read_text(encoding="utf-8")
    assert 'int(user_info.get("storage_limit_mb") or 1024)' not in source


# --- 3. panel SSL email ----------------------------------------------------------------

@pytest.mark.parametrize("email", ["admin@example.com", "x@sub.example.org", "a@b.invalid", "a@host.local", "a@localhost", ""])
def test_placeholder_addresses_give_way_to_admin_at_the_panel_host(email):
    assert panel_settings.acme_email(email, "", host="panel.example.vn") == "admin@panel.example.vn"


def test_a_real_address_is_used():
    assert panel_settings.acme_email("ops@company.vn", host="panel.example.vn") == "ops@company.vn"


# --- 4. sessions -----------------------------------------------------------------------

def test_signing_out_ends_this_session_only():
    import inspect
    logout = inspect.getsource(auth_api.logout)
    assert "token_version" not in logout.split('"""')[-1], "a sign-out must not end every other session"
    everywhere = inspect.getsource(auth_api.logout_everywhere)
    assert "current_user.token_version = (current_user.token_version or 0) + 1" in everywhere
    assert '@router.post("/logout-all")' in inspect.getsource(auth_api)


def test_six_hours_idle():
    assert settings.access_token_expire_minutes == 360


def test_a_refused_credential_says_why(caplog):
    caplog.set_level(logging.WARNING, logger="bpanel.auth")
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"), url=SimpleNamespace(path="/api/websites"))
    deps._log_reject(request, "token-version-mismatch", {"sub": "alice", "iat": 0, "exp": 9e9}, tv_token=1, tv_db=2)
    line = caplog.records[-1].getMessage()
    assert line.startswith("auth-reject reason=token-version-mismatch user=alice ip=203.0.113.9 path=/api/websites")
    assert "tv_token=1 tv_db=2" in line and "age_s=" in line and "exp_in_s=" in line


def test_the_interface_waits_for_an_api_that_is_restarting():
    assert "outcome !== SESSION_UNREACHABLE" in APP
    assert "if (!options?.silent) setError(" in APP, "a background poll says nothing"
    assert "Cannot connect to the" not in APP


# --- 5. backups --------------------------------------------------------------------------

def test_no_backup_schedule_is_not_a_warning():
    assert "No scheduled backup is set up." not in APP
    assert "tone: !backups || !backups.schedules ? 'neutral'" in APP


# --- 6. OPcache sizes ----------------------------------------------------------------------

def test_opcache_sizes_are_written_when_set(monkeypatch):
    monkeypatch.setattr(settings, "command_dry_run", True)
    content = php.update_php_ini(PhpConfigUpdate(php_version="8.3", opcache_memory_consumption=768,
                                                 opcache_interned_strings_buffer=64,
                                                 opcache_max_accelerated_files=100000))
    for line in ("opcache.memory_consumption = 768", "opcache.interned_strings_buffer = 64",
                 "opcache.max_accelerated_files = 100000"):
        assert line in content
    assert "opcache" not in php.update_php_ini(PhpConfigUpdate(php_version="8.3")), "empty keeps Auto-tune's"


def test_the_interned_strings_must_fit():
    with pytest.raises(ValueError):
        PhpConfigUpdate(opcache_memory_consumption=64, opcache_interned_strings_buffer=64)


def test_the_helper_accepts_the_opcache_sizes():
    validate = HELPER.split("\nvalidate_php_config_file() {", 1)[1].split("\n}\n", 1)[0]
    for key in ("opcache.memory_consumption)", "opcache.interned_strings_buffer)", "opcache.max_accelerated_files)"):
        assert key in validate, key


def test_the_page_is_asked_for_again_every_time(monkeypatch, tmp_path):
    """A tab brought back after sleep was drawn from the cache and showed the
    sign-in form with nothing wrong on the server."""
    from fastapi.testclient import TestClient

    from app import main

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>panel</title>", encoding="utf-8")
    (tmp_path / "robots.txt").write_text("User-agent: *", encoding="utf-8")
    monkeypatch.setattr(main, "frontend_dist", tmp_path)
    client = TestClient(main.app)
    for path in ("/", "/websites", "/index.html"):
        response = client.get(path)
        assert response.status_code == 200 and "panel" in response.text
        assert response.headers.get("cache-control") == "no-cache", path
    assert "no-cache" not in client.get("/robots.txt").headers.get("cache-control", "")
