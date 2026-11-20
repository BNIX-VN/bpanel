import contextlib
from datetime import datetime
import os
from pathlib import Path
import re
import secrets
import string
import subprocess
import tempfile
from typing import Dict

from app.core.config import settings
from app.services.shell import shell


IDENTIFIER_CHARS = set(string.ascii_lowercase + string.digits + "_")


def random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%^*_+-"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def safe_db_identifier(domain: str, prefix: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in domain.lower())[:38]
    return f"{prefix}_{clean}"[:63]


def _validate_identifier(value: str) -> str:
    if not value or len(value) > 64 or any(ch not in IDENTIFIER_CHARS for ch in value):
        raise ValueError("Invalid database identifier")
    return value


# MariaDB's own accounts, plus the one the panel authenticates as. Creating a
# database must never touch any of them, on any code path - not even a restore.
RESERVED_DB_USERS = frozenset({
    "root",
    "mysql",
    "mariadb.sys",
    "debian-sys-maint",
    "bpanel",
})


def _reject_reserved_user(db_user: str) -> None:
    if db_user.strip().lower() in RESERVED_DB_USERS:
        raise ValueError(f"'{db_user}' is a reserved MariaDB account and cannot be used for a website database")


def user_exists(db_user: str) -> bool:
    """Whether this MariaDB account already exists.

    Asked of MariaDB rather than of BPanel's own table: the whole point is to
    notice accounts BPanel does not know about, which is exactly what the
    table cannot tell us.
    """
    safe = _validate_identifier(db_user)
    result = _run_sql(
        f"SELECT 1 FROM mysql.user WHERE user = {_quote_sql_string(safe)} LIMIT 1;\n",
        check=False,
    )
    return "1" in (result.stdout or "")


def _quote_sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return f"`{_validate_identifier(value)}`"


_NATIVE_PASSWORD_HASH_RE = re.compile(r"^\*[0-9A-Fa-f]{40}$")


def _auth_clause(db_password: str, password_hash: str | None) -> str:
    """The IDENTIFIED ... clause for CREATE/ALTER USER.

    When a mysql_native_password hash is given (DirectAdmin keeps the original
    in its <db>.conf), the user is recreated with that exact hash so the
    imported site's existing config keeps working untouched. The hash is a
    fixed shape (``*`` + 40 hex) and is validated before it reaches any SQL.
    """
    if password_hash:
        if not _NATIVE_PASSWORD_HASH_RE.match(password_hash):
            raise ValueError("Invalid mysql_native_password hash")
        return f"IDENTIFIED VIA mysql_native_password USING '{password_hash}'"
    return f"IDENTIFIED BY {_quote_sql_string(db_password)}"


def _mysql_args(extra: list = None) -> list:
    args = ["mysql"]
    home_cnf = Path.home() / ".my.cnf"
    if home_cnf.exists():
        args.append(f"--defaults-file={home_cnf}")
    if extra:
        args.extend(extra)
    return args


def _run_sql(sql: str, *, check: bool = True):
    """Pipe SQL through stdin so secrets never appear in argv/ps output."""
    return shell.run(_mysql_args(), check=check, input=sql, sensitive=True)


def create_database(seed: str, prefix: str = "wp", db_name: str | None = None, if_not_exists: bool = True) -> Dict[str, str]:
    db_name = _validate_identifier(db_name or safe_db_identifier(seed, prefix))
    db_user = _validate_identifier(safe_db_identifier(db_name, "u"))
    _reject_reserved_user(db_user)
    db_password = random_password()
    create_clause = "CREATE DATABASE IF NOT EXISTS" if if_not_exists else "CREATE DATABASE"
    sql = (
        f"{create_clause} {_quote_identifier(db_name)} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
        f"CREATE USER IF NOT EXISTS {_quote_sql_string(db_user)}@'localhost' IDENTIFIED BY {_quote_sql_string(db_password)};\n"
        f"ALTER USER {_quote_sql_string(db_user)}@'localhost' IDENTIFIED BY {_quote_sql_string(db_password)};\n"
        f"GRANT ALL PRIVILEGES ON {_grant_target(db_name)} TO {_quote_sql_string(db_user)}@'localhost';\n"
        "FLUSH PRIVILEGES;\n"
    )
    _run_sql(sql)
    return {"db_name": db_name, "db_user": db_user, "db_password": db_password}


