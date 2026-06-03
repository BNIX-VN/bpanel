from app.services.shell import shell


def status():
    return shell.privileged(
        "updates-status",
        check=False,
        fallback=["bash", "-lc", "apt list --upgradable 2>/dev/null | head -40"],
    )


def run_os_update():
    return shell.privileged(
        "updates-os-run",
        check=False,
        fallback=[
            "bash",
            "-lc",
            "nohup bash -lc 'apt-get update && apt-get upgrade -y' >/tmp/bpanel-os-update.log 2>&1 & echo OS update started in background. Log: /tmp/bpanel-os-update.log",
        ],
    )


def configure_os_auto_update(enabled: bool, mode: str, auto_reboot: bool):
    if mode not in {"security", "all"}:
        raise ValueError("Unsupported OS auto-update mode")
    return shell.privileged(
        "updates-os-auto",
        helper_args=["on" if enabled else "off", mode, "on" if auto_reboot else "off"],
        check=False,
        fallback=["bash", "-lc", "echo unattended-upgrades helper is not installed"],
    )


def run_panel_update():
    return shell.privileged(
        "updates-panel-run",
        check=False,
        fallback=["bash", "installer/update.sh"],
    )


def configure_panel_auto_update(enabled: bool, time_value: str):
    return shell.privileged(
        "updates-panel-auto",
        helper_args=["on" if enabled else "off", time_value],
        check=False,
        fallback=["bash", "-lc", "echo panel auto-update helper is not installed"],
    )
