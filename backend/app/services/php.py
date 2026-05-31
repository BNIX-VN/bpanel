from pathlib import Path

from app.core.config import settings
from app.schemas.schemas import PhpConfigUpdate
from app.services.shell import shell

SUPPORTED_PHP_VERSIONS = {"5.6", "7.4", "8.0", "8.1", "8.2", "8.3", "8.4"}


def _safe_ini_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("Invalid PHP ini value")
    return value


def update_php_ini(payload: PhpConfigUpdate) -> str:
    if payload.php_version not in SUPPORTED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version. Allowed: {sorted(SUPPORTED_PHP_VERSIONS)}")
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
    php_version = payload.php_version
    target = Path(f"/etc/php/{php_version}/fpm/conf.d/99-bpanel.ini")
    if settings.command_dry_run:
        return content
    target.write_text(content, encoding="utf-8")
    shell.privileged(
        "systemctl",
        helper_args=[f"php{php_version}-fpm", "restart"],
        fallback=["systemctl", "restart", f"php{php_version}-fpm"],
    )
    return str(target)


PHP_CONFIG_KEYS = {
    "display_errors": "Off",
    "memory_limit": "512M",
    "upload_max_filesize": "1024M",
    "post_max_size": "1024M",
    "max_execution_time": "300",
    "max_input_time": "600",
    "max_input_vars": "10000",
}


def read_php_ini(php_version: str) -> dict:
    if php_version not in SUPPORTED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version. Allowed: {sorted(SUPPORTED_PHP_VERSIONS)}")
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


def list_installed_php() -> list[str]:
    """List PHP versions that are currently installed on the system."""
    installed = []
    for version in SUPPORTED_PHP_VERSIONS:
        fpm_path = Path(f"/etc/php/{version}/fpm/php-fpm.conf")
        if fpm_path.exists():
            installed.append(version)
    return sorted(installed, key=lambda v: [int(x) for x in v.split(".")])


def install_php(php_version: str) -> dict:
    """Install a PHP version via apt."""
    if php_version not in SUPPORTED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version. Allowed: {sorted(SUPPORTED_PHP_VERSIONS)}")

    # Check if already installed
    for p in shell.run("ls -d /etc/php/*/fpm/php-fpm.conf 2>/dev/null || true").stdout.splitlines():
        if f"/etc/php/{php_version}/" in p:
            raise ValueError(f"PHP {php_version} is already installed")

    if settings.command_dry_run:
        return {"status": "dry_run", "message": f"Would install php{php_version}-fpm"}

    # Install PHP-FPM via bpanel-helper
    shell.privileged(
        "php-install",
        helper_args=[php_version],
        fallback=["apt-get", "install", "-y", f"php{php_version}-fpm", f"php{php_version}-cli", f"php{php_version}-mysql", f"php{php_version}-curl", f"php{php_version}-gd", f"php{php_version}-mbstring", f"php{php_version}-xml", f"php{php_version}-zip", f"php{php_version}-bcmath"],
    )
    return {"status": "installed", "version": php_version}