def create_database_credentials(
    db_name: str, db_user: str, db_password: str, *, password_hash: str | None = None,
    allow_existing_user: bool = False,
) -> Dict[str, str]:
    """Create a database and the account that owns it.

    `CREATE USER IF NOT EXISTS` followed by an unconditional `ALTER USER` used
    to mean "create it, or take it over". Since the panel authenticates to
    MariaDB with ALL PRIVILEGES ON *.*, any panel user who asked for
    db_user=root got root's password reset to a value of their choosing - and
    the API handed it back in the response. On a stock Ubuntu box root is
    `IDENTIFIED VIA mysql_native_password USING 'invalid' OR unix_socket`, so
    the ALTER also drops the socket clause and locks the system's own root out
    of MariaDB.

    Creating now refuses an account that already exists. `allow_existing_user`
    is for the restore paths - a backup or a DirectAdmin import legitimately
    recreates the account that archive already owned - and even those cannot
    touch a reserved account.
    """
    db_name = _validate_identifier(db_name)
    db_user = _validate_identifier(db_user)
    _reject_reserved_user(db_user)

    if not allow_existing_user and user_exists(db_user):
        raise ValueError(
            f"MariaDB account '{db_user}' already exists. Choose another database user name."
        )

    auth = _auth_clause(db_password, password_hash)
    statements = [
        f"CREATE DATABASE IF NOT EXISTS {_quote_identifier(db_name)} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"CREATE USER IF NOT EXISTS {_quote_sql_string(db_user)}@'localhost' {auth};",
    ]
    if allow_existing_user:
        # Only a restore sets the password of an account that was already there.
        statements.append(f"ALTER USER {_quote_sql_string(db_user)}@'localhost' {auth};")
    statements += [
        f"GRANT ALL PRIVILEGES ON {_grant_target(db_name)} TO {_quote_sql_string(db_user)}@'localhost';",
        "FLUSH PRIVILEGES;",
    ]
    _run_sql("\n".join(statements) + "\n")
    return {"db_name": db_name, "db_user": db_user, "db_password": db_password}


def drop_database(db_name: str, db_user: str):
    _reject_reserved_user(_validate_identifier(db_user))
    sql = (
        f"DROP DATABASE IF EXISTS {_quote_identifier(db_name)};\n"
        f"DROP USER IF EXISTS {_quote_sql_string(_validate_identifier(db_user))}@'localhost';\n"
        "FLUSH PRIVILEGES;\n"
    )
    return _run_sql(sql)


def change_database_password(db_user: str, db_password: str):
    _reject_reserved_user(_validate_identifier(db_user))
    sql = (
        f"ALTER USER {_quote_sql_string(_validate_identifier(db_user))}@'localhost' "
        f"IDENTIFIED BY {_quote_sql_string(db_password)};\n"
        "FLUSH PRIVILEGES;\n"
    )
    return _run_sql(sql)


def export_database(db_name: str, output_file: str):
    args = ["mysqldump"]
    home_cnf = Path.home() / ".my.cnf"
    if home_cnf.exists():
        args.append(f"--defaults-file={home_cnf}")
    args.extend([_validate_identifier(db_name), "--result-file", output_file])
    return shell.run(args, sensitive=True)


