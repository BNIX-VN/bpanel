"""The design decisions that a single careless edit undoes.

None of this is about taste. Each test below is a rule that was broken in the
source before the design pass, that nothing complained about, and that shows up
only as a screen somebody has to look at - which is why it is a test and not a
note in a stylesheet.

They read the CSS and the interface source. The panel has no browser test
runner, and every one of these is a textual fact.
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC = PROJECT_ROOT / "frontend" / "src"
# The look itself is OPanel's shared layer (frontend/src/shared, synced from
# OPanel and checked by test_shared_ui.py); BPanel's own sheet holds only what
# OPanel does not have. Tests of BPanel's former look were dropped on
# 2026-09-29, when the operator chose OPanel's interface as it is.
APP = (SRC / "App.jsx").read_text(encoding="utf-8")


# --- the two dark themes have to stay one theme ------------------------------

# --- type and the mono stack -------------------------------------------------

# --- hierarchy ---------------------------------------------------------------

def test_refresh_is_never_the_loudest_button_on_a_page():
    """Re-reading a list is the one action on any page that cannot go wrong.
    Twenty-three of these were filled brand blue, so on the settings page the
    button that re-reads the form shouted as loud as the one that saves it.
    """
    loud = []
    for match in re.finditer(r"<button([^>]*)>((?:(?!</button>).){0,220}?t\('Refresh'\))", APP, re.S):
        attributes = match.group(1)
        if "className" not in attributes:
            loud.append(match.group(0)[:70])
            continue
        classes = re.search(r'className="([^"]*)"', attributes)
        if classes and "secondary" not in classes.group(1):
            loud.append(match.group(0)[:70])
    assert not loud, f"{len(loud)} primary Refresh buttons: {loud[:3]}"


UI = (SRC / "shared" / "ui.css").read_text(encoding="utf-8")


def _dashboard():
    return APP.split("function renderDashboard()")[1].split("function renderAdminOnly()")[0]


def test_the_dashboard_is_laid_out_as_cpanels_home():
    """cPanel's home page (operator, 2026-10-04, following OPanel: customers
    come from cPanel and DirectAdmin), in SNPanel's shape since 2026-10-18:
    every feature a tile with its picture, in sections that fold, with a
    search; on the right, how things stand. What needs attention is the top
    bar's bell."""
    dashboard = _dashboard()
    assert "featureGroups" not in APP and "function FeatureTile(" not in APP
    assert 'className="dashboard cp-layout"' in dashboard
    assert "dash-resources" not in dashboard
    assert 'className={`status-row tone-${card.tone}`}' in dashboard
    for key in ("services", "ssl", "firewall", "waf", "malware", "backups"):
        assert f"key: '{key}'" in dashboard, key
    bell = (SRC / "components" / "NotificationBell.jsx").read_text(encoding="utf-8")
    assert "t('Needs attention')" in bell
    assert "{t('Statistics')}" in dashboard and "{t('General information')}" in dashboard
    # The tiles (lib/features.jsx): grouped, searchable, and "New website" and
    # "New database" arrive with their form open.
    features = (SRC / "lib" / "features.jsx").read_text(encoding="utf-8")
    assert "before: 'newWebsite'" in features and "before: 'newDatabase'" in features
    assert "newWebsite: () => setCreateFormOpen(true)," in APP and "newDatabase: () => setDbCreateOpen(true)," in APP
    assert "t('Search tools (press /)')" in APP and "normalizeSearch(" in APP


def test_a_customer_is_not_shown_the_server():
    """Server state is an administrator's: the endpoint leaves it out for a
    customer, and what reads it sits in the administrator's branch. Every
    account's use is Server › Account resources, an administrator's page."""
    dashboard = _dashboard()
    services = dashboard.index("status.push({ key: 'services'")
    assert dashboard[:services].rfind("if (isAdmin) {") > dashboard[:services].rfind("} else {")
    admin_page, customer_page = dashboard.split("if (!currentUser) return null;", 1)
    assert "t('Server information')" in admin_page and "t('Server information')" not in customer_page
    assert "if (page === 'account-resources') return isAdmin ? renderAccountResources() : renderDashboard();" in APP
    customer_status = dashboard.split("} else {\n      const wafOn", 1)[1].split("\n    }\n", 1)[0]
    assert "key: 'waf'" in customer_status and "key: 'security'" in customer_status


