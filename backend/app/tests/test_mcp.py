"""MCP: the token, the transport, and who is allowed to see what.

The rules being held to here are the ones that are easy to get subtly wrong
and impossible to notice afterwards:

  - a token is never stored, only its hash
  - every reason to refuse a token gives the same answer to the holder
  - a tool the caller may not use does not appear, and is "unknown" if named
  - the addon being off means the endpoint does not exist, not that it is
    locked - and that check comes before anything looks at credentials
"""

from datetime import datetime, timedelta

import pytest

from app.core.permissions import Role
from app.models.entities import McpToken, User
from app.services import file_manager
from app.services import mcp
# At module scope on purpose. The tools register themselves into mcp.REGISTRY
# when this is first imported, and several tests below swap that dict for an
# empty one. If the first import happened inside one of those, every real tool
# would register into the temporary dict and vanish when it was restored -
# leaving the registry tests passing against nothing, which is the worst way
# for this to fail.
from app.services import mcp_tools


# --- fixtures ---------------------------------------------------------------

class _Query:
    def __init__(self, rows, model=None):
        self._rows = rows
        self._model = model

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def count(self):
        return len(self._rows)


class _Session:
    def __init__(self, tokens=(), users=()):
        self._tokens = list(tokens)
        self._users = list(users)
        self.commits = 0

    def query(self, model):
        if model is McpToken:
            return _Query(self._tokens)
        if model is User:
            return _Query(self._users)
        return _Query([])

    def add(self, item):
        pass

    def commit(self):
        self.commits += 1


def _user(role=Role.admin, active=True, user_id=1):
    return User(id=user_id, username="admin" if role == Role.admin else "customer",
                email="a@example.test", role=str(role), hashed_password="x",
                is_active=active)


def _token(user_id=1, can_write=False, expires_in=timedelta(days=30),
           revoked=None, token_hash="h"):
    return McpToken(id=1, user_id=user_id, name="laptop", token_hash=token_hash,
                    prefix="bpmcp_abcdef", can_write=can_write,
                    expires_at=datetime.utcnow() + expires_in,
                    revoked_at=revoked, created_at=datetime.utcnow())


def _ctx(user=None, token=None):
    user = user or _user()
    return mcp.Context(db=_Session(), user=user, token=token or _token())


# --- the token --------------------------------------------------------------

def test_the_token_itself_is_never_what_gets_stored():
    token, stored, prefix = mcp.generate_token()
    assert token.startswith("bpmcp_")
    assert stored == mcp.hash_token(token)
    assert token not in stored
    assert len(stored) == 64, "sha-256 hex, and the column is sized for it"
    assert prefix == token[:12] and prefix in token


def test_two_tokens_are_never_the_same():
    assert len({mcp.generate_token()[0] for _ in range(50)}) == 50


@pytest.mark.parametrize("why,token_kwargs,user_kwargs", [
    ("expired", {"expires_in": timedelta(days=-1)}, {}),
    ("revoked", {"revoked": datetime.utcnow()}, {}),
    ("owner suspended", {}, {"active": False}),
])
def test_every_reason_to_refuse_looks_the_same_from_outside(why, token_kwargs, user_kwargs):
    """The holder learns nothing about which check stopped them."""
    token, stored, _ = mcp.generate_token()
    row = _token(token_hash=stored, **token_kwargs)
    db = _Session(tokens=[row], users=[_user(**user_kwargs)])
    assert mcp.authenticate(db, token) is None, why


def test_a_token_whose_owner_is_gone_is_refused():
    token, stored, _ = mcp.generate_token()
    db = _Session(tokens=[_token(token_hash=stored)], users=[])
    assert mcp.authenticate(db, token) is None


def test_a_good_token_is_accepted():
    token, stored, _ = mcp.generate_token()
    row = _token(token_hash=stored)
    db = _Session(tokens=[row], users=[_user()])
    assert mcp.authenticate(db, token) is row


