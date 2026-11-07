"""Copy and Move work like a clipboard (operator, 2026-11-08).

Copy/Move only remember the items; the customer opens the folder they want
them in and presses Paste, instead of typing the destination's path.
"""
from pathlib import Path

APP = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start:APP.index("\n  }\n", start)]


def test_copy_and_move_ask_for_no_path():
    assert "to folder:`" not in APP
    clip = _function("clipFileItems")
    assert "promptDialog" not in clip and "request(" not in clip
    assert "setFileClipboard({ action, paths: [...paths]" in clip
    assert "clipFileItems('copy', paths);" in APP and "clipFileItems('move', paths);" in APP


def test_paste_goes_into_the_folder_on_screen_of_any_tree_of_the_account():
    paste = _function("pasteFileClipboard")
    assert "clip.targetKey === fileTargetKey() ? {} : {" in paste
    assert "destination_website_id: here.website_id ?? null" in paste
    assert "destination_app_id: here.app_id ?? null" in paste
    assert "destination_path: fileListPath || ''" in paste
    assert "...clip.targetBody, ...into" in paste
    assert "Open the website or application they came from" not in APP
    assert "if (clip.action === 'move') setFileClipboard(null);" in paste


def test_the_paste_bar_is_not_offered_in_the_home_listing():
    assert "{fileClipboard && !fileAtHome && <div className=\"fm-selection fm-clipboard\"" in APP
    assert "onClick={pasteFileClipboard}" in APP
