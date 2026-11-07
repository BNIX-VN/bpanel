"""The file manager's tree starts at the account's home (operator, 2026-11-07).

/home/<user> is the root, with each website and apps/<name> of that account
under it, instead of one website's folder. Files are still changed only inside
a website or an application: the helper confines every file operation to a
managed root, and the page offers nothing to make or upload in the home itself.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "frontend" / "src"
APP = (ROOT / "App.jsx").read_text(encoding="utf-8")
TREE = (ROOT / "components" / "FolderTree.jsx").read_text(encoding="utf-8")
HELPER = (Path(__file__).resolve().parents[3] / "installer" / "files" / "bpanel-helper.sh").read_text(encoding="utf-8")


def _render_files() -> str:
    start = APP.index("  function renderFiles({ brand, actions } = {}) {")
    return APP[start:APP.index("\n  }\n", APP.index('<div className="file-toolbar fm-toolbar">', start))]


def test_the_tree_and_the_path_start_at_the_home():
    body = _render_files()
    assert "match(/^(\\/home\\/[^/]+)\\//)" in body
    assert "homeLabel={fileHome} homeEntries={homeEntries}" in body
    assert "title={fileHome}>{fileHome}</button>" in body, "the first crumb is /home/<user>"
    assert "homeLabel = ''" in TREE and "<span>apps</span>" in TREE


def test_every_website_and_app_of_that_account_is_in_it():
    body = _render_files()
    assert "websites.filter(site => String(site.root_path || '').startsWith(`${fileHome}/`))" in body
    assert "siteApps.items.filter(app => String(app.directory || '').startsWith(`${fileHome}/apps/`))" in body


def test_nothing_is_made_or_uploaded_in_the_home_itself():
    body = _render_files()
    toolbar = body[body.index('<div className="file-toolbar fm-toolbar">'):]
    toolbar = toolbar[:toolbar.index("</div>")]
    assert "!hasTarget ||" not in toolbar and toolbar.count("!canEdit ||") >= 5
    assert "const canEdit = hasTarget && !fileAtHome;" in body


def test_the_helper_still_keeps_file_operations_inside_a_website_or_an_app():
    depth = HELPER[HELPER.index("managed_root_depth() {"):]
    depth = depth[:depth.index("\n}\n")]
    assert "instead of the bare home directory" in depth