def test_the_sidebar_holds_what_is_used_every_day():
    """The sidebar holds the everyday pages and the hubs (SNPanel-style shell,
    2026-10-18); a hub's pages are its tabs, and an addon is opened from its
    Dashboard tile, never from the sidebar (operator, 2026-10-18)."""
    navigation = (SRC / "lib" / "navigation.jsx").read_text(encoding="utf-8")
    sidebar = navigation.split("export function sidebarItems(")[1].split("\n}\n")[0]
    keys = re.findall(r"\['([a-z-]+)', ", sidebar)
    # The WordPress Manager is the one addon there, last, while installed
    # (operator, 2026-10-19), as SNPanel has it.
    assert keys == ["wordpress", "dashboard", "websites", "ssl", "databases", "cron", "files", "backups",
                    "users", "server", "security-center", "config", "users"]
    assert "const wordpress = ctx.wordpressAddonInstalled ? [['wordpress'," in sidebar
    assert "      ...wordpress,\n    ];" in sidebar and "return [...common, ...wordpress];" in sidebar
    for addon in ("mail", "dns", "git", "mcp", "applications"):
        assert f"'{addon}'" not in sidebar, addon
    hubs = navigation.split("export const HUBS = [")[1].split("\n];")[0]
    tabs = re.findall(r"\{ page: '([a-z-]+)'", hubs)
    for page in ("processes", "ram-usage", "disk-usage", "traffic", "account-resources", "php", "services", "updates",
                 "firewall", "waf", "access-logs", "malware", "panel-settings", "addons", "notifications"):
        assert page in tabs, page
    # The File manager opens in a tab of its own, SFTP and the terminal from
    # the Dashboard (operator, 2026-10-26): no Files hub.
    for page in ("files", "sftp", "terminal"):
        assert page not in tabs, page
    assert not set(keys) & set(tabs), "a page in both places"


def test_a_settings_page_keeps_its_own_name_and_lights_up_settings():
    """A hub's page keeps its own name, after the hub's, and the hub's entry
    in the sidebar lights up (lib/navigation.jsx sidebarKeyOf)."""
    assert "const activeHub = hubOf(page, navCtx);" in APP
    assert "<button type=\"button\" onClick={() => navigateToPage(activeHub.tabs[0].page)}>{t(activeHub.hub.title)}</button>" in APP
    assert '<span className="page-crumb-current">{pageTitle}</span>' in APP
    navigation = (SRC / "lib" / "navigation.jsx").read_text(encoding="utf-8")
    assert "if (found && keys.has(found.hub.key)) return found.hub.key;" in navigation


def test_panel_settings_is_opanels_tabs():
    """OPanel's page (operator, 2026-09-30: tabs as BPanel had them): General,
    Brand assets, API Tokens, one at a time; the admin's own email and
    password live in Profile."""
    page = APP.split("  function renderPanelSettings() {")[1].split("  function renderUsers() {")[0]
    tabs = re.findall(r"\['([a-z]+)', '([^']+)', \w+\],", page.split("const tabs = [")[1].split("];")[0])
    assert tabs == [("general", "General"), ("brand", "Brand assets"), ("api", "API Tokens")]
    assert 'className="segmented-control backup-tabs" role="tablist"' in page
    for key, _label in tabs:
        assert f"activeTab === '{key}' && <div className=\"backup-tab-panel\"" in page, key
    assert "Admin account" not in page
    # The tokens used to be their own page; an old link still opens their tab.
    assert "/^\\/api-tokens?\\/?$/i.test(window.location.pathname) ? 'api' : 'general'" in APP


def test_sign_out_lives_in_the_account_menu():
    """The top bar is the page title and one account menu, as in OPanel:
    Profile, Account security, Logout."""
    assert 'className="user-menu-panel"' in APP
    menu = APP.split('className="user-menu-panel"')[1].split("</div>}")[0]
    assert menu.index("openProfileModal()") < menu.index("navigateToPage('security')") < menu.index("logout()")
    assert "account-pill" not in APP
    modal = APP.split("{showProfileModal && ")[1].split("{renderNotifications()}")[0]
    assert "saveProfileEmail" in modal and "changeMyPassword" in modal

