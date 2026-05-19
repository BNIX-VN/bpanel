from app.services.shell import shell

SUPPORTED_SERVICES = {"nginx", "php8.3-fpm", "php8.4-fpm", "mariadb", "redis-server", "filebrowser"}
SUPPORTED_ACTIONS = {"start", "stop", "restart", "reload", "status"}


def service_action(name: str, action: str):
    if name not in SUPPORTED_SERVICES:
        raise ValueError("Unsupported service")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("Unsupported action")
    if action == "status":
        # Status is read-only; non-privileged user can call systemctl status fine.
        return shell.run(["systemctl", action, name], check=False)
    return shell.privileged(
        "systemctl",
        helper_args=[name, action],
        check=False,
        fallback=["systemctl", action, name],
    )


def system_info() -> dict:
    os_info = shell.run(["bash", "-lc", "cat /etc/os-release | head -20"], check=False)
    disk = shell.run(["df", "-h", "/"], check=False)
    memory = shell.run(["free", "-m"], check=False)
    return {"os": os_info.stdout, "disk": disk.stdout, "memory": memory.stdout}


def install_wordpress_stack():
    raise PermissionError(
        "Installing the system stack from the panel is disabled. "
        "Run installer/install.sh on the server instead."
    )
