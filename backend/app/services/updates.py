import json
import os
import re
import subprocess
import time
from pathlib import Path

from app.core.version import APP_VERSION
from app.services.shell import shell


REPO_URL = os.environ.get("BPANEL_REPO_URL", "https://github.com/BNIX-VN/bpanel.git")
UPDATE_STATE_FILE = Path(os.environ.get("BPANEL_UPDATE_STATE_FILE", "/var/lib/bpanel/update-status.json"))
SEMVER_TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
STATUS_CACHE_SECONDS = 300


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _semver_tuple(value: str):
    value = (value or "").strip()
    if value.startswith("v"):
        value = value[1:]
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _read_update_state() -> dict:
    try:
        if UPDATE_STATE_FILE.exists():
            return json.loads(UPDATE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _write_update_state(state: dict) -> None:
    try:
        UPDATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = UPDATE_STATE_FILE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(UPDATE_STATE_FILE)
    except Exception:
        # Update status should never break the Updates page itself.
        return


def _latest_release_from_git() -> tuple[str, str]:
    completed = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", REPO_URL, "refs/tags/v*"],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Could not read release tags").strip())
    candidates = []
    for line in completed.stdout.splitlines():
        ref = line.rsplit("/", 1)[-1].strip()
        match = SEMVER_TAG_RE.match(ref)
        if match:
            candidates.append((tuple(int(part) for part in match.groups()), ref))
    if not candidates:
        raise RuntimeError("No release tags found")
    _, latest_tag = max(candidates, key=lambda item: item[0])
    return latest_tag, latest_tag[1:]


def panel_release_status(force_refresh: bool = False) -> dict:
    state = _read_update_state()
    now = _utc_now()
    current_version = APP_VERSION
    current_tuple = _semver_tuple(current_version)
    latest_version = state.get("latest_version") or ""
    latest_tag = state.get("latest_tag") or (f"v{latest_version}" if latest_version else "")
    check_error = ""

    checked_at = float(state.get("last_checked_epoch") or 0)
    should_refresh = force_refresh or not latest_version or (time.time() - checked_at > STATUS_CACHE_SECONDS)
    if should_refresh:
        try:
            latest_tag, latest_version = _latest_release_from_git()
            state.update(
                {
                    "current_version": current_version,
                    "latest_tag": latest_tag,
                    "latest_version": latest_version,
                    "last_checked_at": now,
                    "last_checked_epoch": time.time(),
                    "check_error": "",
                }
            )
        except Exception as exc:
            check_error = str(exc)
            state.update(
                {
                    "current_version": current_version,
                    "last_checked_at": now,
                    "last_checked_epoch": time.time(),
                    "check_error": check_error,
                }
            )
        _write_update_state(state)
    else:
        state["current_version"] = current_version

    latest_tuple = _semver_tuple(latest_version)
    update_available = None
    if current_tuple and latest_tuple:
        update_available = latest_tuple > current_tuple
    elif not check_error:
        check_error = state.get("check_error") or ""

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "latest_tag": latest_tag,
        "update_available": update_available,
        "last_checked_at": state.get("last_checked_at") or "",
        "last_update_started_at": state.get("last_update_started_at") or "",
        "last_update_finished_at": state.get("last_update_finished_at") or "",
        "last_update_status": state.get("last_update_status") or "",
        "last_update_ref": state.get("last_update_ref") or "",
        "check_error": check_error or state.get("check_error") or "",
        "state_file": str(UPDATE_STATE_FILE),
    }


def status(force_refresh: bool = False):
    result = shell.privileged(
        "updates-status",
        check=False,
        fallback=["bash", "-lc", "apt list --upgradable 2>/dev/null | head -40"],
    )
    payload = result.__dict__
    payload["panel"] = panel_release_status(force_refresh=force_refresh)
    return payload


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
