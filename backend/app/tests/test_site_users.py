import hashlib
from pathlib import Path

import pytest

from app.api import websites
from app.services import site_users


def test_site_php_fpm_socket_is_scoped_to_site_root(tmp_path):
    first_root = tmp_path / "first.test"
    second_root = tmp_path / "second.test"

    first_socket = site_users.site_php_fpm_socket("siteuser", first_root, "8.3")
    second_socket = site_users.site_php_fpm_socket("siteuser", second_root, "8.3")

    first_hash = hashlib.sha256(str(first_root.resolve()).encode("utf-8")).hexdigest()[:12]
    assert first_socket == f"/run/php/bpanel-siteuser-{first_hash}-8_3.sock"
    assert second_socket != first_socket


def test_site_php_fpm_socket_returns_none_without_php_version(tmp_path):
    assert site_users.site_php_fpm_socket("siteuser", tmp_path, None) is None


def test_php_fpm_socket_rejects_invalid_php_version(tmp_path):
    with pytest.raises(ValueError, match="Invalid PHP version"):
        site_users.site_php_fpm_socket("siteuser", tmp_path, "../8.3")


def test_legacy_user_php_fpm_socket_is_kept_for_callers_without_site_root():
    assert site_users.php_fpm_socket("siteuser", "8.3") == "/run/php/bpanel-siteuser-8_3.sock"


def test_placeholder_page_for_linux_user_uses_site_file_write(tmp_path, monkeypatch):
    root = tmp_path / "site"
    public = root / "public_html"
    public.mkdir(parents=True)
    calls = []

    def fake_privileged(helper_command, helper_args=None, **kwargs):
        calls.append((helper_command, helper_args, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(websites.file_manager.shell, "privileged", fake_privileged)
    monkeypatch.setattr(websites.file_manager, "_clear_fastcgi_cache", lambda: None)

    websites._write_placeholder_page("example.test", str(root), "siteuser", "8.3")

    assert calls[0][0] == "site-file-write"
    assert calls[0][1] == ["siteuser", str(root.resolve()), "public_html/index.html"]
    assert "example.test" in calls[0][2]["input"]
