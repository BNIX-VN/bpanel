"""`bpanel regenerate-secrets`: a server cloned from an image gets secrets of
its own (security, operator 2026-11-10: VPSes made from one Proxmox template
shared its SECRET_KEY and tokens)."""
import json
import sqlite3
from pathlib import Path

from app import regenerate_secrets as regen
from app.core import secrets as store
from app.core.config import settings

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (ROOT / "installer" / "files" / "bpanel-regenerate-secrets.sh").read_text(encoding="utf-8")
CHANGE_IP = (ROOT / "change_IP.sh").read_text(encoding="utf-8")
CTL = (ROOT / "installer" / "files" / "bpanelctl").read_text(encoding="utf-8")
INSTALL = (ROOT / "installer" / "install.sh").read_text(encoding="utf-8")
UPDATE = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")


def _decrypt_with(secret_key: str, stored: str) -> str:
    from cryptography.fernet import Fernet
    return Fernet(store._derive_key(secret_key)).decrypt(stored[len("fernet:"):].encode()).decode()


def _server(tmp_path, monkeypatch):
    db = tmp_path / "bpanel.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE database_accounts (id INTEGER PRIMARY KEY, db_password TEXT, note TEXT);
        CREATE TABLE api_tokens (id INTEGER PRIMARY KEY, token_hash TEXT);
        CREATE TABLE mcp_tokens (id INTEGER PRIMARY KEY, token_hash TEXT);
    """)
    conn.execute("INSERT INTO database_accounts VALUES (1, ?, 'plain')", (store.encrypt("db-pass"),))
    conn.execute("INSERT INTO database_accounts VALUES (2, 'fernet:not-a-token', NULL)")
    conn.execute("INSERT INTO api_tokens VALUES (1, 'aaa')")
    conn.execute("INSERT INTO mcp_tokens VALUES (1, 'bbb'), (2, 'ccc')")
    conn.commit()
    conn.close()
    data = tmp_path / "data"
    (data / "addons").mkdir(parents=True)
    (data / "addons" / "state.json").write_text(json.dumps(
        {"notifications": {"settings": {"smtp_password": store.encrypt("smtp"), "smtp_host": "mail"}},
         "mail": {"settings": {"relays": [{"password": store.encrypt("relay")}]}}}), encoding="utf-8")
    (data / "plain.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"APP_ENV=production\nSECRET_KEY={settings.secret_key}\nDATABASE_URL=sqlite:///{db}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(regen, "DATA_DIR", data)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    return db, data


def _env(tmp_path) -> dict:
    return dict(line.split("=", 1) for line in (tmp_path / ".env").read_text(encoding="utf-8").splitlines())


def test_every_stored_secret_moves_to_the_new_key(tmp_path, monkeypatch, capsys):
    db, data = _server(tmp_path, monkeypatch)
    assert regen.main() == 0
    env = _env(tmp_path)
    new_key = env["SECRET_KEY"]
    assert new_key != settings.secret_key and len(new_key) == 64
    assert env["APP_ENV"] == "production"

    conn = sqlite3.connect(db)
    stored, note = conn.execute("SELECT db_password, note FROM database_accounts WHERE id = 1").fetchone()
    assert _decrypt_with(new_key, stored) == "db-pass" and note == "plain"
    # A value the old key could not read either is left as it was.
    assert conn.execute("SELECT db_password FROM database_accounts WHERE id = 2").fetchone()[0] == "fernet:not-a-token"
    # The image's tokens (plain SHA-256) would work on every clone.
    assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM mcp_tokens").fetchone()[0] == 0
    conn.close()

    state = json.loads((data / "addons" / "state.json").read_text(encoding="utf-8"))
    assert _decrypt_with(new_key, state["notifications"]["settings"]["smtp_password"]) == "smtp"
    assert _decrypt_with(new_key, state["mail"]["settings"]["relays"][0]["password"]) == "relay"
    assert state["notifications"]["settings"]["smtp_host"] == "mail"
    assert (data / "plain.json").read_text(encoding="utf-8") == '{"a": 1}'
    out = capsys.readouterr().out
    assert "re-encrypted 3 stored value(s), 1 unreadable" in out and "deleted 3 API/MCP token(s)" in out


def test_nothing_is_written_when_a_file_cannot_be(tmp_path, monkeypatch):
    db, data = _server(tmp_path, monkeypatch)
    monkeypatch.setattr(regen.os, "access", lambda path, mode: False)
    before = (tmp_path / ".env").read_text(encoding="utf-8")
    try:
        regen.main()
    except SystemExit as exc:
        assert "not writable" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == before
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 1
    conn.close()


def test_the_command_is_installed_and_reachable():
    target = "/usr/local/sbin/bpanel-regenerate-secrets"
    assert f'"${{SCRIPT_DIR}}/files/bpanel-regenerate-secrets.sh" {target}' in INSTALL
    assert f'"$SOURCE_DIR/installer/files/bpanel-regenerate-secrets.sh" {target}' in UPDATE
    assert 'regenerate-secrets|--regenerate-secrets) regenerate_secrets "${2:-}" ;;' in CTL
    assert "13) regenerate_secrets --ask ;;" in CTL


def test_the_script_covers_the_rest_and_backs_up_first():
    assert "-m app.regenerate_secrets" in SCRIPT
    first_change = SCRIPT.index("# 1. The panel's own")
    assert SCRIPT.index('keep "$ENV_FILE" "$db_path" "$MYCNF"') < first_change
    for part in ("ALTER USER 'bpanel'@'localhost'", "panel-ssl-selfsigned", "blowfish_secret",
                 'sed -i -E "s/^api-key=.*/api-key=${key}/" "$PDNS_CONF"', "SSO_MASTER_PASSWORD=",
                 'data.update(key="", reporter_id=None'):
        assert part in SCRIPT
    # --once: an image's boot script runs it at every boot; only a new server acts.
    assert 'if [[ $once -eq 1 && -f "$MARKER" && "$(cat "$MARKER" 2>/dev/null)" == "$identity" ]]; then' in SCRIPT
    assert SCRIPT.index("trap restart_panel EXIT") < first_change


def test_change_ip_runs_from_an_images_boot_script():
    """`bpanel change-ip <image-ip> $(hostname -I | awk '{print $1}')` at boot:
    the second may be empty while the network comes up, and the image's own
    server sees its own address."""
    assert 'elif [[ $# -eq 1 || ( $# -eq 2 && -z "$2" ) ]]; then' in CTL
    assert 'new_ip="$(detect_ip)"' in CTL
    assert 'if [[ "$old_ip" == "$new_ip" ]]; then' in CHANGE_IP
    same = CHANGE_IP[CHANGE_IP.index('if [[ "$old_ip" == "$new_ip" ]]; then'):]
    assert same.index("exit 0") < same.index("fi\n")
