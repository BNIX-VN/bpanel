"""The helper and the installers must agree with app/services/webserver.py
about which web server is active, and must not run nginx-only steps on an
OpenLiteSpeed box. These are text assertions on the shell scripts - the only
way to check them without a live server of each kind.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELPER = (PROJECT_ROOT / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")
INSTALL = (PROJECT_ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
UPDATE = (PROJECT_ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def test_every_layer_resolves_the_web_server_the_same_way():
    """webserver.py accepts nginx/openlitespeed/ols/litespeed and falls back to
    nginx for anything else. The shell side has to match, or the panel and the
    helper end up writing to two different web servers' config trees."""
    for script, name in ((HELPER, "bpanel-helper.sh"), (UPDATE, "update.sh")):
        assert "web_server() {" in script, f"{name} has no web_server()"
        assert "openlitespeed|ols|litespeed) echo \"openlitespeed\"" in script, f"{name} aliases differ"
        assert "*) echo \"nginx\"" in script, f"{name} has no nginx fallback"


def test_the_installer_offers_both_web_servers_and_records_the_choice():
    assert "ask_web_server() {" in INSTALL
    assert "openlitespeed|ols|litespeed) WEB_SERVER=\"openlitespeed\"" in INSTALL
    # The choice has to reach .env or nothing downstream can dispatch on it.
    assert "WEB_SERVER=${WEB_SERVER}" in INSTALL
    assert "install_openlitespeed() {" in INSTALL
    assert "install_lsphp_config() {" in INSTALL


def test_nginx_only_install_steps_are_skipped_on_openlitespeed():
    """FastCGI cache, the WebSocket upgrade map and the nginx ModSecurity
    module have no meaning on OLS - running them would fail the install."""
    assert 'if [[ "$WEB_SERVER" == "openlitespeed" ]]; then' in INSTALL
    assert "setup_openlitespeed() {" in INSTALL
    assert "setup_web_server() {" in INSTALL
    # update.sh guards the same three.
    assert "is_openlitespeed; then" in UPDATE
    assert "skipping the Nginx FastCGI cache and upgrade map" in UPDATE


def test_the_helper_exposes_the_ols_verbs_openlitespeed_py_calls():
    """openlitespeed.py shells out to these by name; a missing verb fails only
    at runtime, the first time somebody saves a website."""
    for verb in ("ols-vhost-write", "ols-vhost-delete", "ols-sync-main", "ols-reload"):
        assert f"{verb})" in HELPER or f"{verb}|" in HELPER, f"helper is missing verb {verb}"


def test_php_fpm_pools_are_not_created_on_openlitespeed():
    """There is no /etc/php/<ver>/fpm tree on an OLS box - LSPHP is one shared
    listener per version, so a per-site pool file would both fail to write and
    mean nothing."""
    assert 'if [[ "$(web_server)" == "openlitespeed" ]]; then\n    return 0\n  fi' in HELPER


def test_the_panel_sandbox_only_opens_the_active_web_servers_config_tree():
    assert 'WEB_SERVER_RW_PATHS="/usr/local/lsws/conf/bpanel"' in INSTALL
    assert 'WEB_SERVER_RW_PATHS="/etc/nginx/conf.d /etc/nginx/bpanel/custom"' in INSTALL
    assert 'web_server_rw_paths="/usr/local/lsws/conf/bpanel"' in UPDATE


def test_certbot_skips_the_nginx_plugin_on_openlitespeed():
    """OLS has no certbot plugin. `certbot install --nginx` there would either
    fail or, worse, edit an nginx config that is not serving anything."""
    assert 'if [[ "$(web_server)" == "openlitespeed" ]]; then\n      # OLS has no certbot plugin' in HELPER
    assert "install_args=(install --nginx" in HELPER
