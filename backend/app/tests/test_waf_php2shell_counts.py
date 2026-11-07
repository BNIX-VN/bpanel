"""php2shell's field and file counts go only on a PHP without the fix.

WordPress's menu screen posts ~10 multipart fields per menu item; a 50-item
menu (552 fields) was refused by the 400-field rule on an OPanel box (.122,
2026-11-07). The counts stop exploits only on an unpatched PHP, so a patched
site no longer carries them; every other php2shell rule stays on every site.
"""
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import waf

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")
COUNTS = ("id:1003003", "id:1003004")
EVERYWHERE = ("id:1003001", "id:1003002", "id:1003005", "id:1003006", "id:1003007")


@pytest.fixture
def builds(monkeypatch):
    installed = {"8.1": "8.1.34", "8.3": "8.3.36", "8.4": "8.4.26", "8.5": "8.5.12"}
    monkeypatch.setattr(waf, "_php_builds", {})
    monkeypatch.setattr(waf, "php_build", lambda version: installed.get(str(version or ""), ""))
    return installed


@pytest.mark.parametrize("version,fixed", [
    ("8.5", True), ("8.3", True),
    ("8.4", False),            # 8.4.26: one release short of 8.4.27
    ("8.1", False),            # no fixed 8.1 release exists
    ("7.4", False), (None, False),
])
def test_which_php_has_the_fix(builds, version, fixed):
    assert waf.php2shell_fixed(version) is fixed


def test_a_patched_site_has_no_field_or_file_count(builds):
    content = waf.render_site_rules("menu.test", ["php2shell"], php_version="8.5")
    assert not any(rule_id in content for rule_id in COUNTS)
    assert all(rule_id in content for rule_id in EVERYWHERE)


@pytest.mark.parametrize("version", ["8.1", "8.4", None])
def test_an_unpatched_or_unknown_php_keeps_them(builds, version):
    content = waf.render_site_rules("menu.test", ["php2shell"], php_version=version)
    assert all(rule_id in content for rule_id in COUNTS + EVERYWHERE)


def _site():
    return SimpleNamespace(domain="menu.test", php_version="8.3", waf_default_rules='["php2shell"]',
                           waf_custom_rules="", waf_enabled=True, crs_enabled=False)


def test_a_website_is_rendered_with_its_own_php(monkeypatch):
    seen = []
    monkeypatch.setattr(waf, "sync_site_rules", lambda domain, ids, custom, **kw: seen.append(kw))
    waf.sync_website_rules(_site())
    waf.save_website_config(_site(), ["php2shell"], "")
    assert [kw["php_version"] for kw in seen] == ["8.3", "8.3"]


def test_switching_crs_renders_each_site_with_its_own_php():
    assert 'php_version=getattr(website, "php_version", None)' in inspect.getsource(waf.set_crs_mode)


def test_the_build_is_read_from_the_sites_own_php_without_its_ini():
    source = inspect.getsource(waf.php_build)
    assert '"-n", "-r", "echo PHP_VERSION;"' in source and 'f"/usr/bin/php{key}"' in source


def test_every_update_re_renders_each_sites_rules():
    # BPanel's updater already rewrites every site's WAF file on each update,
    # so a rule change - or a PHP release that now has the fix - reaches
    # existing sites without a separate pass.
    assert "result = waf.sync_website_rules(website)" in UPDATE