def test_something_that_is_not_one_of_ours_is_refused_without_a_lookup():
    """No database round trip for a string that cannot be a token."""
    class _Explodes(_Session):
        def query(self, model):
            raise AssertionError("should not have looked it up")

    assert mcp.authenticate(_Explodes(), "") is None
    assert mcp.authenticate(_Explodes(), "sk-something-else") is None


def test_last_used_is_not_written_on_every_call():
    row = _token()
    row.last_used_at = datetime.utcnow()
    db = _Session()
    mcp.touch(db, row)
    assert db.commits == 0, "a tool call must not cost a write"

    row.last_used_at = datetime.utcnow() - timedelta(minutes=5)
    mcp.touch(db, row)
    assert db.commits == 1


# --- who sees which tool ----------------------------------------------------

@pytest.fixture
def sample_tools(monkeypatch):
    monkeypatch.setattr(mcp, "REGISTRY", {})

    @mcp.tool("read_thing", "Read", "Reads.")
    def _read(ctx, args):
        return {"ok": True}

    @mcp.tool("write_thing", "Write", "Writes.", writes=True)
    def _write(ctx, args):
        return {"ok": True}

    @mcp.tool("admin_thing", "Admin", "Admin only.", admin_only=True)
    def _admin(ctx, args):
        return {"ok": True}

    return mcp.REGISTRY


def test_a_read_only_token_is_not_shown_the_writing_tools(sample_tools):
    ctx = _ctx(token=_token(can_write=False))
    assert [t.name for t in mcp.visible_tools(ctx)] == ["admin_thing", "read_thing"]


def test_a_customer_is_not_shown_the_administrative_tools(sample_tools):
    ctx = _ctx(user=_user(role=Role.end_user), token=_token(can_write=True))
    assert [t.name for t in mcp.visible_tools(ctx)] == ["read_thing", "write_thing"]


def test_a_hidden_tool_called_by_name_is_reported_as_unknown(sample_tools):
    """Not "forbidden" - that would confirm it exists.

    The tool list is otherwise an enumeration oracle: a customer's token could
    map out the administrative surface by calling names and reading which ones
    came back as refused rather than missing.
    """
    ctx = _ctx(user=_user(role=Role.end_user))
    answer = mcp.call_tool(ctx, "admin_thing", {})
    assert answer["isError"] is True
    assert answer["content"][0]["text"] == "Unknown tool: admin_thing"
    assert mcp.call_tool(ctx, "no_such_tool", {})["content"][0]["text"] \
        == "Unknown tool: no_such_tool"


def test_the_schema_marks_which_tools_only_read(sample_tools):
    by_name = {t.name: t.schema() for t in mcp.visible_tools(_ctx(token=_token(can_write=True)))}
    assert by_name["read_thing"]["annotations"]["readOnlyHint"] is True
    assert by_name["write_thing"]["annotations"]["readOnlyHint"] is False


# --- argument checking ------------------------------------------------------

@pytest.fixture
def one_tool(monkeypatch):
    monkeypatch.setattr(mcp, "REGISTRY", {})

    @mcp.tool("thing", "Thing", "Does a thing.",
              {"domain": mcp.DOMAIN_ARG,
               "lines": {"type": "integer", "minimum": 1, "maximum": 100},
               "mode": {"type": "string", "enum": ["on", "off"]},
               "flag": {"type": "boolean"}},
              required=("domain",))
    def _thing(ctx, args):
        return args

    return mcp.REGISTRY["thing"]


def test_a_missing_required_argument_names_it(one_tool):
    with pytest.raises(mcp.ToolError) as exc:
        mcp.validate_arguments(one_tool, {})
    assert "domain" in str(exc.value)


