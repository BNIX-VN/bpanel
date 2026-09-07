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


def test_the_ols_config_tree_is_created_before_the_systemd_unit_is_written():
    """systemd refuses to start a unit whose ReadWritePaths names a directory
    that does not exist ("Failed to set up mount namespacing", 226/NAMESPACE).
    setup_openlitespeed creates that tree, but it runs long after
    setup_systemd - so install_openlitespeed has to create it first, or the
    panel crashloops through the rest of the install.
    """
    assert "install -d -o root -g root -m 0755 \\\n    /usr/local/lsws/conf/bpanel \\" in INSTALL
    create_at = INSTALL.index("/usr/local/lsws/conf/bpanel \\")
    unit_at = INSTALL.index('WEB_SERVER_RW_PATHS="/usr/local/lsws/conf/bpanel"')
    assert create_at < unit_at, "the OLS config tree must be created before setup_systemd"


def test_waf_rules_are_written_where_the_running_server_reads_them():
    """The panel picks the rules path, the helper writes the file, and the
    vhost template points at it - all three have to land on the same
    directory. When they did not, every site creation on OLS failed with
    "nginx: command not found" from a WAF verb that assumed nginx.
    """
    from app.services import openlitespeed as ols, waf

    assert "modsec_dir() {" in HELPER
    # No WAF path may be hardcoded any more; only the constant may name one.
    hardcoded = [
        line for line in HELPER.splitlines()
        if "/etc/nginx/modsec" in line and not line.startswith("NGINX_MODSEC_DIR=")
    ]
    assert not hardcoded, f"hardcoded modsec paths left in the helper: {hardcoded}"
    # The helper must not shell out to nginx to validate on an OLS box.
    assert "webserver_test_config() {" in HELPER
    assert "deny \"Web server rejected WAF site rules\"" in HELPER
    # Panel side and vhost side agree on the OLS location.
    assert ols.waf_rules_file("example.test") == "/usr/local/lsws/conf/bpanel/waf/sites/example.test.conf"
    assert waf.modsec_dir() in ("/etc/nginx/modsec", "/usr/local/lsws/conf/bpanel/waf")


def test_certbot_skips_the_nginx_plugin_on_openlitespeed():
    """OLS has no certbot plugin. `certbot install --nginx` there would either
    fail or, worse, edit an nginx config that is not serving anything."""
    assert 'if [[ "$(web_server)" == "openlitespeed" ]]; then\n      # OLS has no certbot plugin' in HELPER
    assert "install_args=(install --nginx" in HELPER


def test_the_update_site_refresh_goes_through_the_dispatcher():
    """update.sh re-renders every vhost from an embedded Python block. It
    lives inside a shell heredoc, so the Milestone 1 sweep of `import nginx`
    call sites missed it - and on OpenLiteSpeed every site's refresh failed
    with "exec: nginx: not found".
    """
    assert "from app.services import site_users, waf, webserver" in UPDATE
    assert "webserver.rewrite_vhost(" in UPDATE
    assert "webserver.sync_http_flood_zones(websites)" in UPDATE
    assert "nginx.rewrite_vhost(" not in UPDATE
    assert "nginx.sync_http_flood_zones(" not in UPDATE


def test_http_flood_zone_sync_is_a_no_op_on_openlitespeed():
    """The shared limit_req_zone file is an nginx concept; OLS renders its
    throttling per vhost. Without this the verb ran `nginx -t` on a box with
    no nginx and every update printed a warning."""
    assert 'if [[ "$(web_server)" == "openlitespeed" ]]; then\n    cat >/dev/null' in HELPER


def test_the_stock_openlitespeed_example_vhost_is_removed():
    """OLS ships an "Example" vhost mapped to "*", so any hostname the panel
    does not map reaches LiteSpeed's demo page. The nginx installer removes
    its own default site for exactly this reason."""
    assert 'remove_named_block(text, "virtualHost", "Example")' in HELPER


