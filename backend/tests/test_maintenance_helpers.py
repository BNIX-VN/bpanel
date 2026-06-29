import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("COMMAND_DRY_RUN", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

from app.models.entities import Website  # noqa: E402
from app.services import cron, firewall, nginx, waf  # noqa: E402


def test_cron_line_parser_strips_bpanel_wrapper():
    item = cron._parse_cron_line(0, "*/15 * * * * cd /home/admin/example.com/public_html && wp cron event run --due-now --allow-root # bpanel:example.com")  # noqa: SLF001

    assert item["index"] == 0
    assert item["schedule"] == "*/15 * * * *"
    assert item["command"] == "wp cron event run --due-now"


def test_cron_user_for_website_uses_site_owner_from_home_path():
    website = Website(domain="example.com", root_path="/home/client/example.com", linux_user="")

    assert cron.cron_user_for_website(website) == "client"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "php -q /home/minhhien/minhhien.vn/public_html/sieunhim/cron.php profile=default",
            "php -q /home/minhhien/minhhien.vn/public_html/sieunhim/cron.php profile=default",
        ),
        (
            "php -q /home/minhhien/minhhien.vn/public_html/queue.php",
            "php -q /home/minhhien/minhhien.vn/public_html/queue.php",
        ),
    ],
)
def test_cron_command_allows_php_scripts_inside_document_root(command, expected):
    result = cron._validate_command(command, "/home/minhhien/minhhien.vn/public_html")  # noqa: SLF001

    assert result == expected


@pytest.mark.parametrize(
    "command",
    [
        "php -r 'echo 1;'",
        "php /home/minhhien/minhhien.vn/private.php",
        "php /home/minhhien/minhhien.vn/public_html/../private.php",
        "php /home/minhhien/minhhien.vn/public_html/readme.txt",
    ],
)
def test_cron_command_rejects_unsafe_php_commands(command):
    with pytest.raises(ValueError):
        cron._validate_command(command, "/home/minhhien/minhhien.vn/public_html")  # noqa: SLF001


def test_cron_command_keeps_wp_cli_allow_root_behavior():
    result = cron._validate_command("wp cron event run --due-now", "/home/client/example.com/public_html")  # noqa: SLF001

    assert result == "wp cron event run --due-now --allow-root"


def test_waf_site_rules_render_selected_defaults_and_custom_rules():
    content = waf.render_site_rules(
        "example.com",
        ["general-sensitive-files", "wordpress-sensitive-files"],
        "SecRule REQUEST_URI \"@streq /private\" \"id:1001999,phase:1,deny,status:403\"",
    )

    assert "Include /etc/nginx/modsec/bpanel-base.conf" in content
    assert "general-sensitive-files" in content
    assert "wordpress-sensitive-files" in content
    assert "general-path-traversal" not in content
    assert "id:1001999" in content


def test_http_flood_zones_render_only_enabled_sites():
    enabled = Website(
        domain="example.com",
        root_path="/home/client/example.com",
        http_flood_enabled=True,
        http_flood_config='{"access_limit_requests":30,"access_limit_window":60,"access_limit_burst":12,"connection_limit":20}',
    )
    disabled = Website(domain="disabled.com", root_path="/home/client/disabled.com", http_flood_enabled=False)

    content = nginx.render_http_flood_zones([enabled, disabled])

    assert "map $cookie_bpanel_http_flood_ok $bpanel_http_flood_key" in content
    assert "limit_conn_zone $bpanel_http_flood_key zone=bpanel_conn_flood:10m;" in content
    assert f"zone={nginx.http_flood_zone_name('example.com')}:10m rate=30r/m;" in content
    assert nginx.http_flood_zone_name("disabled.com") not in content


