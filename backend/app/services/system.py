from app.services.shell import shell

SUPPORTED_SERVICES = {"nginx", "php8.3-fpm", "php8.4-fpm", "php8.5-fpm", "mariadb", "redis-server", "redis", "filebrowser", "ufw"}
SUPPORTED_ACTIONS = {"start", "stop", "restart", "reload", "status", "enable", "disable"}


def service_action(name: str, action: str):
    if name not in SUPPORTED_SERVICES:
        raise ValueError("Unsupported service")
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("Unsupported action")
    return shell.run(["systemctl", action, name], check=False)


def system_info() -> dict:
    os_info = shell.run(["bash", "-lc", "cat /etc/os-release | head -20"], check=False)
    disk = shell.run(["df", "-h", "/"], check=False)
    memory = shell.run(["free", "-m"], check=False)
    return {"os": os_info.stdout, "disk": disk.stdout, "memory": memory.stdout}


def install_wordpress_stack():
    return shell.run([
        "apt-get", "install", "-y", "nginx", "mariadb-server", "redis-server", "php8.3", "php8.3-fpm",
        "php8.3-mysql", "php8.3-gd", "php8.3-xml", "php8.3-mbstring", "php8.3-curl", "php8.3-zip",
        "certbot", "python3-certbot-nginx", "phpmyadmin"
    ])