def test_an_invented_argument_is_refused_with_the_real_ones(one_tool):
    """Models produce plausible field names that are not the schema's."""
    with pytest.raises(mcp.ToolError) as exc:
        mcp.validate_arguments(one_tool, {"domain": "a.test", "hostname": "b.test"})
    assert "hostname" in str(exc.value) and "domain" in str(exc.value)


def test_a_number_sent_as_text_is_accepted(one_tool):
    """An assistant that means 50 sometimes sends "50"."""
    assert mcp.validate_arguments(one_tool, {"domain": "a.test", "lines": "50"})["lines"] == 50


def test_a_number_out_of_range_says_the_bound(one_tool):
    with pytest.raises(mcp.ToolError) as exc:
        mcp.validate_arguments(one_tool, {"domain": "a.test", "lines": 5000})
    assert "100" in str(exc.value)


def test_something_that_is_not_a_number_is_refused(one_tool):
    with pytest.raises(mcp.ToolError):
        mcp.validate_arguments(one_tool, {"domain": "a.test", "lines": "many"})


def test_an_enum_lists_what_was_allowed(one_tool):
    with pytest.raises(mcp.ToolError) as exc:
        mcp.validate_arguments(one_tool, {"domain": "a.test", "mode": "sideways"})
    assert "on" in str(exc.value) and "off" in str(exc.value)


def test_a_tool_error_comes_back_as_a_result_not_a_crash(monkeypatch):
    monkeypatch.setattr(mcp, "REGISTRY", {})

    @mcp.tool("boom", "Boom", "Raises.")
    def _boom(ctx, args):
        raise RuntimeError("the database is on fire")

    answer = mcp.call_tool(_ctx(), "boom", {})
    assert answer["isError"] is True
    assert "the database is on fire" in answer["content"][0]["text"]


# --- JSON-RPC ---------------------------------------------------------------

def test_initialize_answers_with_a_version_the_client_asked_for():
    answer = mcp.handle_message(_ctx(), {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert answer["result"]["protocolVersion"] == "2024-11-05"


def test_a_version_we_do_not_know_gets_the_newest_one():
    answer = mcp.handle_message(_ctx(), {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    })
    assert answer["result"]["protocolVersion"] == mcp.LATEST_PROTOCOL_VERSION


def test_a_notification_is_answered_with_nothing():
    """It has no id, and the specification says send no response at all."""
    assert mcp.handle_message(_ctx(), {
        "jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_a_batch_of_nothing_but_notifications_produces_no_body():
    assert mcp.handle_payload(_ctx(), [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/cancelled"},
    ]) is None


def test_a_batch_answers_only_the_messages_that_asked(sample_tools):
    answers = mcp.handle_payload(_ctx(), [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 7, "method": "ping"},
    ])
    assert len(answers) == 1 and answers[0]["id"] == 7


def test_an_unknown_method_is_a_json_rpc_error():
    answer = mcp.handle_message(_ctx(), {"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
    assert answer["error"]["code"] == mcp.METHOD_NOT_FOUND


def test_something_that_is_not_json_rpc_is_refused():
    assert mcp.handle_message(_ctx(), {"id": 1, "method": "ping"})["error"]["code"] \
        == mcp.INVALID_REQUEST


def test_tools_call_without_a_name_is_an_invalid_params_error():
    answer = mcp.handle_message(_ctx(), {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                         "params": {}})
    assert answer["error"]["code"] == mcp.INVALID_PARAMS


# --- addresses the firewall must never be handed ----------------------------

@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
    "169.254.1.1", "0.0.0.0", "::1", "fe80::1",
])
def test_private_and_reserved_addresses_are_recognised(address):
    assert mcp.private_or_reserved(address) is True


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "163.61.72.88", "2606:4700::1111"])
def test_a_real_public_address_is_not(address):
    assert mcp.private_or_reserved(address) is False


# --- the endpoint's three gates, and the order they come in -----------------

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture
def addon_on(monkeypatch):
    from app.services import addons
    monkeypatch.setattr(addons, "is_installed", lambda slug: slug == addons.MCP)


def test_with_the_addon_off_the_endpoint_does_not_exist(client, monkeypatch):
    """404, not 401.

    An assistant pointed at a panel that has not turned this on should be told
    there is nothing here, rather than be asked for a credential that could
    never work. It also keeps the panel from advertising a feature the
    administrator chose not to run.
    """
    from app.services import addons
    monkeypatch.setattr(addons, "is_installed", lambda slug: False)

    answer = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         headers={"Authorization": "Bearer bpmcp_whatever"})
    assert answer.status_code == 404