def test_the_create_website_form_is_not_in_front_of_the_list():
    """Making a site is occasional; finding one is why the page gets opened.
    As in SNPanel the form is a side sheet, closed by its own X, and "New
    website" on the list (or its empty state) opens it; with no website yet
    it is open, the only thing to do - except while a create it sent is
    running: Create closes the sheet at once (operator, 2026-10-22)."""
    assert "const [createFormOpen, setCreateFormOpen] = useState(false);" in APP
    assert "const createOpen = !createPending && (createFormOpen || websites.length === 0);" in APP
    page = APP.split("  function renderWebsites() {")[1].split("  function renderSsl(")[0]
    assert "<Drawer open={createOpen} onClose={websites.length > 0 ? closeCreate : undefined}" in page
    assert "action={{ label: t('New website'), icon: Plus, onClick: openCreate }}" in page


def test_a_label_from_an_array_goes_through_the_dictionary():
    """The same mistake as the headings, five more times.

    A list of [id, label, Icon] rows drawn by one shared line of JSX: the
    labels are ordinary English sentences, but nothing wraps them, so the
    backup tabs, the website-type options, the CRS switch and the chmod presets
    all stayed English while the page around them was Vietnamese. One raw
    {label} in a render site is the whole bug, so that is what this looks for.
    """
    # {t(label)} does not contain "{label}", so a plain search finds exactly
    # the unwrapped ones. Requiring a > in front keeps it to JSX text: it steps
    # over key={label} on an attribute and ${label} inside a template string.
    drawn_raw = {
        APP[match.start():match.end() + 20].split("\n")[0]
        for match in re.finditer(r"(?<=>)\{label\}", APP)
    }
    allowed = {
        # ResourceCard is handed an already-translated string by its caller.
        "{label}</span></div>",
        # So are the dashboard's limit rows (LimitRow), built with t().
        "{label}</span>",
        # And its information rows (InfoRow).
        "{label}</span><strong title",
        # Product and file names: "Claude Code", "Cursor - .cursor/mcp.json".
        "{label}</strong>",
        # Account resources' column headings and a website's log tabs: built
        # with t() in the arrays they come from.
        "{label}",
        "{label}</button>)}",
    }
    unexpected = sorted(text for text in drawn_raw if text not in allowed)
    assert not unexpected, f"labels drawn without t(): {unexpected}"


def test_the_dashboard_headings_are_translated_where_they_are_drawn():
    """Having the words in the dictionary is not the same as using them.

    Every group heading was a key with a Vietnamese translation, and the
    dictionary check passed - while the page drew {group.title} raw. The
    sections' titles and the tiles' names go through t() where drawn, and the
    navigation's titles where the top bar shows them.
    """
    assert ".map(([key, title, keys]) => ({ key, title: t(title)," in APP
    assert "{t(tileLabel(item, ctx))}" in APP
    assert "{t(activeHub.hub.title)}" in APP

# --- the operator's list, 2026-09-25 -----------------------------------------

def test_the_file_list_says_when_each_file_was_changed():
    """The API has sent every entry's mtime all along; nothing drew it. As in
    OPanel the date has a column of its own."""
    files = APP.split("  function renderFiles() {")[1].split("\n  }\n")[0]
    assert '<time className="file-date" title={formatFileTime(item.modified, true)}>{formatFileTime(item.modified)}</time>' in files


def test_permissions_open_in_opanels_dialog_and_keep_what_bpanel_adds():
    """OPanel's permissions dialog (a modal card with the grid, the numeric
    mode and presets), with BPanel's own additions still in it: setgid on
    folders, and the toolbar's Permissions for every selected item at once."""
    dialog = APP.split("  function renderChmodDialog() {")[1].split("\n  }\n")[0]
    assert '<div className="modal-card chmod-card"' in dialog and '<div className="chmod-mode-row">' in dialog
    assert "special: bits.special === 2 ? 0 : 2" in dialog, "setgid on folders"
    files = APP.split("  function renderFiles() {")[1].split("\n  }\n")[0]
    assert "onClick={() => openChmodDialog(selectedItems)}" in files
    assert "chmod-backdrop" not in APP and "file-modified" not in APP


