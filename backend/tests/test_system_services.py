import os
import sys
from types import SimpleNamespace

import pytest

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("COMMAND_DRY_RUN", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

from app.services import system  # noqa: E402


def test_list_services_includes_installed_php_versions_in_display_order(tmp_path, monkeypatch):
    for version in ["8.5", "7.4", "8.1"]:
        conf_dir = tmp_path / version / "fpm"
        conf_dir.mkdir(parents=True)
        (conf_dir / "php-fpm.conf").write_text("[global]\n", encoding="utf-8")
    (tmp_path / "8.2" / "cli").mkdir(parents=True)

    monkeypatch.setattr(system, "PHP_ETC_DIR", tmp_path)

    assert system.list_services() == [
        "bpanel-api",
        "nginx",
        "php7.4-fpm",
        "php8.1-fpm",
        "php8.5-fpm",
        "mariadb",
        "redis-server",
    ]


def test_service_action_allows_dynamic_php_service(tmp_path, monkeypatch):
    conf_dir = tmp_path / "8.2" / "fpm"
    conf_dir.mkdir(parents=True)
    (conf_dir / "php-fpm.conf").write_text("[global]\n", encoding="utf-8")
    captured = {}

    def fake_run(command, check=False):
        captured["command"] = command
        captured["check"] = check
        return SimpleNamespace(stdout="active (running)", stderr="", returncode=0)

    monkeypatch.setattr(system, "PHP_ETC_DIR", tmp_path)
    monkeypatch.setattr(system.shell, "run", fake_run)

    result = system.service_action("php8.2-fpm", "status")

    assert result.stdout == "active (running)"
    assert captured == {"command": ["systemctl", "status", "php8.2-fpm"], "check": False}


def test_service_action_rejects_uninstalled_php_service(tmp_path, monkeypatch):
    monkeypatch.setattr(system, "PHP_ETC_DIR", tmp_path)

    with pytest.raises(ValueError, match="Unsupported service"):
        system.service_action("php8.2-fpm", "status")
