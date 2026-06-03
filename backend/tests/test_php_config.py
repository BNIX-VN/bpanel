import os
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("COMMAND_DRY_RUN", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ""))

from app.schemas.schemas import PhpConfigUpdate  # noqa: E402
from app.services import php  # noqa: E402


def test_php_config_accepts_all_supported_versions():
    assert PhpConfigUpdate(php_version="8.2").php_version == "8.2"

    with pytest.raises(ValidationError):
        PhpConfigUpdate(php_version="9.9")


def test_supported_php_versions_keep_display_order():
    assert list(php.SUPPORTED_PHP_VERSIONS) == ["5.6", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5"]


def test_update_php_ini_writes_through_helper(monkeypatch):
    captured = {}

    def fake_privileged(helper_command, helper_args=None, input=None, fallback=None, **kwargs):
        captured.update(
            {
                "helper_command": helper_command,
                "helper_args": helper_args,
                "input": input,
                "fallback": fallback,
            }
        )
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(php.settings, "command_dry_run", False)
    monkeypatch.setattr(php.shell, "privileged", fake_privileged)

    target = php.update_php_ini(PhpConfigUpdate(php_version="8.2", memory_limit="768M"))

    assert target.replace("\\", "/") == "/etc/php/8.2/fpm/conf.d/99-bpanel.ini"
    assert captured["helper_command"] == "php-config-write"
    assert captured["helper_args"] == ["8.2"]
    assert "memory_limit = 768M" in captured["input"]
    assert "systemctl restart php$1-fpm" in captured["fallback"][2]


def test_install_php_repairs_existing_version(monkeypatch):
    captured = {}

    def fake_privileged(helper_command, helper_args=None, fallback=None, **kwargs):
        captured.update({"helper_command": helper_command, "helper_args": helper_args, "fallback": fallback})
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(php.settings, "command_dry_run", False)
    monkeypatch.setattr(php.shell, "privileged", fake_privileged)
    monkeypatch.setattr(php.Path, "exists", lambda self: str(self).replace("\\", "/") == "/etc/php/8.3/fpm/php-fpm.conf")

    result = php.install_php("8.3")

    assert result["status"] == "ensured"
    assert result["output"] == "ok"
    assert captured["helper_command"] == "php-install"
    assert captured["helper_args"] == ["8.3"]
    assert "php8.3-intl" in captured["fallback"]
    assert "php8.3-imagick" in captured["fallback"]
