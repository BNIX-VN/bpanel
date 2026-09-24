"""Translation: the dictionary, the fallback, and the switch.

The design rests on one property - a string with no translation renders in
English rather than blank or as a key - so most of what is worth testing is
that the property holds and that nothing has drifted out of sync with it.

These read the source rather than running a browser. The panel has no
JavaScript test runner, and the things that break here are textual: a key that
no longer matches any string, a Vietnamese word left in the English source, a
t() wrapped around a page key.
"""

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC = PROJECT_ROOT / "frontend" / "src"
APP = (SRC / "App.jsx").read_text(encoding="utf-8")
I18N = (SRC / "i18n.js").read_text(encoding="utf-8")
VI = (SRC / "locales" / "vi.js").read_text(encoding="utf-8")


def _dictionary() -> dict:
    """The vi.js entries, parsed out of the generated file.

    Generated with one entry per line and JSON-compatible escaping, which is
    what makes this safe to read with a regex.
    """
    entries = {}
    for line in VI.splitlines():
        match = re.match(r'^  ("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),$', line.strip().join(("  ", "")))
        if not match:
            match = re.match(r'^\s+("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),$', line)
        if match:
            entries[json.loads(match.group(1))] = json.loads(match.group(2))
    return entries


DICTIONARY = _dictionary()


# --- the dictionary itself ---------------------------------------------------

def test_the_dictionary_parses_and_is_not_empty():
    assert len(DICTIONARY) > 500, f"only parsed {len(DICTIONARY)} entries"


def test_nothing_is_translated_to_itself():
    """An entry equal to its key is dead weight: it says the translator looked
    at it and changed nothing, which the fallback already does for free."""
    same = [k for k, v in DICTIONARY.items() if k == v]
    # Proper nouns and terms that genuinely do not change are left out of the
    # file entirely rather than mapped to themselves.
    assert not same, f"entries that translate to themselves: {same[:10]}"


def test_no_entry_is_empty():
    """An empty translation renders as a blank label, which is worse than
    English - the fallback exists precisely to avoid that."""
    empty = [k for k, v in DICTIONARY.items() if not v.strip()]
    assert not empty, empty[:10]


def test_every_key_is_a_string_something_actually_shows():
    """A key matching nothing is a translation nobody will ever see.

    Checked against the interface source and against the API messages, which
    are the two places a key can legitimately come from.
    """
    api = ""
    for path in sorted((PROJECT_ROOT / "backend" / "app" / "api").glob("*.py")):
        api += path.read_text(encoding="utf-8")

    # t('Everyone else\'s tokens') in the source does not contain the raw
    # sentence, so compare against a copy with the escaping removed. Getting
    # this wrong reports five healthy entries as orphans, which is how it was
    # found.
    unescaped = APP.replace("\\'", "'").replace('\\"', '"')
    orphans = [k for k in DICTIONARY if k not in unescaped and k not in api]
    assert not orphans, f"{len(orphans)} keys match nothing: {orphans[:10]}"


def test_the_placeholders_and_code_samples_were_left_alone():
    """Example domains and code are not language, and translating them would
    make the example wrong."""
    for literal in ("domain.com", "user@domain.com", "s3.wasabisys.com",
                    "php -q cron.php >/dev/null 2>&1", "-----BEGIN CERTIFICATE-----"):
        assert literal not in DICTIONARY, literal


# --- the fallback, which is the whole design ---------------------------------

def test_an_unknown_string_falls_back_to_english():
    body = I18N.split("export function t(text)")[1].split("\n}")[0]
    # Returns the input when there is no hit, rather than '' or the key name.
    assert "return typeof hit === 'string' && hit ? hit : text;" in body


def test_anything_that_is_not_a_string_passes_straight_through():
    """Render code hands null, numbers and elements around freely."""
    body = I18N.split("export function t(text)")[1].split("\n}")[0]
    assert "if (typeof text !== 'string' || !text) return text;" in body


def test_an_unknown_language_code_is_refused():
    body = I18N.split("export function setLanguage(code)")[1].split("\n}")[0]
    assert "if (!isKnown(code)" in body


def test_storage_failures_do_not_break_the_panel():
    """localStorage throws in a private window and in some embedded browsers.
    A panel that will not load because it could not remember a preference is
    a worse panel."""
    assert I18N.count("try {") >= 4
    assert "catch { return null; }" in I18N


# --- the switch --------------------------------------------------------------

def test_the_switch_exists_and_offers_both_languages():
    assert "function LanguageToggle(" in APP
    assert "LANGUAGES.map(" in APP
    assert "['vi', 'Tiếng Việt']" in I18N
    assert "['en', 'English']" in I18N


def test_the_switch_sits_with_the_theme_toggle():
    """Two controls that do the same kind of thing belong together; a person
    who found one will look for the other in the same place."""
    assert APP.count("<LanguageToggle language={language} onChange={changeLanguage}/>") == 3
    assert APP.count("<ThemeToggle theme={theme} onToggle={toggleTheme}/>") == 3


def test_changing_the_language_re_renders():
    """t() is read during render, so the tree has to render again. The hook
    subscribes to the event setLanguage fires."""
    assert "const [language, changeLanguage] = useLanguage();" in APP
    hook = I18N.split("export function useLanguage()")[1].split("\n}")[0]
    assert "addEventListener(LANGUAGE_EVENT" in hook


def test_the_page_language_is_announced():
    """Screen readers and the browser's own translation prompt both read it."""
    assert 'setAttribute(\'lang\'' in I18N


# --- what the sweep must not have touched ------------------------------------

@pytest.mark.parametrize("page_key", [
    "navigateToPage('websites')", "navigateToPage('files')",
    "routeForPage('files')",
])
def test_page_keys_were_not_translated(page_key):
    """The keys are lowercase and the dictionary is not, which is what kept
    them safe - but it is worth holding, because a future entry could collide."""
    assert page_key in APP


def test_no_class_name_was_wrapped():
    assert "className={t(" not in APP


def test_the_interface_source_has_no_vietnamese_left_in_it():
    """English is the source language; Vietnamese belongs in the dictionary.

    A "Sau" button survived the sweep that made the interface English and was
    only found when the translation work went looking for strings to extract.
    Its sibling said "Previous".
    """
    vietnamese_only = "ăâđêôơưĂÂĐÊÔƠƯáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ"
    offenders = []
    for number, line in enumerate(APP.splitlines(), start=1):
        if line.lstrip().startswith(("//", "*", "/*")):
            continue
        if any(character in line for character in vietnamese_only):
            offenders.append(f"{number}: {line.strip()[:80]}")
    assert not offenders, "Vietnamese in App.jsx:\n" + "\n".join(offenders[:5])


# --- the API messages --------------------------------------------------------

def test_api_errors_are_translated_where_they_are_shown():
    """The server does not know the reader's language; the panel does."""
    body = APP.split("function formatApiError(")[1].split("\n}")[0]
    assert "return t(fallback)" in body
    assert "t(cleaned)" in body


def test_a_handful_of_api_messages_have_translations():
    for message in ("Website not found", "Invalid username or password",
                    "Cannot delete yourself", "Request failed."):
        assert message in DICTIONARY, message