APP_JSX = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def test_the_panel_reports_which_web_server_is_running():
    """The choice is made once at install time and never changes, but the UI
    has to say which one it is - the labels, the service list and the log
    locations all differ."""
    from app.schemas.schemas import PanelSettingsOut

    assert "web_server" in PanelSettingsOut.model_fields
    settings_src = (PROJECT_ROOT / "backend" / "app" / "services" / "panel_settings.py").read_text(encoding="utf-8")
    assert '"web_server": webserver.active_name()' in settings_src


def test_the_ui_labels_follow_the_active_web_server():
    """Hardcoded "Nginx" in front of an OpenLiteSpeed customer is simply
    wrong. Internal identifiers, CSS classes and API paths keep their names -
    only what a customer reads is switched."""
    assert "const webServerLabel = " in APP_JSX
    assert "const wsLabel = webServerLabel(webServer)" in APP_JSX
    # The Services page must not list php-fpm/nginx units on an OLS box.
    assert "const OLS_SERVICE_NAMES = ['bpanel-api', 'lshttpd'" in APP_JSX
    assert "setServiceNames(serviceNamesFor(webServer))" in APP_JSX

    # No user-visible "Nginx" left: quoted strings and JSX text nodes only.
    import re
    leftovers = []
    for line in APP_JSX.splitlines():
        if "Nginx" not in line:
            continue
        for m in re.finditer(r"'([^']*Nginx[^']*)'|>([^<>{]*Nginx[^<>{]*)<", line):
            text = m.group(1) or m.group(2)
            # The label helper itself is allowed to contain the word.
            if "webServerLabel" in line:
                continue
            leftovers.append(text.strip())
    assert not leftovers, f"hardcoded Nginx still shown to users: {leftovers}"


def test_features_nginx_only_are_hidden_on_openlitespeed():
    """A control that does nothing is worse than an absent one. HTTP flood
    has no OLS implementation (no request-rate limiter exists there), and the
    Application/proxy website type is nginx-only - the UI must not offer
    either on an OLS server."""
    assert "wafSiteConfig && !isOpenLiteSpeed(webServer) && <section" in APP_JSX, \
        "the HTTP flood panel is still shown on OpenLiteSpeed"
    # Both website-type pickers must refuse "application" on OLS.
    assert APP_JSX.count(
        "disabled={value === 'application' && (!appsFeatureEnabled || isOpenLiteSpeed(webServer))}"
    ) == 2, "an app-type picker still offers Application on OpenLiteSpeed"


def test_the_services_page_lists_the_web_server_that_is_actually_running():
    """Only one web server exists on a given box. Listing the other shows a
    unit that can never report a status and hides the one serving the sites -
    the Services page showed "nginx ..." on an OpenLiteSpeed server and no
    lshttpd at all, which a browser check caught and no text assertion would
    have.
    """
    from app.core.config import settings
    from app.services import system

    original = settings.web_server
    try:
        settings.web_server = "openlitespeed"
        ols = system.list_services()
        assert "lshttpd" in ols and "nginx" not in ols
        # LSPHP runs inside lshttpd; there is no php-fpm unit to restart.
        assert not [s for s in ols if s.endswith("-fpm")]

        settings.web_server = "nginx"
        ngx = system.list_services()
        assert "nginx" in ngx and "lshttpd" not in ngx
    finally:
        settings.web_server = original


def test_php_versions_are_detected_where_the_active_web_server_keeps_them():
    """nginx runs PHP-FPM from /etc/php/<ver>/fpm; OpenLiteSpeed runs LSPHP
    from /usr/local/lsws/lsphp<ver> and has no /etc/php tree. Checking only
    the FPM path left the PHP-version dropdown empty on an OLS server, so a
    website could not be created with a version at all - caught by opening
    the page, not by any assertion on source text.
    """
    from app.core.config import settings
    from app.services import php

    original = settings.web_server
    try:
        settings.web_server = "openlitespeed"
        assert str(php._php_install_marker("8.4")).replace("\\", "/") == \
            "/usr/local/lsws/lsphp84/bin/lsphp"
        settings.web_server = "nginx"
        assert str(php._php_install_marker("8.4")).replace("\\", "/") == \
            "/etc/php/8.4/fpm/php-fpm.conf"
    finally:
        settings.web_server = original