def test_the_addon_is_checked_before_the_token(client, monkeypatch):
    """A wrong token against a disabled addon still gets 404, not 401."""
    from app.services import addons
    monkeypatch.setattr(addons, "is_installed", lambda slug: False)
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 404


def test_a_browser_that_was_tricked_into_posting_is_stopped(client, addon_on):
    """DNS rebinding: a page elsewhere making the browser talk to the panel.

    Checked before the token, so this is refused whether or not the attacker
    also managed to obtain one.
    """
    answer = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                         headers={"Origin": "https://evil.example",
                                  "Authorization": "Bearer bpmcp_whatever"})
    assert answer.status_code == 403


def test_a_real_mcp_client_sends_no_origin_and_is_fine(client, addon_on):
    """It gets as far as the token check, which is the next gate."""
    answer = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert answer.status_code == 401


def test_a_missing_or_wrong_token_asks_for_one(client, addon_on):
    for headers in ({}, {"Authorization": "Bearer bpmcp_not_a_real_token"},
                    {"Authorization": "Basic abc"}):
        answer = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                             headers=headers)
        assert answer.status_code == 401
        assert "Bearer" in answer.headers.get("www-authenticate", "")


def test_there_is_no_stream_to_get(client, addon_on):
    """Plain-JSON Streamable HTTP: no SSE, no sessions, so no GET and no DELETE."""
    for call in (client.get, client.delete):
        answer = call("/api/mcp")
        assert answer.status_code == 405
        assert answer.headers.get("allow") == "POST"


# --- the tools themselves ---------------------------------------------------

@pytest.fixture
def tools():
    """The real registry, as the endpoint sees it."""
    return mcp.REGISTRY


def test_every_tool_tells_the_assistant_when_to_use_it(tools):
    """The description is the only thing steering the model's choice.

    A one-word description produces a model that calls the wrong tool and then
    reports the wrong answer confidently, which is worse than no tool at all.
    """
    for name, spec in tools.items():
        assert len(spec.description) >= 40, f"{name} needs a real description"
        assert spec.title, name


def test_every_argument_is_described_and_bounded(tools):
    """An unbounded string or integer is an argument the model will misuse."""
    for name, spec in tools.items():
        for arg, rule in spec.properties.items():
            assert "type" in rule, f"{name}.{arg} has no type"
            if rule["type"] == "string" and "enum" not in rule:
                assert "maxLength" in rule, f"{name}.{arg} is an unbounded string"
            if rule["type"] == "integer":
                assert "minimum" in rule and "maximum" in rule, \
                    f"{name}.{arg} is an unbounded integer"


def test_no_read_only_tool_claims_to_write(tools):
    for name, spec in tools.items():
        if name.startswith(("list_", "read_", "whoami", "server_")):
            assert not spec.writes, f"{name} reads, and must not be marked as writing"


def test_the_administrative_tools_are_the_ones_you_would_expect(tools):
    """A tool wrongly left off this list is one a customer can reach."""
    assert {name for name, spec in tools.items() if spec.admin_only} == {
        "list_users", "list_services", "list_backup_schedules",
        "recent_audit_log", "panel_update_status",
        "list_firewall_rules", "list_waf_rules",
    }


# --- addressing a website by domain -----------------------------------------

