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
from app.services import mcp


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