def test_render_vhost_keeps_waf_and_http_flood_blocks():
    content = nginx.render_vhost(
        "example.com",
        "/home/client/example.com",
        app_type="php",
        php_version="8.3",
        document_root="public_html/public",
        waf_enabled=True,
        http_flood_enabled=True,
        http_flood_config={"access_limit_requests":120, "access_limit_window":10, "access_limit_burst":20, "connection_limit":8},
    )

    assert "# BPANEL WAF BEGIN" in content
    assert "# BPANEL HTTP FLOOD BEGIN" in content
    assert f"limit_req zone={nginx.http_flood_zone_name('example.com')} burst=20;" in content
    assert "limit_conn bpanel_conn_flood 8;" in content
    assert "@bpanel_http_flood_challenge" in content
    assert "bpanel_http_flood_ok=1" in content
    assert "# BPANEL ACME CHALLENGE" in content
    assert "root /var/www/bpanel-acme;" in content
    expected_root = Path("/home/client/example.com").resolve() / "public_html" / "public"
    assert f"root {expected_root};" in content


def test_wordpress_cache_revalidates_quickly():
    content = nginx.render_vhost(
        "example.com",
        "/home/client/example.com",
        app_type="wordpress",
        php_version="8.3",
    )

    assert 'if ($http_cache_control ~* "no-cache|no-store|max-age=0")' in content
    assert 'if ($http_pragma = "no-cache")' in content
    assert "fastcgi_cache_valid 200 15s;" in content
    assert "fastcgi_cache_valid 200 301 302 10m;" not in content
    assert "fastcgi_cache_use_stale" not in content
    assert "expires -1;" in content
    assert 'Cache-Control "public, immutable"' not in content


def test_set_php_version_preserves_existing_vhost(tmp_path, monkeypatch):
    target = tmp_path / "example.com.conf"
    existing = """server {
    server_name example.com;
    # BPANEL REVERSE PROXY BEGIN
    real_ip_header X-Forwarded-For;
    # BPANEL REVERSE PROXY END
    location ~ \\.php$ {
        fastcgi_pass unix:/run/php/bpanel-client-8_3.sock;
    }
}
"""
    target.write_text(existing, encoding="utf-8")
    monkeypatch.setattr(nginx.settings, "command_dry_run", False)
    monkeypatch.setattr(nginx, "_vhost_path", lambda _domain: target)
    monkeypatch.setattr(nginx, "_test_and_reload", lambda _target, _old: None)

    nginx.set_php_version("example.com", "8.1", "/run/php/bpanel-client-8_1.sock")

    updated = target.read_text(encoding="utf-8")
    assert "# BPANEL REVERSE PROXY BEGIN" in updated
    assert "fastcgi_pass unix:/run/php/bpanel-client-8_1.sock;" in updated
    assert target.with_suffix(".conf.bak").read_text(encoding="utf-8") == existing


def test_write_backup_replaces_existing_backup(tmp_path):
    target = tmp_path / "example.com.conf"
    target.write_text("current", encoding="utf-8")
    backup = target.with_suffix(".conf.bak")
    backup.write_text("old backup", encoding="utf-8")

    nginx._write_backup(target, "new backup")

    assert backup.read_text(encoding="utf-8") == "new backup"


def test_firewall_numbered_rules_mark_defaults_protected(monkeypatch):
    monkeypatch.setattr(firewall.settings, "panel_port", 2222)

    rules = firewall.parse_numbered_rules(
        "[ 1] 22/tcp                     ALLOW IN    Anywhere\n"
        "[ 2] 2222/tcp                   ALLOW IN    Anywhere\n"
        "[ 3] 465/tcp                    ALLOW IN    Anywhere\n"
        "[ 4] 443/tcp                    DENY IN     Anywhere\n"
        "[ 5] 5.6.7.8                    DENY IN     Anywhere # bpanel:UserZone\n"
        "[ 6] 80/tcp                     ALLOW IN    Anywhere # bpanel:UserZone\n"
        "[ 7] Anywhere                   DENY IN     10.0.0.0/8 # bpanel:UserZone:blocklist"
    )

    assert [rule["id"] for rule in rules] == [1, 2, 3, 4, 5, 6, 7]
    assert rules[0]["protected"] is True
    assert rules[1]["protected"] is True
    assert rules[2]["protected"] is True
    assert rules[3]["protected"] is False
    assert rules[4]["protected"] is False
    assert rules[5]["protected"] is False
    assert rules[6]["protected"] is False
    assert rules[0]["zone"] == "PanelZone"
    assert rules[4]["zone"] == "UserZone"
    assert rules[4]["from"] == "Anywhere"
    assert rules[6]["from"] == "10.0.0.0/8"
