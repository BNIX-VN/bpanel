"""Terminal entitlement and sandboxing — issue #119 (BPANEL-2026-001/002)."""

import pytest
from fastapi import HTTPException

from app.api import terminal as terminal_api


class _User:
    def __init__(self, role="end_user", terminal_enabled=False, user_id=2):
        self.role = role
        self.terminal_enabled = terminal_enabled
        self.id = user_id


def test_an_end_user_without_the_entitlement_is_refused():
    """UserPackage.terminal_enabled existed but nothing read it.

    Both terminal doors checked website ownership only, so any end user could
    open a shell on their own site regardless of the package they were paying
    for. Hiding the button in the frontend is not access control - curl with a
    valid session cookie reached the same endpoint.
    """
    assert terminal_api.may_use_terminal(_User(terminal_enabled=False)) is False


def test_an_end_user_with_the_entitlement_is_allowed():
    assert terminal_api.may_use_terminal(_User(terminal_enabled=True)) is True


def test_an_admin_always_may():
    # Admins administer the server; the entitlement is a per-package sales
    # boundary, not a security boundary against the operator.
    assert terminal_api.may_use_terminal(_User(role="admin", terminal_enabled=False)) is True


def test_the_rest_endpoint_refuses_before_touching_the_site():
    """The check has to live in get_user_website, which /exec goes through.

    Driven with asyncio.run rather than pytest-asyncio: the suite has no async
    plugin and one coroutine is not worth adding a dependency for.
    """
    import asyncio

    class _Website:
        id = 1
        owner_id = 2
        linux_user = "client"

    class _Query:
        def filter(self, *_a):
            return self

        def first(self):
            return _Website()

    class _DB:
        def query(self, *_a):
            return _Query()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(terminal_api.get_user_website(1, _DB(), _User(terminal_enabled=False)))

    assert exc.value.status_code == 403
    assert "not enabled" in str(exc.value.detail).lower()


def test_assigning_a_package_copies_its_terminal_flag():
    """The flag is copied onto the user, the way website_limit already is, so
    enforcement reads one column and a user without a package still resolves."""
    from app.api.users import _apply_package_limits

    class _Package:
        id = 1
        website_limit = 10
        storage_limit_mb = 2048
        terminal_enabled = True

    class _Target:
        package_id = None
        website_limit = 5
        storage_limit_mb = 1024
        terminal_enabled = False

    user = _Target()
    _apply_package_limits(user, _Package())

    assert user.terminal_enabled is True


def test_php_run_through_the_terminal_is_confined_to_the_tenant():
    """BPANEL-2026-002: PHP CLI from the terminal had no open_basedir at all.

    The FPM pool for the same site has always had one; the terminal is a
    separate pipeline and was missed. Because it runs as the site user and site
    files are world-readable by design, `php -r "readfile('/home/other/...')"`
    read another customer's files. Confirmed against a running server before
    the fix - it printed /etc/passwd.

    Asserted against the shipped helper rather than a copy, so the guarantee
    cannot drift away from what actually runs.
    """
    from pathlib import Path

    helper = Path(__file__).resolve().parents[3] / "installer" / "files" / "bpanel-helper.sh"
    script = helper.read_text(encoding="utf-8")

    start = script.index("  terminal-exec)")
    end = script.index("  nginx-upgrade-map-ensure)", start)
    block = script[start:end]

    # The value is built once from the tenant's home, not a single site root:
    # a customer with several sites still has to work across their own. It now
    # lives in one shared function because the terminal was not the only
    # pipeline that starts a PHP CLI as a site user - wp-site and cron both
    # did, unconfined, for as long as this assertion only looked in here.
    assert 'site_open_basedir() {' in script
    assert '"$HOME_ROOT/$user:/var/lib/php/sessions/$user:' in script
    assert 'terminal_open_basedir="$(site_open_basedir "$user")"' in block

    # Every PHP entry point uses it. node/npm/npx/yarn/git are deliberately
    # absent: open_basedir is a PHP mechanism and does nothing for them.
    for line in block.splitlines():
        if '"$php_bin"' in line and line.strip().startswith("exec "):
            assert "open_basedir" in line, f"unconfined PHP invocation: {line.strip()[:90]}"


def test_wp_site_runs_under_the_same_confinement_as_the_terminal():
    """The verb the terminal's own guarantee did not cover.

    wp-site execs WP-CLI as the site user, and WP-CLI bootstraps that install's
    wp-config.php and active plugins - tenant-authored PHP. It carried no
    open_basedir while the terminal's near-identical wp branch set it twice.
    The old assertion above could not see it, because it sliced the helper down
    to the terminal-exec block first.
    """
    from pathlib import Path

    helper = Path(__file__).resolve().parents[3] / "installer" / "files" / "bpanel-helper.sh"
    script = helper.read_text(encoding="utf-8")

    start = script.index("  wp-site)")
    end = script.index("  cron-list)", start)
    block = script[start:end]

    assert "site_open_basedir" in block, "wp-site must use the shared confinement"
    # Both halves: WP-CLI honours WP_CLI_PHP_ARGS for the PHP it spawns, and the
    # interpreter flags cover the phar bootstrap itself.
    assert "WP_CLI_PHP_ARGS=" in block and "open_basedir=" in block

    # The exec wraps across lines, so join backslash continuations before
    # scanning - otherwise this reads only the first physical line and passes
    # on a command whose confinement sits on the next one.
    joined = block.replace("\\\n", " ")
    for line in joined.splitlines():
        if line.strip().startswith("exec runuser"):
            assert "open_basedir" in line, f"unconfined WP-CLI: {line.strip()[:90]}"


def test_terminal_command_execution_does_not_block_the_event_loop():
    """BPANEL: one tenant must not be able to stall the whole control panel.

    Both terminal doors are `async def`, so FastAPI runs them ON the event
    loop rather than in the threadpool. terminal.exec_command is subprocess.run
    with a timeout of up to 915s for composer/npm/git/curl and friends, and
    serve.py runs a single uvicorn worker with no `workers` option - so calling
    it inline froze every other tenant's request, the admin UI and /auth/login
    for that whole time. `curl <host-that-never-answers>` was enough.

    17 of 18 API modules use plain `def` and get the threadpool for free;
    terminal.py is the outlier that has to ask for it.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "api" / "terminal.py"
    ).read_text(encoding="utf-8")

    assert "from starlette.concurrency import run_in_threadpool" in source

    # Every call to the blocking helper must go through the threadpool.
    for line_no, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("result = terminal.exec_command("):
            raise AssertionError(
                f"terminal.py:{line_no} calls exec_command inline on the event "
                "loop; wrap it in run_in_threadpool"
            )

    assert source.count("run_in_threadpool(\n        terminal.exec_command,") + source.count(
        "run_in_threadpool(\n                    terminal.exec_command,"
    ) == 2, "both the REST door and the WebSocket door must offload"
