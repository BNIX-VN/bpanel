import os
import shutil
import time

from app.services.shell import shell

SUPPORTED_SERVICES = {"nginx", "php8.3-fpm", "php8.4-fpm", "mariadb", "redis-server"}
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


def _read_cpu_times() -> dict:
    with open("/proc/stat", encoding="utf-8") as handle:
        fields = handle.readline().split()
    if not fields or fields[0] != "cpu":
        raise RuntimeError("Cannot read CPU counters")
    values = [int(value) for value in fields[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return {"idle": idle, "total": sum(values)}


def _cpu_percent(start: dict, end: dict) -> float:
    total_delta = end["total"] - start["total"]
    idle_delta = end["idle"] - start["idle"]
    if total_delta <= 0:
        return 0.0
    percent = (1 - (idle_delta / total_delta)) * 100
    return round(max(0.0, min(100.0, percent)), 1)


def _read_network_totals() -> dict:
    totals = {"rx": 0, "tx": 0}
    with open("/proc/net/dev", encoding="utf-8") as handle:
        for line in handle.readlines()[2:]:
            if ":" not in line:
                continue
            name, data = line.split(":", 1)
            if name.strip() == "lo":
                continue
            fields = data.split()
            if len(fields) >= 16:
                totals["rx"] += int(fields[0])
                totals["tx"] += int(fields[8])
    return totals


def _memory_usage() -> dict:
    values = {}
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            key, raw_value = line.split(":", 1)
            values[key] = int(raw_value.split()[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - available)
    percent = round((used / total) * 100, 1) if total else 0.0
    return {"total": total, "used": used, "available": available, "percent": percent}


def _disk_usage() -> dict:
    usage = shutil.disk_usage("/")
    percent = round((usage.used / usage.total) * 100, 1) if usage.total else 0.0
    return {"mount": "/", "total": usage.total, "used": usage.used, "free": usage.free, "percent": percent}


def resource_usage() -> dict:
    sample_seconds = 0.2
    cpu_start = _read_cpu_times()
    network_start = _read_network_totals()
    time.sleep(sample_seconds)
    cpu_end = _read_cpu_times()
    network_end = _read_network_totals()
    rx_delta = max(0, network_end["rx"] - network_start["rx"])
    tx_delta = max(0, network_end["tx"] - network_start["tx"])
    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load_average = []
    return {
        "cpu": {"percent": _cpu_percent(cpu_start, cpu_end), "load": load_average, "cores": os.cpu_count() or 1},
        "memory": _memory_usage(),
        "disk": _disk_usage(),
        "network": {
            "rx_per_sec": round(rx_delta / sample_seconds),
            "tx_per_sec": round(tx_delta / sample_seconds),
            "rx_total": network_end["rx"],
            "tx_total": network_end["tx"],
        },
        "sample_seconds": sample_seconds,
    }


def install_wordpress_stack():
    raise PermissionError(
        "Installing the system stack from the panel is disabled. "
        "Run installer/install.sh on the server instead."
    )