def import_database(db_name: str, input_file: str):
    safe_name = _validate_identifier(db_name)
    sql_path = Path(input_file).resolve()
    if not sql_path.exists() or not sql_path.is_file():
        raise FileNotFoundError("SQL file not found")
    if settings.command_dry_run:
        return shell.run(["mysql", safe_name], sensitive=True)
    args = _mysql_args([safe_name])
    with sql_path.open("rb") as source:
        completed = subprocess.run(args, stdin=source, capture_output=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Database import failed: {stderr.strip()}")
    return completed


# --- Importing a dump that came out of an archive ------------------------------------
# import_database() runs as the panel's own account, which may do anything on
# the server, and `mysql <db>` only picks the default schema: a dump body can
# still GRANT, CREATE USER or touch another tenant's tables. A website backup
# can be one its owner uploaded, so its dump is loaded through an account that
# MariaDB itself confines to the one schema.
RESTORE_USER_PREFIX = "bprst_"


def _option_value(value: str) -> str:
    """A value as a MariaDB option file reads it back unchanged. Unquoted, a
    `#` starts a comment and cuts the rest off - and random_password() puts a
    `#` in about one password in three - so it is always quoted; the file
    unescapes backslashes in any value, so those are doubled."""
    if any(ch in value for ch in "\r\n\x00"):
        raise ValueError("Invalid database password")
    escaped = value.replace("\\", "\\\\")
    if '"' not in value:
        return f'"{escaped}"'
    if "'" not in value:
        return f"'{escaped}'"
    raise ValueError("A password with both kinds of quote cannot go in an option file")


@contextlib.contextmanager
def _client_defaults_file(db_user: str, db_password: str):
    """A 0600 [client] defaults-file for one account. The password stays out of
    argv: /proc/<pid>/cmdline is readable by every local user, every other
    tenant's PHP included."""
    safe_user = _validate_identifier(db_user)
    password = _option_value(db_password)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="bpanel-mysql-", suffix=".cnf", delete=False)
    try:
        os.chmod(handle.name, 0o600)
        handle.write(f"[client]\nuser={safe_user}\npassword={password}\nhost=localhost\n")
        handle.close()
        yield handle.name
    finally:
        with contextlib.suppress(OSError):
            os.unlink(handle.name)


def _import_as(db_user: str, db_password: str, db_name: str, sql_path: Path) -> subprocess.CompletedProcess:
    with _client_defaults_file(db_user, db_password) as defaults, sql_path.open("rb") as source:
        return subprocess.run(["mysql", f"--defaults-file={defaults}", db_name], stdin=source,
                              capture_output=True, check=False)


def _login_refused(completed: subprocess.CompletedProcess) -> bool:
    # ERROR 1045 (28000): Access denied - at connect, before any statement ran.
    return completed.returncode != 0 and b"ERROR 1045" in (completed.stderr or b"")


def import_database_scoped(db_name: str, input_file: str, *, db_user: str | None = None,
                           db_password: str | None = None) -> subprocess.CompletedProcess:
    """Load a SQL dump from an archive into ``db_name``, as an account limited
    to that schema.

    With the schema's own login (``db_user`` and its stored password), triggers
    and views that name that user as DEFINER come back as they were. A database
    imported from DirectAdmin has no password the panel knows, and a stored one
    can be stale: then a temporary login is made with rights on this schema
    only, and dropped afterwards.
    """
    safe_name = _validate_identifier(db_name)
    sql_path = Path(input_file).resolve()
    if not sql_path.exists() or not sql_path.is_file():
        raise FileNotFoundError("SQL file not found")
    if settings.command_dry_run:
        return shell.run(["mysql", safe_name], sensitive=True)
    completed = None
    if db_user and db_password:
        try:
            completed = _import_as(db_user, db_password, safe_name, sql_path)
        except ValueError:
            completed = None  # a name or password an option file cannot hold
    if completed is None or _login_refused(completed):
        user = RESTORE_USER_PREFIX + secrets.token_hex(5)
        # Hex only: nothing in it for the option file or SQL to read specially.
        password = secrets.token_hex(24)
        _run_sql(
            f"CREATE USER {_quote_sql_string(user)}@'localhost' IDENTIFIED BY {_quote_sql_string(password)};\n"
            f"GRANT ALL PRIVILEGES ON {_grant_target(safe_name)} TO {_quote_sql_string(user)}@'localhost';\n"
        )
        try:
            completed = _import_as(user, password, safe_name, sql_path)
        finally:
            _run_sql(f"DROP USER IF EXISTS {_quote_sql_string(user)}@'localhost';\n", check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"Database import failed: {stderr.strip()}")
    return completed


