from pathlib import Path

from app.core.config import settings
from app.schemas.schemas import PhpConfigUpdate
from app.services.shell import shell

SUPPORTED_PHP_VERSIONS = ("5.6", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4", "8.5")


def _safe_ini_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("Invalid PHP ini value")
    return value


def update_php_ini(payload: PhpConfigUpdate) -> str:
    php_version = payload.php_version
    if php_version not in SUPPORTED_PHP_VERSIONS:
        allowed = ", ".join(sorted(SUPPORTED_PHP_VERSIONS))
        raise ValueError(f"Unsupported PHP version. Allowed: {allowed}")
    display_errors = "On" if str(payload.display_errors).lower() in {"1", "true", "on", "yes"} else "Off"
    content = "\n".join([
        f"display_errors = {display_errors}",
        f"memory_limit = {_safe_ini_value(payload.memory_limit)}",
        f"upload_max_filesize = {_safe_ini_value(payload.upload_max_filesize)}",
        f"post_max_size = {_safe_ini_value(payload.post_max_size)}",
        f"max_execution_time = {int(payload.max_execution_time)}",
        f"max_input_time = {int(payload.max_input_time)}",
        f"max_input_vars = {int(payload.max_input_vars)}",
        "",
    ])
    target = Path(f"/etc/php/{php_version}/fpm/conf.d/99-bpanel.ini")
    if settings.command_dry_run:
        return content
    shell.privileged(
        "php-config-write",
        helper_args=[php_version],
        input=content,
        fallback=[
            "bash",
            "-lc",
            "cat > /etc/php/$1/fpm/conf.d/99-bpanel.ini && systemctl restart php$1-fpm",
            "bpanel-php-config-write",
            php_version,
        ],
    )
    return str(target)


PHP_CONFIG_KEYS = {
    "display_errors": "Off",
    "memory_limit": "1024M",
    "upload_max_filesize": "1024M",
    "post_max_size": "1024M",
    "max_execution_time": "300",
    "max_input_time": "600",
    "max_input_vars": "10000",
}


def default_php_config(php_version: str) -> dict:
    if php_version not in SUPPORTED_PHP_VERSIONS:
        allowed = ", ".join(sorted(SUPPORTED_PHP_VERSIONS))
        raise ValueError(f"Unsupported PHP version. Allowed: {allowed}")
    return {
        "php_version": php_version,
        "display_errors": PHP_CONFIG_KEYS["display_errors"],
        "memory_limit": PHP_CONFIG_KEYS["memory_limit"],
        "upload_max_filesize": PHP_CONFIG_KEYS["upload_max_filesize"],
        "post_max_size": PHP_CONFIG_KEYS["post_max_size"],
        "max_execution_time": int(PHP_CONFIG_KEYS["max_execution_time"]),
        "max_input_time": int(PHP_CONFIG_KEYS["max_input_time"]),
        "max_input_vars": int(PHP_CONFIG_KEYS["max_input_vars"]),
    }


def restore_default_php_ini(php_version: str) -> str:
    return update_php_ini(PhpConfigUpdate(**default_php_config(php_version)))


def read_php_ini(php_version: str) -> dict:
    if php_version not in SUPPORTED_PHP_VERSIONS:
        allowed = ", ".join(sorted(SUPPORTED_PHP_VERSIONS))
        raise ValueError(f"Unsupported PHP version. Allowed: {allowed}")
    values = dict(PHP_CONFIG_KEYS)
    for path in [
        Path(f"/etc/php/{php_version}/fpm/php.ini"),
        Path(f"/etc/php/{php_version}/fpm/conf.d/99-bpanel.ini"),
    ]:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith(";") or "=" not in line:
                continue
            key, value = [part.strip() for part in line.split("=", 1)]
            if key in values:
                values[key] = value
    values["php_version"] = php_version
    values["max_execution_time"] = int(values["max_execution_time"])
    values["max_input_time"] = int(values["max_input_time"])
    values["max_input_vars"] = int(values["max_input_vars"])
    return values


# The extensions the PHP config page offers, one apt package each
# (php<version>-<name>). The helper keeps the same list and enforces it.
PHP_EXTENSIONS = tuple("apcu bcmath bz2 curl enchant gd gmp igbinary imagick imap intl ldap mailparse mbstring memcached mongodb msgpack mysql opcache pgsql redis soap sqlite3 ssh2 tidy uuid xml xsl yaml zip".split())

# `php -m` names where they differ from the package: php-mysql brings mysqli
# and pdo_mysql, php-xml brings dom and friends, and OPcache is built into
# PHP 8.5 with no package of its own.
_MODULE_NAMES = {
    "mysql": ("mysqli",),
    "xml": ("dom",),
    "opcache": ("zend opcache",),
}


def _command_output(args: list[str]) -> str:
    try:
        result = shell.run(args, check=False, timeout=30)
    except (OSError, ValueError):  # no dpkg / php on a development machine
        return ""
    return result.stdout or ""


def list_extensions() -> dict:
    """Every offered extension against every installed PHP version.

    A cell is "installed" (its package is), "builtin" (PHP loads the module
    without a package, OPcache on 8.5), "available" (the repository has it)
    or "unavailable". Read-only, and needs no root: dpkg-query, apt-cache and
    php -m are open to anyone.
    """
    versions = list_installed_php()
    installed = set()
    for line in _command_output(["dpkg-query", "-W", "-f=${Package}\t${Status}\n", "php*"]).splitlines():
        package, _, status = line.partition("\t")
        if status == "install ok installed":
            installed.add(package)
    available = set(_command_output(["apt-cache", "pkgnames", "php"]).split())
    modules = {
        version: {line.strip().lower() for line in _command_output([f"php{version}", "-m"]).splitlines()}
        for version in versions
    }
    rows = []
    for ext in PHP_EXTENSIONS:
        states = {}
        for version in versions:
            package = f"php{version}-{ext}"
            if package in installed:
                states[version] = "installed"
            elif any(name in modules[version] for name in _MODULE_NAMES.get(ext, (ext,))):
                states[version] = "builtin"
            elif package in available:
                states[version] = "available"
            else:
                states[version] = "unavailable"
        rows.append({"name": ext, "versions": states})
    return {"versions": versions, "extensions": rows}


def install_extension(php_version: str, extension: str) -> str:
    """Install one offered extension for an installed PHP version.

    apt, then a PHP-FPM reload so sites load it at once. Raises ValueError for
    anything the panel does not offer, RuntimeError when apt or PHP refuse.
    """
    # What reaches the command line is the panel's own constant, picked by the
    # request's value, never the request's string itself - and there is no
    # shell anywhere on the way.
    version = next((v for v in SUPPORTED_PHP_VERSIONS if v == php_version), None)
    name = next((e for e in PHP_EXTENSIONS if e == extension), None)
    if name is None:
        raise ValueError("PHP extension not offered by the panel")
    if version is None or version not in list_installed_php():
        raise ValueError("That PHP version is not installed")
    package = f"php{version}-{name}"
    result = shell.privileged(
        "php-ext-install",
        helper_args=[version, name],
        check=False,
        timeout=600,
        fallback=["apt-get", "install", "-y", package],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"Could not install {package}").strip()[-600:])
    return (result.stdout or "").strip()


