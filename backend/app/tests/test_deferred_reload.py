"""Rewriting every vhost on a server without testing the config N times.

nginx re-parses everything on each `nginx -t`, ModSecurity rules included.
With CRS enabled and 22 sites that is 22 parses of 18,503 rules in one update,
which is what ran a swapless 8 GB server out of memory and took nginx down
partway through. These pin the batching, and - more importantly - that
batching did not cost the rollback that made the per-site path safe.
"""

import pytest

from app.services import nginx


class FakeResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_privileged(verb, *a, **k):
        seen.append(verb)
        if verb == "nginx-test":
            return FakeResult(fake_privileged.test_rc, fake_privileged.test_err)
        return FakeResult(0)

    fake_privileged.test_rc = 0
    fake_privileged.test_err = ""
    monkeypatch.setattr(nginx.shell, "privileged", fake_privileged)
    return seen, fake_privileged


def _write(tmp_path, name, text, old=None):
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    nginx._test_and_reload(target, old)
    return target


def test_each_write_tests_and_reloads_on_its_own_by_default(tmp_path, calls):
    seen, _ = calls

    for i in range(3):
        _write(tmp_path, f"s{i}.conf", "new")

    assert seen.count("nginx-test") == 3
    assert seen.count("nginx-reload") == 3


def test_a_batch_tests_and_reloads_once(tmp_path, calls):
    seen, _ = calls

    with nginx.deferred_reload():
        for i in range(22):
            _write(tmp_path, f"s{i}.conf", "new")
        assert "nginx-test" not in seen, "nothing may be tested inside the batch"

    assert seen.count("nginx-test") == 1
    assert seen.count("nginx-reload") == 1


def test_a_failing_batch_puts_every_file_back_and_never_reloads(tmp_path, calls):
    seen, fake = calls
    for i in range(3):
        (tmp_path / f"s{i}.conf").write_text(f"old {i}", encoding="utf-8")
    fake.test_rc = 1
    fake.test_err = "invalid value"

    with pytest.raises(RuntimeError, match="invalid value"):
        with nginx.deferred_reload():
            for i in range(3):
                _write(tmp_path, f"s{i}.conf", "new", old=f"old {i}")

    for i in range(3):
        assert (tmp_path / f"s{i}.conf").read_text(encoding="utf-8") == f"old {i}"
    assert "nginx-reload" not in seen, "a config that fails the test must not be loaded"


def test_a_file_that_did_not_exist_before_is_removed_again(tmp_path, calls):
    seen, fake = calls
    fake.test_rc = 1

    with pytest.raises(RuntimeError):
        with nginx.deferred_reload():
            _write(tmp_path, "new-site.conf", "new", old=None)

    assert not (tmp_path / "new-site.conf").exists()


def test_the_body_raising_also_rolls_back(tmp_path, calls):
    seen, _ = calls
    (tmp_path / "s.conf").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError):
        with nginx.deferred_reload():
            _write(tmp_path, "s.conf", "new", old="old")
            raise ValueError("render failed halfway")

    assert (tmp_path / "s.conf").read_text(encoding="utf-8") == "old"
    assert "nginx-test" not in seen and "nginx-reload" not in seen


def test_nesting_leaves_the_reload_to_the_outermost_block(tmp_path, calls):
    seen, _ = calls

    with nginx.deferred_reload():
        _write(tmp_path, "a.conf", "new")
        with nginx.deferred_reload():
            _write(tmp_path, "b.conf", "new")
        assert "nginx-test" not in seen

    assert seen.count("nginx-test") == 1


def test_the_batch_flag_is_cleared_even_when_it_fails(tmp_path, calls):
    """Otherwise every later write in the process silently stops reloading."""
    seen, fake = calls
    fake.test_rc = 1

    with pytest.raises(RuntimeError):
        with nginx.deferred_reload():
            _write(tmp_path, "s.conf", "new", old=None)

    assert nginx._DEFERRED_WRITES is None
    fake.test_rc = 0
    _write(tmp_path, "after.conf", "new")
    assert seen.count("nginx-reload") == 1


def test_the_updater_actually_uses_it():
    """The fix is only real if update.sh's per-site loop is inside the block."""
    from pathlib import Path

    update = (Path(__file__).resolve().parents[3] / "installer" / "update.sh").read_text(
        encoding="utf-8", errors="replace"
    )

    assert "with nginx.deferred_reload():" in update
    block = update.split("with nginx.deferred_reload():", 1)[1].split("\nPY\n", 1)[0]
    assert "websites_api._rewrite_website_vhost(website)" in block


