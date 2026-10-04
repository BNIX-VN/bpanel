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


def test_the_dashboard_says_how_things_stand_not_the_sidebar_again():
    """Its Hosting / Security / System blocks repeated the sidebar item for
    item (operator, 2026-09-25). What is left is what the sidebar cannot say:
    the meters, a card per thing that can be wrong, what needs attention and
    the few things done often - as in OPanel, one brand, one layout."""
    dashboard = _dashboard()
    assert "featureGroups" not in APP and "function FeatureTile(" not in APP
    assert "dash-resources" in dashboard and 'className={`status-card tone-${card.tone}`}' in dashboard
    for key in ("websites", "ssl", "databases", "backups", "firewall", "waf", "malware", "services"):
        assert f"key: '{key}'" in dashboard, key
    assert "<h2>{t('Needs attention')}</h2>" in dashboard and "<h2>{t('Quick actions')}</h2>" in dashboard
    assert "t('Everything looks fine.')" in dashboard
    # "New website" and "New database" arrive with their form open.
    assert "setCreateFormOpen(true); navigateToPage('websites');" in dashboard
    assert "setDbCreateOpen(true); navigateToPage('databases');" in dashboard


def test_a_customer_is_not_shown_the_server():
    """Server state is an administrator's: the endpoint leaves it out for a
    customer, and the cards that read it sit in the admin branch."""
    dashboard = _dashboard()
    index = dashboard.index("cards.push({ key: 'services'")
    before = dashboard[:index]
    assert before.rfind("if (isAdmin) {") > before.rfind("} else {"), "the services card is not inside the admin branch"
    customer = dashboard.split("} else {\n      cards.push(sslCard);", 1)[1].split("\n    }\n", 1)[0]
    assert "key: 'waf'" in customer and "key: 'security'" in customer
    assert "key: 'websites'" not in customer and "key: 'databases'" not in customer, (
        "the plan-usage card above already counts them"
    )


def test_the_sidebar_holds_what_is_used_every_day():
    """OPanel's sidebar (operator, 2026-09-29: BPanel follows OPanel exactly):
    one plain list - the everyday pages, the addons that are on in OPanel's
    order, then Settings. Everything else is one click further, on the
    Settings page, which is a page and not a collapsed submenu."""
    sidebar = APP.split("const navSections = [")[1].split("].filter(section")[0]
    keys = re.findall(r"\['([a-z-]+)', '", sidebar)
    assert keys == ["dashboard", "websites", "applications", "ssl", "databases", "cron", "files",
                    "sftp", "backups", "users", "mail", "dns", "mcp", "notifications", "malware", "settings"]
    assert sidebar.count("{ key: ") == 1, "one list, no groups"
    assert "sidebar-subnav" not in APP and "settingsMenuOpen" not in APP
    hub = APP.split("const settingsGroups = [")[1].split("const settingsItems = ")[0]
    hub_keys = re.findall(r"\['([a-z-]+)', '", hub)
    assert hub_keys == ["firewall", "waf", "access-logs", "security",
                        "panel-settings", "services", "php", "updates", "addons"]
    assert not set(keys) & set(hub_keys), "a page in both places"
    assert "if (page === 'settings') return renderSettingsHub();" in APP
    assert 'className="section settings-hub"' in APP and 'className="settings-tile"' in APP

