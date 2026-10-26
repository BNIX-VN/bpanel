"""The File manager opens in a browser tab of its own, with only the files in
it, as cPanel's (operator, 2026-10-26) - and as OPanel's."""
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "src"
APP = (FRONTEND / "App.jsx").read_text(encoding="utf-8")
NAV = (FRONTEND / "lib" / "navigation.jsx").read_text(encoding="utf-8")


def test_every_way_to_the_files_opens_their_tab():
    start = APP.index("const navigateToPage = useCallback(")
    navigate = APP[start:APP.index("  }, []);", start)]
    assert "if (nextPage === 'files') {" in navigate and "window.open(fileManagerUrl(options), '_blank', 'noopener');" in navigate
    # A website's own button opens its application's folder when one serves it.
    assert "navigateToPage('files', appId ? { appId } : { websiteId: site.id });" in APP
    assert "navigateToPage('files', { appId: app.id });" in APP


def test_the_tab_opens_on_what_it_was_asked_for():
    assert "useState(() => standaloneEditor?.websiteId || fileManagerTarget.websiteId);" in APP
    assert "useState(() => standaloneEditor?.appId || fileManagerTarget.appId);" in APP
    # An application's root has no public_html.
    assert "useState(() => (fileManagerTarget.appId ? '' : 'public_html'));" in APP


def test_the_tab_has_nothing_of_the_panel_around_it():
    assert "if (page === 'files') return renderStandaloneFiles();" in APP
    tab = APP[APP.index("function renderStandaloneFiles() {"):APP.index("if (standaloneEditor) return renderStandaloneEditor();")]
    assert '<main className="fm-app">' in tab and "{renderFiles({ brand: renderBrandMark(), actions })}" in tab
    assert "sidebar" not in tab and "renderTopStats" not in tab
    # Under <main> the columns at once (operator, 2026-10-26): the bar, the
    # tree and the files are renderFiles()'s top level - no card inside a card.
    files = APP[APP.index("  function renderFiles("):]
    files = files[:files.index("\n  function ")]
    assert '<header className="fm-app-top">' in files and '<section className="fm-main"' in files
    for wrapper in ('className="section"', 'className="file-manager"', 'className="file-panel"', 'className="fm-body"'):
        assert wrapper not in files, wrapper
    # No tab row of File manager / SFTP / Terminal any more.
    assert "{ key: 'files'," not in NAV
    assert "sftp: 'files', terminal: 'files'" in NAV
    # Refresh is in the toolbar, not a row of its own over the files.
    assert "<PageHeader onRefresh" not in files and "onClick={() => listFiles(fileListPath)}><RefreshCw" in files
