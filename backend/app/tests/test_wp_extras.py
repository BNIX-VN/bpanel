"""WordPress Manager, further (OPanel's, ported to BPanel 2026-10-18): a staging
copy and a push back, a plugin or theme from a .zip, the website's Nginx page
cache, the daily check.

Every file is copied and every WP-CLI command run as the account's own user;
a copy goes only into another website of the same account whose folder holds
nothing yet; a push takes a restore point of the live site first and keeps
its wp-config.php.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.entities import DatabaseAccount, Website, WpInstall
from app.services import mariadb, wp_extras, wp_manager
from app.tests.test_wordpress_manager import env  # noqa: F401 - the shared fixture

HELPER = (Path(__file__).resolve().parents[3] / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _scan(env):
    assert env.as_user("alice").post("/api/wordpress/scan", json={}).status_code == 200
    return env.db.query(WpInstall).filter_by(website_id=env.sites["alice"].id, rel_path="").one()


def _staging_site(env, *, placeholder=True):
    root = env.tmp / "alice" / "staging.alice.example"
    (root / "public_html" / ".well-known").mkdir(parents=True)
    if placeholder:
        (root / "public_html" / "index.html").write_text("<h1>staging.alice.example is ready</h1>", encoding="utf-8")
    site = Website(domain="staging.alice.example", owner_id=env.people["alice"].id, root_path=str(root),
                   linux_user="alice", php_version="8.3", app_type="php")
    env.db.add(site)
    env.db.commit()
    return site


@pytest.fixture
def quiet(monkeypatch):
    """MariaDB, the config writer and the vhost, as a test sees them."""
    made = []
    monkeypatch.setattr(mariadb, "user_exists", lambda name: False)
    monkeypatch.setattr(mariadb, "create_database_credentials", lambda *a, **k: made.append(a))
    written = []
    monkeypatch.setattr(wp_extras, "_point_config_at", lambda website, path, creds: written.append((path, creds["db_name"])))
    import app.api.websites as websites_api
    monkeypatch.setattr(websites_api, "_rewrite_website_vhost", lambda website, **kw: "")
    return SimpleNamespace(made=made, written=written)


def test_only_an_empty_website_of_the_same_account_takes_a_copy(env):
    install = _scan(env)
    empty = _staging_site(env)
    targets = {item["domain"]: item for item in wp_extras.clone_targets(env.db, install, env.sites["alice"])}
    assert targets["staging.alice.example"]["ok"] is True
    (Path(empty.root_path) / "public_html" / "shop.php").write_text("<?php")
    targets = {item["domain"]: item for item in wp_extras.clone_targets(env.db, install, env.sites["alice"])}
    assert targets["staging.alice.example"]["ok"] is False
    assert "bob.example" not in targets  # another account's website is never offered


def test_a_staging_copy_is_made_as_the_account(env, quiet):
    install = _scan(env)
    target = _staging_site(env)
    answer = env.as_user("alice").post(f"/api/wordpress/installs/{install.id}/clone", json={"website_id": target.id})
    assert answer.status_code == 200, answer.text
    assert answer.json()["job"]["status"] == "completed", answer.json()["job"]["error"]
    commands = [(call["command"], call["user"], call["args"][:3]) for call in env.calls]
    assert ("wp-copy", "alice", [install.path, str(Path(target.root_path) / "public_html"), "all"]) in commands
    exports = [call for call in env.calls if call["command"] == "wp-site" and call["args"][:2] == ["db", "export"]]
    imports = [call for call in env.calls if call["command"] == "wp-site" and call["args"][:2] == ["db", "import"]]
    assert exports and imports and all(call["user"] == "alice" for call in exports + imports)
    replaced = [call["args"][1:3] for call in env.calls if call["command"] == "wp-site" and call["args"][0] == "search-replace"]
    assert ["https://alice.example", "http://staging.alice.example"] in replaced
    assert any(call["args"][:4] == ["option", "update", "blog_public", "0"] for call in env.calls if call["command"] == "wp-site")
    copy = env.db.query(WpInstall).filter_by(website_id=target.id).one()
    assert copy.staging_of == install.id
    assert env.db.query(DatabaseAccount).filter_by(website_id=target.id).count() == 1
    detail = env.as_user("alice").get(f"/api/wordpress/installs/{install.id}").json()
    assert detail["staging_copies"][0]["domain"] == "staging.alice.example"


def test_a_push_takes_a_restore_point_and_keeps_the_live_config(env, quiet):
    install = _scan(env)
    target = _staging_site(env)
    env.as_user("alice").post(f"/api/wordpress/installs/{install.id}/clone", json={"website_id": target.id})
    copy = env.db.query(WpInstall).filter_by(website_id=target.id).one()
    env.calls.clear()
    answer = env.as_user("alice").post(f"/api/wordpress/installs/{copy.id}/push")
    assert answer.status_code == 200 and answer.json()["job"]["status"] == "completed", answer.text
    commands = [call["command"] for call in env.calls]
    assert commands.index("wp-point-create") < commands.index("wp-copy")
    copy_call = next(call for call in env.calls if call["command"] == "wp-copy")
    assert copy_call["args"][2] == "keep-config" and copy_call["args"][1] == install.path
    # Only a staging copy is pushed.
    assert env.as_user("alice").post(f"/api/wordpress/installs/{install.id}/push").status_code == 400


def test_a_zip_is_taken_in_and_installed_as_the_account(env, monkeypatch, tmp_path):
    install = _scan(env)
    monkeypatch.setattr("app.api.wordpress_manager.UPLOAD_DIR", tmp_path / "uploads")
    client = env.as_user("alice")
    bad = client.post(f"/api/wordpress/installs/{install.id}/plugins/upload", files={"file": ("x.zip", b"not a zip")})
    assert bad.status_code == 400
    good = client.post(f"/api/wordpress/installs/{install.id}/plugins/upload",
                       files={"file": ("My Plugin.zip", b"PK\x03\x04rest")}, data={"activate": "1"})
    assert good.status_code == 200 and good.json()["job"]["status"] == "completed", good.text
    place = next(call for call in env.calls if call["command"] == "wp-upload-place")
    assert place["user"] == "alice" and place["args"][1] == "My-Plugin.zip"
    install_call = next(call for call in env.calls if call["command"] == "wp-site" and call["args"][:2] == ["plugin", "install"])
    assert install_call["args"][2] == "/home/alice/.bpanel-wp-stage/My-Plugin.zip" and "--activate" in install_call["args"]
    assert not list((tmp_path / "uploads").iterdir())  # the waiting copy is gone


def test_the_daily_check_reads_a_day_old_install_again(env):
    install = _scan(env)
    install.last_checked_at = datetime.utcnow() - timedelta(days=2)
    env.db.commit()
    env.calls.clear()
    assert wp_extras.daily_tick(env.db) == 1
    assert any(call["args"][:2] == ["core", "version"] for call in env.calls if call["command"] == "wp-site")
    assert wp_extras.daily_tick(env.db) == 0


def test_the_helper_copies_as_the_account_and_never_across_accounts():
    body = HELPER.split("  wp-copy)", 1)[1].split(";;", 1)[0]
    assert 'from=$(require_managed_path "$2" "$user")' in body and 'to=$(require_managed_path "$3" "$user")' in body
    assert 'runuser -u "$user" -- rsync' in body and "the two folders overlap" in body
    place = HELPER.split("  wp-upload-place)", 1)[1].split(";;", 1)[0]
    assert "^/var/lib/bpanel/wp-uploads/[a-f0-9]{24}\\.zip$" in place


def test_the_nginx_cache_is_the_website_s_and_a_purge_empties_only_it(env, monkeypatch):
    install = _scan(env)
    import app.api.websites as websites_api
    rewritten = []
    monkeypatch.setattr(websites_api, "_rewrite_website_vhost", lambda website, **kw: rewritten.append(website.nginx_cache_enabled) or "")
    client = env.as_user("alice")
    assert client.post(f"/api/wordpress/installs/{install.id}/nginx-cache", json={"action": "rm -rf"}).status_code == 422
    env.calls.clear()
    answer = client.post(f"/api/wordpress/installs/{install.id}/nginx-cache", json={"action": "purge"})
    assert answer.status_code == 200 and answer.json()["job"]["status"] == "completed", answer.text
    purge = [call for call in env.calls if call["command"] == "fastcgi-cache-purge"]
    assert [call["user"] for call in purge] == ["alice.example"]
    off = client.post(f"/api/wordpress/installs/{install.id}/nginx-cache", json={"action": "off"})
    assert off.json()["job"]["status"] == "completed", off.text
    env.db.refresh(env.sites["alice"])
    assert env.sites["alice"].nginx_cache_enabled is False and rewritten == [False]
    listed = client.get("/api/wordpress").json()["items"][0]
    assert listed["nginx_cache"] is False and listed["app_type"] == "wordpress"


def test_a_website_not_in_wordpress_mode_has_no_nginx_cache_to_switch(env, monkeypatch):
    install = _scan(env)
    env.sites["alice"].app_type = "php"
    env.db.commit()
    answer = env.as_user("alice").post(f"/api/wordpress/installs/{install.id}/nginx-cache", json={"action": "on"})
    assert answer.json()["job"]["status"] == "failed"
    assert "WordPress mode" in answer.json()["job"]["error"]


def test_the_helper_purges_one_website_from_the_cache():
    body = HELPER.split("  fastcgi-cache-purge)", 1)[1].split(";;", 1)[0]
    assert 'require_domain "$domain"' in body
    # The key is "$scheme$request_method$host$request_uri": the host ends at the first slash.
    assert '"^KEY: https?(GET|HEAD)${host_re}/"' in body


def test_a_vhost_without_the_cache_stays_without_it():
    from app.services import nginx

    on = nginx.render_vhost("example.test", "/home/bp_example_test/example.test", app_type="wordpress", php_version="8.3")
    off = nginx.render_vhost("example.test", "/home/bp_example_test/example.test", app_type="wordpress", php_version="8.3",
                             fastcgi_cache=False)
    assert "fastcgi_cache BPANEL_FASTCGI;" in on and nginx.FASTCGI_CACHE_OFF_MARK not in on
    assert "fastcgi_cache BPANEL_FASTCGI;" not in off and "BPANEL FASTCGI CACHE" not in off.replace(nginx.FASTCGI_CACHE_OFF_MARK, "")
    assert nginx.FASTCGI_CACHE_OFF_MARK in off and "fastcgi_pass" in off


def test_the_website_page_switches_and_empties_its_own_cache(env, monkeypatch):
    """The website's Cache tab (operator, 2026-10-19), without the addon."""
    import app.api.websites as websites_api
    rewritten = []
    monkeypatch.setattr(websites_api, "_rewrite_website_vhost", lambda website, **kw: rewritten.append(website.nginx_cache_enabled) or "")
    site = env.sites["alice"]
    client = env.as_user("alice")
    env.calls.clear()
    off = client.put(f"/api/websites/{site.id}/nginx-cache", json={"enabled": False})
    assert off.status_code == 200, off.text
    assert off.json()["nginx_cache_enabled"] is False and rewritten == [False]
    # Turning it off empties what it kept.
    assert [call["user"] for call in env.calls if call["command"] == "fastcgi-cache-purge"] == ["alice.example"]
    assert client.post(f"/api/websites/{site.id}/nginx-cache/purge").json() == {"purged": 0}
    # Another account's website is not reachable.
    assert env.as_user("bob").put(f"/api/websites/{site.id}/nginx-cache", json={"enabled": True}).status_code in (403, 404)
    site.app_type = "php"
    env.db.commit()
    refused = env.as_user("alice").put(f"/api/websites/{site.id}/nginx-cache", json={"enabled": True})
    assert refused.status_code == 400 and "WordPress mode" in refused.json()["detail"]