def test_a_settings_page_keeps_its_own_name_and_lights_up_settings():
    assert "const navPage = settingsItems.some(([key]) => key === basePage) ? 'settings' : basePage;" in APP
    assert "<h1>{pageItem?.[1] ? t(pageItem[1])" in APP
    # As in OPanel, its title is a crumb back to the Settings page.
    assert '<h1 className="page-crumbs"><button type="button" onClick={() => navigateToPage(\'settings\')}>' in APP

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
    The form was four hundred pixels of it above the list. As in OPanel it is
    a create-panel section, closed by an icon-only X, and "New website" on
    the list (or its empty state) opens it."""
    assert "const [createFormOpen, setCreateFormOpen] = useState(false);" in APP
    assert "const createOpen = createFormOpen || websites.length === 0;" in APP
    # An empty panel is the exception: there the form is the only thing to do.
    assert "{createOpen && <section className=\"section create-panel\">" in APP
    page = APP.split("  function renderWebsites() {")[1].split("  function renderSsl() {")[0]
    assert 'className="secondary icon-only mini" onClick={() => setCreateFormOpen(false)}' in page
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
        # Product and file names: "Claude Code", "Cursor - .cursor/mcp.json".
        "{label}</strong>",
    }
    unexpected = sorted(text for text in drawn_raw if text not in allowed)
    assert not unexpected, f"labels drawn without t(): {unexpected}"


def test_the_dashboard_headings_are_translated_where_they_are_drawn():
    """Having the words in the dictionary is not the same as using them.

    Every group heading was a key with a Vietnamese translation, and the
    dictionary check passed - while the page drew {group.title} raw, so the
    sidebar read "Tổng quan" beside a heading that read "Dashboard". The
    launcher's headings and tile names go through t() where drawn, and the
    nav array still feeds the page title in the topbar.
    """
    dashboard = _dashboard()
    assert "<h2>{t('Server resources')}</h2>" in dashboard
    # Card labels are translated where they are built; the ones left raw are
    # WAF, CPU and RAM, which read the same in both languages.
    assert re.findall(r"label: '([^']+)'", dashboard) == ["WAF", "WAF", "CPU", "RAM"]
    assert "<p className=\"sidebar-section-title\">{t(section.title)}</p>" in APP
    assert "{pageItem?.[1] ? t(pageItem[1])" in APP


# --- the operator's list, 2026-09-25 -----------------------------------------

def test_the_file_list_says_when_each_file_was_changed():
    """The API has sent every entry's mtime all along; nothing drew it. As in
    OPanel the date has a column of its own, and moves beside the size once
    the columns stack on a narrow screen."""
    row = APP.split('<div className="file-list">')[1].split("</div>)}")[0]
    assert '<span className="file-date" title={formatFileTime(item.modified, true)}>{formatFileTime(item.modified)}</span>' in row
    assert '<span className="file-date-inline"> · {formatFileTime(item.modified)}</span>' in row


def test_permissions_open_in_opanels_dialog_and_keep_what_bpanel_adds():
    """OPanel's permissions dialog (a modal card with the grid, the numeric
    mode and presets), with BPanel's own additions still in it: setgid on
    folders, and the toolbar's Permissions for every selected item at once."""
    dialog = APP.split("  function renderChmodDialog() {")[1].split("\n  }\n")[0]
    assert '<div className="modal-card chmod-card"' in dialog and '<div className="chmod-mode-row">' in dialog
    assert "special: bits.special === 2 ? 0 : 2" in dialog, "setgid on folders"
    files = APP.split("  function renderFiles() {")[1].split("\n  }\n")[0]
    assert "onClick={() => openChmodDialog(selectedChmodItems)}" in files
    assert "chmod-backdrop" not in APP and "file-modified" not in APP


def test_a_scan_from_the_history_opens_its_own_page():
    """Clicking a past run used to unfold its details at the foot of a long page.

    As in OPanel it opens as a sub-page of the scanner, with a back button on
    the left; the address it used to have (/malware-scan) shows the scanner.
    """
    malware = APP.split("  function renderMalware() {")[1].split("\n  function ")[0]
    assert "onClick={() => openMalwareScanDetail(job)}" in malware
    assert "if (malwareDetailJob) {" in malware
    assert "<button className=\"secondary\" onClick={() => setMalwareDetailJob(null)}><ArrowLeft size={14}/> {t('Malware scanner')}</button>" in malware
    assert "'malware-scan': '/malware-scan'" in APP
    assert "!['malware', 'malware-scan'].includes(page)" in APP


def test_updating_wordpress_asks_first():
    """The card's Update button ran core, plugins and themes at once. As in
    OPanel it opens the inline WordPress panel, and "Update All" there runs it."""
    page = APP.split("  function renderWebsites() {")[1].split("  function renderSsl() {")[0]
    card = page.split('<div className="site-feature-actions">')[1].split("</article>")[0]
    assert "onClick={() => openWordPressUpdate(site)}" in card and "updateWordPressAll" not in card
    panel = page.split('<div className="wp-manager-panel">')[1]
    assert "onClick={() => updateWordPressAll(site)}><RefreshCw size={14}/> {t('Update All')}" in panel


def test_a_cron_schedule_is_picked_rather_than_typed():
    """OPanel's schedule picker: a preset dropdown beside the raw expression,
    both always there; typing in the expression switches it to "Custom…".
    The list names each schedule and shows the expression beside it."""
    assert "const CRON_PRESETS = [" in APP
    picker = APP.split("  function renderSchedulePicker(key, value, onChange, inputId) {")[1].split("\n  }\n")[0]
    assert '<div className="schedule-picker">' in picker
    assert "{CRON_PRESETS.map(([expr, label]) => <option key={expr} value={expr}>{t(label)}</option>)}" in picker
    assert "<option value=\"custom\">{t('Custom…')}</option>" in picker
    cron = APP.split("  function renderCron() {")[1].split("\n  }\n")[0]
    assert "renderSchedulePicker('cron', cronSchedule, setCronSchedule, 'cron-schedule-input')" in cron
    assert '<code className="cron-expr">{item.schedule}</code>' in cron


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


def test_a_panel_user_row_keeps_opanels_five_cells():
    """The shared .row grid has five columns. A sixth cell (package and 2FA
    badges) pushed the buttons onto a line of their own (operator, 2026-09-30);
    they now sit under the name."""
    row = APP.split('<div className="row user-row" key={user.id}>')[1].split('<div className="row-actions">')[0]
    cells = re.findall(r"^          <(div|span)\b", row, flags=re.M)
    assert len(cells) == 4, cells  # name, role, status, disk; the buttons are the fifth
    assert "user.package_name" in row and "user.totp_enabled" in row