class _WebsiteQuery:
    def __init__(self, rows, owner_filtered=None):
        self._rows = rows
        self.filters = 0
        self.owner_filtered = owner_filtered

    def filter(self, *args):
        self.filters += 1
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _WebsiteSession(_Session):
    def __init__(self, rows):
        super().__init__()
        self.query_obj = _WebsiteQuery(rows)

    def query(self, model):
        return self.query_obj


def test_someone_elses_domain_reads_as_not_existing():
    """Never "forbidden" - that confirms the domain is real.

    A customer's assistant must not be able to map the server by trying
    domains and reading which answer comes back.
    """
    ctx = mcp.Context(db=_WebsiteSession([]), user=_user(role=Role.end_user), token=_token())
    with pytest.raises(mcp.ToolError) as exc:
        mcp_tools._website(ctx, "someone-else.test")
    message = str(exc.value)
    assert "No website named someone-else.test" in message
    assert "permission" not in message.lower() and "forbidden" not in message.lower()


def test_a_customer_lookup_is_narrowed_to_their_own_websites():
    """Two filters for a customer, one for an administrator."""
    customer = mcp.Context(db=_WebsiteSession([]), user=_user(role=Role.end_user), token=_token())
    with pytest.raises(mcp.ToolError):
        mcp_tools._website(customer, "a.test")
    assert customer.db.query_obj.filters == 2, "domain, and owner"

    admin = mcp.Context(db=_WebsiteSession([]), user=_user(role=Role.admin), token=_token())
    with pytest.raises(mcp.ToolError):
        mcp_tools._website(admin, "a.test")
    assert admin.db.query_obj.filters == 1, "domain only"


@pytest.mark.parametrize("given,wanted", [
    ("Example.TEST", "example.test"),
    ("  example.test  ", "example.test"),
    (".example.test", "example.test"),
])
def test_a_domain_is_tidied_before_it_is_looked_up(given, wanted, monkeypatch):
    """Models paste domains with a stray dot or capital in them."""
    seen = {}

    class _Recording(_WebsiteQuery):
        def filter(self, *args):
            seen.setdefault("args", args)
            return self

    session = _WebsiteSession([])
    session.query_obj = _Recording([])
    ctx = mcp.Context(db=session, user=_user(), token=_token())
    with pytest.raises(mcp.ToolError) as exc:
        mcp_tools._website(ctx, given)
    assert wanted in str(exc.value)


def test_an_empty_domain_says_so_rather_than_searching():
    ctx = mcp.Context(db=_WebsiteSession([]), user=_user(), token=_token())
    with pytest.raises(mcp.ToolError) as exc:
        mcp_tools._website(ctx, "   ")
    assert "domain is required" in str(exc.value)


# --- reading a file ---------------------------------------------------------

def test_a_long_file_is_truncated_and_admits_it(monkeypatch):
    """A 40 MB log would otherwise fill the assistant's context and end the session."""
    from app.api import maintenance as maintenance_api
    content = "\n".join(f"line {n}" for n in range(5000))
    monkeypatch.setattr(mcp_tools, "_website",
                        lambda ctx, domain: type("W", (), {"id": 1})())
    monkeypatch.setattr(maintenance_api, "read_file",
                        lambda **kwargs: {"content": content})

    result = mcp.REGISTRY["read_file"].handler(
        _ctx(), {"domain": "a.test", "path": "wp-config.php"})
    assert result["truncated"] is True
    assert result["total_lines"] == 5000
    assert result["lines"] == mcp_tools.MAX_READ_LINES
    assert result["content"].count("\n") == mcp_tools.MAX_READ_LINES - 1
    assert "2000 of 5000" in result["note"]