def test_a_scan_from_the_history_opens_its_own_page():
    """Clicking a past run used to unfold its details at the foot of a long page.

    As in OPanel it opens as a sub-page of the scanner, the way back in its
    breadcrumbs; the address it used to have (/malware-scan) shows the scanner.
    """
    malware = APP.split("  function renderMalware() {")[1].split("\n  function ")[0]
    assert "onClick={() => openMalwareScanDetail(job)}" in malware
    assert "if (malwareDetailJob) {" in malware
    assert "breadcrumbs={[{ label: t('Malware scanner'), onClick: () => setMalwareDetailJob(null) }" in malware
    assert "'malware-scan': '/malware-scan'" in APP
    assert "!['malware', 'malware-scan'].includes(page)" in APP


def test_updating_wordpress_asks_first():
    """The card's Update button ran core, plugins and themes at once. As in
    OPanel it opens the WordPress panel, and "Update All" there runs it."""
    page = APP.split("  function renderWebsites() {")[1].split("  function renderSsl(")[0]
    menu = page.split("const siteMenuItems = (site) => [")[1].split("];")[0]
    assert "onClick: () => openWordPressUpdate(site)" in menu and "updateWordPressAll" not in menu
    panel = APP.split("  function renderWordPressPanel(site) {")[1].split("\n  }\n")[0]
    assert "onClick={() => updateWordPressAll(site)}><RefreshCw size={14}/> {t('Update All')}" in panel


def test_a_cron_schedule_is_picked_rather_than_typed():
    """OPanel's schedule picker: a preset dropdown beside the raw expression,
    both always there; typing in the expression switches it to "Custom…".
    The list names each schedule and shows the expression beside it."""
    assert "const CRON_PRESETS = [" in APP
    picker = APP.split("  function renderSchedulePicker(key, value, onChange, inputId) {")[1].split("\n  }\n")[0]
    assert '<div className="schedule-picker cron-schedule">' in picker
    assert "{CRON_PRESETS.map(([expr, label]) => <option key={expr} value={expr}>{t(label)}</option>)}" in picker
    assert "<option value=\"custom\">{t('Custom…')}</option>" in picker
    cron = APP.split("  function renderCron() {")[1].split("\n  }\n")[0]
    assert "renderSchedulePicker('cron', cronSchedule, setCronSchedule, 'cron-schedule-input')" in cron
    assert '<code className="cron-item-expr">{item.schedule}</code>' in cron


def test_a_new_page_opens_at_its_top():
    """The window scrolls, and nothing reset it on a page change: the next page
    opened at the last one's offset, part-way down or in empty space. Instant,
    because html{scroll-behavior:smooth} would otherwise slide it there."""
    effect = APP.split("useLayoutEffect(() => {", 1)[1].split("}, [page]);", 1)[0]
    assert "window.scrollTo({ top: 0, left: 0, behavior: 'instant' })" in effect
    assert "window.history.scrollRestoration = 'manual'" in APP


def test_no_function_in_the_app_is_declared_twice():
    """A second `function renderNotifications()` - the Notifications page -
    silently replaced the toast renderer of the same name: every toast in the
    panel drew the Notifications page instead, and nothing failed. Inside one
    component the later declaration simply wins."""
    names = re.findall(r"^  (?:async )?function (\w+)\(", APP, flags=re.M)
    duplicated = sorted({name for name in names if names.count(name) > 1})
    assert not duplicated, f"declared more than once: {duplicated}"


def test_the_updates_page_prints_no_stray_zero():
    """A panel update at 0% made `{(updating || (progress_percent && ...)) && ...}`
    evaluate to 0, and React printed "0" under the buttons (seen on the demo
    server, 2026-09-27)."""
    page = APP.split("  function renderUpdates() {")[1].split("\n  function ")[0]
    assert "(panelUpdate.progress_percent &&" not in page
    assert "Number(panelUpdate.progress_percent) > 0 &&" in page


def test_a_panel_user_row_keeps_its_columns_in_line():
    """Every row of the users table is a subgrid of the table's columns, as in
    OPanel and SNPanel, so role, package, disk and status line up whatever a
    row holds (operator, 2026-09-30)."""
    users = APP.split("  function renderUsers() {")[1].split("\n  function ")[0]
    assert "user.package_name" in users and "user.totp_enabled" in users
    assert 'role="cell" className="ust-package" data-label' in users
    css = (SRC / "pages" / "Users.css").read_text(encoding="utf-8")
    assert "grid-template-columns:subgrid" in css
