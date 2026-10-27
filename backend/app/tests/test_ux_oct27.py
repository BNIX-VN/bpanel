"""The operator's 2026-10-27 batch: one click where there were two, forms in
the page, the bot list open, and an uploaded plugin or theme that is
installed, not switched on."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "frontend" / "src"
APP = (SRC / "App.jsx").read_text(encoding="utf-8")
WP = (SRC / "pages" / "WordPress.jsx").read_text(encoding="utf-8")


def test_new_database_opens_under_the_search():
    page = APP.split("<NoAutofillInput name=\"database-search\"", 1)[1]
    assert page.index("<InlinePanel open={dbCreateOpen}") < page.index("className={`dbt")


def test_the_global_bad_bots_are_open_with_the_paste_box_shown():
    assert "wafBotsOpen" not in APP
    assert "<details className=\"global-bots-paste\">" not in APP
    assert "<label className=\"global-bots-paste\">" in APP


def test_a_website_and_a_wordpress_row_have_icons_not_a_menu():
    assert "<IconActions label={t('Website actions for {domain}', { domain: site.domain })} items={menuItems}/>" in APP
    assert "<IconActions className=\"wpm-row-actions\"" in WP
    assert "{t('Manage')}</button>" not in WP


def test_an_uploaded_zip_is_installed_not_activated():
    assert "form.append('activate', '0');" in WP
    assert "activateUpload" not in WP
    assert "t('Owner: {name}', { name: item.owner_username })" in WP


def test_login_as_lands_on_the_accounts_dashboard():
    """Operator, 2026-10-27: after "Login as" the account's Dashboard, not
    its websites."""
    app = (SRC / "App.jsx").read_text(encoding="utf-8")
    login_as = app[app.index("async function quickLoginUser("):app.index("async function returnToImpersonator(")]
    assert login_as.count("navigateToPage('dashboard');") == 2
    assert "navigateToPage('websites')" not in login_as