def test_a_short_file_comes_back_whole(monkeypatch):
    from app.api import maintenance as maintenance_api
    monkeypatch.setattr(mcp_tools, "_website",
                        lambda ctx, domain: type("W", (), {"id": 1})())
    monkeypatch.setattr(maintenance_api, "read_file",
                        lambda **kwargs: {"content": "one\ntwo\nthree"})

    result = mcp.REGISTRY["read_file"].handler(_ctx(), {"domain": "a.test", "path": "x.txt"})
    assert result["truncated"] is False and result["content"] == "one\ntwo\nthree"


# --- whoami -----------------------------------------------------------------

def test_whoami_says_plainly_what_this_token_can_do():
    admin = mcp.REGISTRY["whoami"].handler(
        _ctx(user=_user(role=Role.admin), token=_token(can_write=True)), {})
    assert admin["role"] == "administrator" and admin["can_make_changes"] is True

    customer = mcp.REGISTRY["whoami"].handler(
        _ctx(user=_user(role=Role.end_user), token=_token(can_write=False)), {})
    assert customer["role"] == "hosting customer"
    assert customer["can_make_changes"] is False
    assert "only websites owned by this account" in customer["scope"]


def test_whoami_never_leaks_the_token_itself():
    answer = mcp.REGISTRY["whoami"].handler(_ctx(), {})
    assert "token" not in str(answer).lower().replace("token_name", "").replace("token_expires_at", "")


# --- searching a website's files --------------------------------------------