def list_installed_php() -> list[str]:
    """List PHP versions that are currently installed on the system."""
    installed = []
    for version in SUPPORTED_PHP_VERSIONS:
        fpm_path = Path(f"/etc/php/{version}/fpm/php-fpm.conf")
        if fpm_path.exists():
            installed.append(version)
    return sorted(installed, key=lambda v: [int(x) for x in v.split(".")])


def install_php(php_version: str) -> dict:
    """Install a PHP version or repair the BPanel extension set via apt."""
    if php_version not in SUPPORTED_PHP_VERSIONS:
        allowed = ", ".join(sorted(SUPPORTED_PHP_VERSIONS))
        raise ValueError(f"Unsupported PHP version. Allowed: {allowed}")

    already_installed = Path(f"/etc/php/{php_version}/fpm/php-fpm.conf").exists()

    if settings.command_dry_run:
        action = "repair" if already_installed else "install"
        return {"status": "dry_run", "message": f"Would {action} php{php_version} and BPanel extensions"}

    result = shell.privileged(
        "php-install",
        helper_args=[php_version],
        fallback=[
            "apt-get",
            "install",
            "-y",
            f"php{php_version}-fpm",
            f"php{php_version}-cli",
            f"php{php_version}-mysql",
            f"php{php_version}-sqlite3",
            f"php{php_version}-curl",
            f"php{php_version}-gd",
            f"php{php_version}-mbstring",
            f"php{php_version}-xml",
            f"php{php_version}-zip",
            f"php{php_version}-opcache",
            f"php{php_version}-intl",
            f"php{php_version}-bcmath",
            f"php{php_version}-redis",
            f"php{php_version}-imagick",
            f"php{php_version}-imap",
        ],
    )
    return {"status": "ensured" if already_installed else "installed", "version": php_version, "output": result.stdout}