def test_the_updater_rebuilds_a_vhost_the_way_the_panel_does():
    """Aliases, redirect domains and an application's port included.

    The refresh used to call nginx.rewrite_vhost with none of them: every
    update dropped crm.media.io.vn's redirect on .88, and refused reviewthammy.vn
    on .120 because it fronts an application (2026-10-02).
    """
    from pathlib import Path

    update = (Path(__file__).resolve().parents[3] / "installer" / "update.sh").read_text(
        encoding="utf-8", errors="replace"
    )
    refresh = update.split('log "Refreshing managed site configuration"', 1)[1].split("\nPY\n", 1)[0]
    assert "from app.api import websites as websites_api" in refresh
    assert "nginx.rewrite_vhost(" not in refresh
    # Under a new step name, so servers already up to date run it once.
    assert "SITE_REFRESH_STEP=site-refresh-2" in update
    assert '"$SOURCE_DIR/backend/app/api/websites.py"' in update.split("SITE_REFRESH_INPUTS=(", 1)[1].split(")", 1)[0]


def test_the_panels_rebuild_carries_aliases_redirects_and_the_app_port(monkeypatch):
    from types import SimpleNamespace

    from app.api import websites as websites_api

    seen = {}
    monkeypatch.setattr(websites_api.nginx, "rewrite_vhost",
                        lambda domain, root_path, **kwargs: seen.update(kwargs) or "ok")
    monkeypatch.setattr(websites_api, "_alias_domains", lambda website: ["alias.test"])
    monkeypatch.setattr(websites_api, "_redirect_domains", lambda website: ["old.test"])
    monkeypatch.setattr(websites_api.site_apps, "app_port_for_website", lambda website: 21000)
    site = SimpleNamespace(domain="reviewthammy.vn", root_path="/home/wow/reviewthammy.vn", linux_user="wow",
                           app_type="node", php_version=None, nginx_custom="", waf_enabled=True,
                           http_flood_enabled=False, http_flood_config="", document_root="public_html",
                           nginx_rewrite_mode="none", ssl_mode="letsencrypt")
    websites_api._rewrite_website_vhost(site)
    assert seen["aliases"] == ["alias.test"] and seen["redirects"] == ["old.test"]
    assert seen["app_port"] == 21000


# --- the global bad-bot list --------------------------------------------------

@pytest.fixture
def vhosts(tmp_path, monkeypatch):
    from app.services import waf

    monkeypatch.setattr(nginx.settings, "command_dry_run", False)
    monkeypatch.setattr(nginx, "_vhost_path", lambda domain: tmp_path / f"{domain}.conf")
    monkeypatch.setattr(waf, "effective_blocked_bots", lambda site: ["BadBot"])
    sites = []
    for i in range(23):
        domain = f"site{i}.test"
        (tmp_path / f"{domain}.conf").write_text("server {\n    server_name %s;\n}\n" % domain, encoding="utf-8")
        sites.append(type("Site", (), {"domain": domain})())
    return tmp_path, sites


def test_saving_the_global_bot_list_tests_nginx_once(vhosts, calls):
    """23 sites used to mean 23 tests and 23 reloads - minutes of "Saving
    global bad bots..." on a server with CRS on."""
    from app.services import waf

    tmp_path, sites = vhosts
    seen, _ = calls
    done, failed = waf.resync_bot_blocks(sites)
    assert len(done) == 23 and not failed
    assert seen.count("nginx-test") == 1 and seen.count("nginx-reload") == 1
    assert "BadBot" in (tmp_path / "site7.test.conf").read_text(encoding="utf-8")


def test_a_refused_bot_list_puts_every_vhost_back(vhosts, calls):
    from app.services import waf

    tmp_path, sites = vhosts
    seen, fake = calls
    fake.test_rc = 1
    fake.test_err = "unknown directive"
    with pytest.raises(RuntimeError):
        waf.resync_bot_blocks(sites)
    assert "BadBot" not in (tmp_path / "site7.test.conf").read_text(encoding="utf-8")
    assert "nginx-reload" not in seen


def test_the_endpoint_restores_the_stored_list_when_nginx_refuses():
    from pathlib import Path

    api = (Path(__file__).resolve().parents[1] / "api" / "waf.py").read_text(encoding="utf-8")
    body = api.split("def save_global_bots(", 1)[1].split("\n@router", 1)[0]
    assert "previous = panel_settings.global_blocked_bots()" in body
    assert 'panel_settings.save_global_blocked_bots("\\n".join(previous))' in body