@pytest.fixture
def site(tmp_path):
    """A website root with the shapes a real one has."""
    root = tmp_path / "site"
    (root / "wp-content" / "themes").mkdir(parents=True)
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "wp-content" / "uploads" / "2026").mkdir(parents=True)
    (root / ".git").mkdir()

    (root / "wp-config.php").write_text("<?php\ndefine('DB_NAME', 'shop');\n", encoding="utf-8")
    (root / "wp-content" / "themes" / "style.css").write_text(
        "/* shop theme */\nbody{}\n", encoding="utf-8")
    # The three that must never be walked into or read.
    (root / "node_modules" / "left-pad" / "index.js").write_text("shop", encoding="utf-8")
    (root / ".git" / "config").write_text("shop", encoding="utf-8")
    (root / "wp-content" / "uploads" / "2026" / "note.txt").write_text("shop", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n" + bytes([0]) + b"shop")
    (root / "huge.log").write_bytes(b"shop\n" * 200_000)

    return type("W", (), {"root_path": str(root), "domain": "shop.test"})()


def test_search_finds_the_file_and_the_line(site):
    found = file_manager.search_text(site, "DB_NAME")
    assert [m["path"] for m in found["matches"]] == ["wp-config.php"]
    assert found["matches"][0]["line"] == 2
    assert "shop" in found["matches"][0]["text"]
    assert found["complete"] is True


def test_search_never_walks_into_the_directories_that_make_it_useless(site):
    """node_modules, .git and uploads all contain the word and must not appear.

    Without pruning, one question against a WordPress site reads a dependency
    tree and a customer's media library, takes minutes, and answers with
    nothing anybody wanted.
    """
    found = file_manager.search_text(site, "shop")
    paths = {m["path"] for m in found["matches"]}
    assert not any(p.startswith(("node_modules/", ".git/")) for p in paths), paths
    assert not any("uploads/" in p for p in paths), paths
    assert "wp-config.php" in paths


def test_a_binary_file_is_skipped_rather_than_pasted_into_the_answer(site):
    found = file_manager.search_text(site, "shop")
    assert not any(m["path"] == "logo.png" for m in found["matches"])
    assert found["skipped_binary"] >= 1


def test_a_file_too_large_to_be_a_config_is_skipped(site):
    """A megabyte log is not where a configuration string lives."""
    found = file_manager.search_text(site, "shop")
    assert not any(m["path"] == "huge.log" for m in found["matches"])
    assert found["skipped_too_large"] >= 1


def test_stopping_early_is_reported_rather_than_looking_like_the_whole_answer(site):
    """"Not found" and "gave up" must not look the same to an assistant."""
    found = file_manager.search_text(site, "shop", max_matches=1)
    assert len(found["matches"]) == 1
    assert found["complete"] is False
    assert "Stopped" in found["note"]


def test_searching_for_nothing_is_refused(site):
    for bad in ("", "   "):
        with pytest.raises(ValueError):
            file_manager.search_text(site, bad)


def test_search_cannot_be_pointed_outside_the_website(site):
    for escape in ("../..", "/etc", "wp-content/../../.."):
        with pytest.raises(ValueError):
            file_manager.search_text(site, "shop", relative_path=escape)


# --- summarising traffic ----------------------------------------------------

def test_the_summary_counts_rather_than_returning_rows(monkeypatch):
    """An assistant asked who is hammering a site wants the shape, not 500 rows.

    Handing it the rows spends the operator's tokens on arithmetic and gets
    ties wrong.
    """
    from app.services import waf

    entries = (
        [("1.2.3.4", "/wp-login.php", 403, "block", "Vietnam")] * 30
        + [("5.6.7.8", "/", 200, "allow", "Germany")] * 10
        + [("9.9.9.9", "/", 200, "allow", "Germany")] * 5
    )

    def fake_parse(domain, line, sequence):
        index = int(line)
        ip, path, status, verdict, country = entries[index]
        return (datetime(2026, 9, 24, 0, index % 60), {
            "ip": ip, "path": path, "status": status, "verdict": verdict,
            "country": country, "timestamp": f"2026-09-24T00:00:{index % 60:02d}",
        })

    monkeypatch.setattr(waf, "_validate_domain", lambda d: d)
    monkeypatch.setattr(waf, "_read_site_logs",
                        lambda domains, lines: {"shop.test": "\n".join(str(i) for i in range(len(entries)))})
    monkeypatch.setattr(waf, "_parse_access_log_line", fake_parse)

    summary = waf.access_summary([type("W", (), {"domain": "shop.test"})()], top=2)

    assert summary["requests"] == 45
    assert summary["verdicts"] == {"allow": 15, "block": 30}
    assert summary["top_ips"][0] == {"ip": "1.2.3.4", "requests": 30}
    assert summary["most_blocked_ips"] == [{"ip": "1.2.3.4", "requests": 30}]
    assert len(summary["top_ips"]) == 2, "top is respected"
    assert summary["top_paths"][0]["path"] == "/wp-login.php"


def test_the_summary_is_stable_when_counts_tie(monkeypatch):
    """A summary that reshuffles on ties reads as a change that did not happen."""
    from app.services import waf

    def fake_parse(domain, line, sequence):
        return (datetime(2026, 9, 24), {
            "ip": line, "path": "/", "status": 200, "verdict": "allow",
            "country": "", "timestamp": "2026-09-24T00:00:00",
        })

    monkeypatch.setattr(waf, "_validate_domain", lambda d: d)
    monkeypatch.setattr(waf, "_read_site_logs",
                        lambda domains, lines: {"a.test": "9.9.9.9\n1.1.1.1\n5.5.5.5"})
    monkeypatch.setattr(waf, "_parse_access_log_line", fake_parse)

    site = type("W", (), {"domain": "a.test"})()
    first = waf.access_summary([site])["top_ips"]
    second = waf.access_summary([site])["top_ips"]
    assert first == second
    assert [row["ip"] for row in first] == ["1.1.1.1", "5.5.5.5", "9.9.9.9"]


def test_a_site_with_no_log_yet_is_named_not_silently_dropped(monkeypatch):
    from app.services import waf

    monkeypatch.setattr(waf, "_validate_domain", lambda d: d)
    monkeypatch.setattr(waf, "_read_site_logs", lambda domains, lines: {"new.test": None})

    summary = waf.access_summary([type("W", (), {"domain": "new.test"})()])
    assert summary["no_log_yet"] == ["new.test"]
    assert summary["requests"] == 0
