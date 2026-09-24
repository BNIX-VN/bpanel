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
THEME = (SRC / "theme.css").read_text(encoding="utf-8")
STYLE = (SRC / "style.css").read_text(encoding="utf-8")
BRAND = (SRC / "brand.css").read_text(encoding="utf-8")
FILES = (SRC / "file-manager.css").read_text(encoding="utf-8")
APP = (SRC / "App.jsx").read_text(encoding="utf-8")
ALL_CSS = {"theme.css": THEME, "style.css": STYLE, "brand.css": BRAND,
           "file-manager.css": FILES}


# --- the two dark themes have to stay one theme ------------------------------

def _dark_blocks():
    """The dark tokens as they are written twice: once for the explicit choice,
    once for the OS preference."""
    chosen = THEME.split(':root[data-theme="dark"]{')[1].split("\n}")[0]
    preferred = THEME.split(':root:not([data-theme="light"]){')[1].split("\n  }")[0]
    parse = lambda block: {  # noqa: E731
        name.strip(): value.strip()
        for name, _, value in (line.partition(":") for line in block.split(";"))
        if name.strip().startswith("--")
    }
    return parse(chosen), parse(preferred)


def test_dark_mode_is_defined_identically_in_both_places():
    """One block applies when the reader picked dark, the other when their
    system did. They are the same theme, and CSS has no way to say so, so a
    token retuned in one and forgotten in the other gives two different dark
    modes depending on how the reader got there - which nobody would think to
    check.
    """
    chosen, preferred = _dark_blocks()
    assert chosen, "no explicit dark block found"
    differences = {
        name: (chosen.get(name), preferred.get(name))
        for name in set(chosen) | set(preferred)
        if chosen.get(name) != preferred.get(name)
    }
    assert not differences, f"dark tokens that differ between the two blocks: {differences}"


def test_dark_surfaces_are_far_enough_apart_to_see():
    """A card on the page background, and a shaded box inside the card, were
    seven points of luminance apart in dark mode - so the structure of a page
    read as a vague grid of rectangles."""
    chosen, _ = _dark_blocks()

    def luminance(token):
        value = chosen[token].lstrip("#")
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    assert luminance("--surface") - luminance("--bg") >= 6
    assert luminance("--surface-alt") - luminance("--surface") >= 6


# --- type and the mono stack -------------------------------------------------

def test_the_type_scale_is_declared_once_and_used():
    for token in ("--text-xs", "--text-sm", "--text-hint", "--text-base",
                  "--text-lg", "--text-xl", "--font-sans", "--font-mono", "--measure"):
        assert token in THEME, token
    assert "font-size:var(--text-base)" in THEME.replace(" ", "")


@pytest.mark.parametrize("name", ["style.css", "brand.css", "file-manager.css"])
def test_no_stylesheet_spells_out_its_own_monospace_stack(name):
    """There were fourteen copies of it in three different orders, so a path
    and the command beside it could render in different faces."""
    body = re.sub(r"/\*.*?\*/", "", ALL_CSS[name], flags=re.S)
    hardcoded = [line.strip()[:90] for line in body.splitlines()
                 if "monospace" in line and "var(--font-mono)" not in line]
    assert not hardcoded, hardcoded[:5]


def test_numbers_line_up():
    """Columns of sizes, ports and percentages, with a figure that changes in
    place every few seconds. Proportional digits make those jump."""
    assert "font-variant-numeric:tabular-nums" in THEME.replace(" ", "")


def test_prose_is_capped_at_a_readable_measure():
    assert "max-width:var(--measure)" in STYLE.replace(" ", "")


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


def test_delete_in_a_list_row_is_a_glyph_not_a_block():
    """Twenty-two sites meant twenty-two filled red squares down the page, each
    at the end of a row of five identical ones - which is where a cursor
    overshoots. Pointing at it still turns it fully red."""
    quiet = BRAND.split(".site-icon-button.danger,")[1].split("}")[0]
    assert "background:var(--surface)" in quiet
    assert "color:var(--danger)" in quiet
    assert ".site-icon-button.danger:hover:not(:disabled)" in BRAND


def test_the_dashboard_does_not_draw_a_box_around_a_box():
    """The groups were cards holding cards. The heading labels the run below it
    without framing it."""
    group = BRAND.split(".dash-group{")[1].split("}")[0]
    assert "background:none" in group and "border:0" in group


def test_the_dashboard_grid_fills_the_width_it_is_given():
    """A fixed six columns left three empty whenever a group had three tiles,
    which is why the page had a ragged right edge."""
    tiles = BRAND.split(".dash-tiles{")[1].split("}")[0]
    assert "auto-fill" in tiles, tiles


def test_the_create_website_form_is_not_in_front_of_the_list():
    """Making a site is occasional; finding one is why the page gets opened.
    The form was four hundred pixels of it above the list."""
    assert "const [createFormOpen, setCreateFormOpen] = useState(false);" in APP
    assert "const createOpen = createFormOpen || websites.length === 0;" in APP
    # An empty panel is the exception: there the form is the only thing to do.
    assert "{createOpen && <section className=\"section create-site-section\">" in APP


def test_the_file_list_says_what_its_columns_are():
    """755 and 4.1 KB floated between the name and the buttons under no
    heading at all."""
    header = APP.split('<div className="file-list-header">')[1].split("</div>")[0]
    for column in ("t('Name')", "t('Mode')", "t('Size')"):
        assert column in header, column
    grid = FILES.split(".file-list-header {")[1].split("}")[0]
    row = FILES.split(".file-item {")[1].split("}")[0]
    columns = lambda block: re.search(r"grid-template-columns:([^;]+);", block).group(1).strip()  # noqa: E731
    assert columns(grid) == columns(row), "header and row columns must line up"


def test_the_dashboard_headings_are_translated_where_they_are_drawn():
    """Having the words in the dictionary is not the same as using them.

    Every group heading was a key with a Vietnamese translation, and the
    dictionary check passed - while the page drew {group.title} raw, so the
    sidebar read "Tổng quan" beside a heading that read "Dashboard". The same
    array feeds the page title in the topbar.
    """
    assert "<h2>{t(group.title)}</h2>" in APP
    assert "<span>{t(group.hint)}</span>" in APP
    assert "{activeNavItem?.[1] ? t(activeNavItem[1])" in APP
