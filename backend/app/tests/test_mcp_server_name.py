"""Each panel and account gets its own MCP server name (operator, 2026-11-08):
every server was "bpanel", so a client connected to several VPSes could not
tell them apart, nor add a second one under the same name."""
from pathlib import Path

from app.services import mcp

APP = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")


def _snippets() -> str:
    start = APP.index("  function mcpClientSnippets(token) {")
    return APP[start:APP.index("\n  }\n", start)]


def test_the_setup_snippets_use_the_name_not_a_fixed_one():
    body = _snippets()
    assert "const name = mcpName;" in body
    assert "--transport http ${name} " in body
    assert "mcpServers: { [name]:" in body and "servers: { [name]:" in body
    assert "http bpanel " not in body and "{ bpanel:" not in body


def test_the_name_comes_from_the_panel_address_and_the_account():
    assert "function defaultMcpServerName(hostname, username)" in APP
    assert "defaultMcpServerName(window.location.hostname, currentUser?.username)" in APP
    assert "replace(/^(panel|www)\\./, '')" in APP and ".slice(0, 40)" in APP
    assert "setMcpServerName(e.target.value.replace(/[^A-Za-z0-9_-]/g, ''))" in APP


def test_the_server_says_which_panel_it_is(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "panel_domain", "panel.media.io.vn")
    assert mcp.server_info()["title"] == "BPanel · panel.media.io.vn"
    assert mcp.server_info()["name"] == "bpanel"
    monkeypatch.setattr(settings, "panel_domain", "")
    assert mcp.server_info()["title"] == "BPanel"