def dump_database_file(db_name: str, output_dir: Path) -> Path:
    safe_name = _validate_identifier(db_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{safe_name}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.sql"
    export_database(safe_name, str(target))
    if settings.command_dry_run and not target.exists():
        target.write_text(f"-- DRY RUN database dump for {safe_name}\n", encoding="utf-8")
    return target


# --- phpMyAdmin single sign-on --------------------------------------------------------
# A login of its own for each phpMyAdmin visit, rather than the website's: a
# database imported from DirectAdmin keeps its user's original password hash,
# so the panel never learns the password and had stored an empty one - and
# every phpMyAdmin sign-in to it failed (operator, 2026-10-16). A temporary
# user also keeps the site's real password out of phpMyAdmin's session.
SSO_USER_PREFIX = "bpsso_"
SSO_LOGIN_TTL_SECONDS = 8 * 3600
SSO_STATE_FILE = Path("/var/lib/bpanel/pma-sso-logins.json")


def _read_sso_state() -> dict:
    import json

    try:
        data = json.loads(SSO_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _write_sso_state(state: dict) -> None:
    import json
    import os

    SSO_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SSO_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(SSO_STATE_FILE)


def _grant_target(db_name: str) -> str:
    """`db`.* with LIKE wildcards escaped: unescaped, a database-level grant
    reads _ (and %) as wildcards, so `shop_db` would also cover `shopXdb`.
    Identifiers are [a-z0-9_]-restricted so only _ occurs in practice; % and \\
    are escaped too for safety."""
    escaped = _validate_identifier(db_name).replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
    return f"`{escaped}`.*"


def create_sso_login(db_name: str) -> tuple[str, str]:
    """A MariaDB login for one phpMyAdmin visit to one database."""
    import time

    drop_expired_sso_logins()
    user = SSO_USER_PREFIX + secrets.token_hex(5)
    password = random_password(32)
    _run_sql(
        f"CREATE USER {_quote_sql_string(user)}@'localhost' IDENTIFIED BY {_quote_sql_string(password)};\n"
        f"GRANT ALL PRIVILEGES ON {_grant_target(db_name)} TO {_quote_sql_string(user)}@'localhost';\n"
    )
    state = _read_sso_state()
    state[user] = time.time() + SSO_LOGIN_TTL_SECONDS
    _write_sso_state(state)
    return user, password


def drop_expired_sso_logins(drop_all: bool = False) -> int:
    """Drop the phpMyAdmin logins past their time, and any the state file lost
    track of. Run before each new one and on the scheduler's minute tick."""
    import time

    state = _read_sso_state()
    now = time.time()
    doomed = {user for user, expires in state.items() if drop_all or expires <= now}
    listed = shell.run(_mysql_args(["-N", "-B"]), check=False, sensitive=True,
                       input=f"SELECT user FROM mysql.user WHERE user LIKE {_quote_sql_string(SSO_USER_PREFIX + '%')};\n")
    for line in (listed.stdout or "").splitlines():
        user = line.strip()
        if user.startswith(SSO_USER_PREFIX) and user not in state:
            doomed.add(user)
    doomed = {user for user in doomed if user.startswith(SSO_USER_PREFIX) and all(ch in IDENTIFIER_CHARS for ch in user)}
    if not doomed:
        return 0
    _run_sql("".join(f"DROP USER IF EXISTS {_quote_sql_string(user)}@'localhost';\n" for user in sorted(doomed)), check=False)
    for user in doomed:
        state.pop(user, None)
    _write_sso_state(state)
    return len(doomed)
