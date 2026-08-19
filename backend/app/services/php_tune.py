"""PHP settings sized for the machine the panel is running on.

Two halves, and only one of them existed before.

The FPM pools have been sized from RAM, CPU and pool count since they were
introduced — but silently, at the moment a pool is written, so nobody could see
what was chosen and a server that gained RAM kept yesterday's numbers until
someone happened to touch a site. This module reads the same figures back out.

php.ini was never sized at all: every server got the same constants, including
`memory_limit = 1024M`, which on a 2 GB box lets a single request eat half the
machine while the pool maths assumed 128 MB per worker. Those are what the
recommendations here mostly change.

Nothing is applied on its own. The panel shows current beside recommended, with
the reason, and an administrator decides.
"""

import os
import re
from pathlib import Path

from app.services import php

# Mirrors PHP_FPM_DEFAULT_WORKER_MB in bpanel-helper.sh. The pool maths divides
# the PHP budget by this, so it is also what a sensible memory_limit is built
# from: a limit far above it means the arithmetic protecting the box is fiction.
WORKER_MB = 128
TUNE_FILE_NAME = "95-bpanel-tune.ini"

# Keys the tuner is allowed to write. The helper enforces the same list; this
# copy is what the panel offers, so a typo here fails loudly rather than being
# written and ignored.
TUNABLE_KEYS = (
    "memory_limit",
    "realpath_cache_size",
    "realpath_cache_ttl",
    "opcache.enable",
    "opcache.enable_cli",
    "opcache.memory_consumption",
    "opcache.interned_strings_buffer",
    "opcache.max_accelerated_files",
    "opcache.revalidate_freq",
    "opcache.validate_timestamps",
    "opcache.save_comments",
    "expose_php",
    "zlib.output_compression",
)


def total_memory_mb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return max(1, int(line.split()[1]) // 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 1024


def available_memory_mb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return max(0, int(line.split()[1]) // 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def pool_count() -> int:
    """Managed FPM pools, which is what the per-pool share is divided by."""
    found = 0
    for version_dir in Path("/etc/php").glob("*/fpm/pool.d"):
        found += len(list(version_dir.glob("bpanel-*.conf")))
    return max(1, found)


def reserved_memory_mb(total_mb: int) -> int:
    """RAM kept for everything that is not PHP: MariaDB, nginx, the panel, apps.

    The same tiers the helper uses, so the panel reports the number the pools
    were actually sized against rather than a second opinion.
    """
    if total_mb <= 1024:
        reserve = max(total_mb * 45 // 100, 448)
    elif total_mb <= 2048:
        reserve = max(total_mb * 35 // 100, 640)
    elif total_mb <= 4096:
        reserve = max(total_mb * 30 // 100, 896)
    elif total_mb <= 8192:
        reserve = max(total_mb * 25 // 100, 1280)
    else:
        reserve = max(total_mb * 20 // 100, 2048)
    return max(128, min(reserve, total_mb - 128))


def server_facts() -> dict:
    total = total_memory_mb()
    reserve = reserved_memory_mb(total)
    budget = max(WORKER_MB, total - reserve)
    return {
        "cpu_count": cpu_count(),
        "total_memory_mb": total,
        "available_memory_mb": available_memory_mb(),
        "reserved_memory_mb": reserve,
        "php_budget_mb": budget,
        "pool_count": pool_count(),
        "worker_mb": WORKER_MB,
        "concurrent_requests": max(1, budget // WORKER_MB),
    }


def _tier(total_mb: int) -> dict:
    """The numbers that follow from how much RAM the machine has.

    Sized so that a worker holding memory_limit does not by itself exceed what
    the pool arithmetic budgeted for it, and so opcache is big enough to hold a
    WordPress install without evicting on every request.
    """
    if total_mb <= 1024:
        return {"memory_limit": 128, "opcache_mb": 64, "interned": 8, "files": 10000}
    if total_mb <= 2048:
        return {"memory_limit": 192, "opcache_mb": 96, "interned": 8, "files": 16229}
    if total_mb <= 4096:
        return {"memory_limit": 256, "opcache_mb": 128, "interned": 16, "files": 32531}
    if total_mb <= 8192:
        return {"memory_limit": 384, "opcache_mb": 192, "interned": 24, "files": 65407}
    return {"memory_limit": 512, "opcache_mb": 256, "interned": 32, "files": 130987}


def recommendations(facts: dict | None = None) -> list[dict]:
    """What to set, and why, for this machine."""
    facts = facts or server_facts()
    total = facts["total_memory_mb"]
    tier = _tier(total)
    workers = facts["concurrent_requests"]

    return [
        {
            "key": "memory_limit",
            "value": f"{tier['memory_limit']}M",
            "reason": (
                f"{total} MB RAM, {facts['reserved_memory_mb']} MB để cho MariaDB/nginx/panel, "
                f"còn {facts['php_budget_mb']} MB cho PHP (~{workers} request cùng lúc). "
                "Một request không nên tự mình ăn hết phần đó."
            ),
        },
        {
            "key": "opcache.enable",
            "value": "1",
            "reason": "Không có opcache thì mỗi request biên dịch lại toàn bộ mã nguồn.",
        },
        {
            "key": "opcache.memory_consumption",
            "value": str(tier["opcache_mb"]),
            "reason": f"Đủ chứa mã đã biên dịch của một WordPress đầy plugin ({tier['opcache_mb']} MB).",
        },
        {
            "key": "opcache.interned_strings_buffer",
            "value": str(tier["interned"]),
            "reason": "Chuỗi lặp lại được dùng chung giữa các worker thay vì nhân bản.",
        },
        {
            "key": "opcache.max_accelerated_files",
            "value": str(tier["files"]),
            "reason": "WordPress cùng plugin thường vượt 10.000 file; hết chỗ là opcache bắt đầu đuổi file.",
        },
        {
            "key": "opcache.validate_timestamps",
            "value": "1",
            "reason": "Vẫn kiểm tra file đổi. Tắt thì nhanh hơn chút nhưng khách sửa code sẽ không thấy gì thay đổi.",
        },
        {
            "key": "opcache.revalidate_freq",
            "value": "60",
            "reason": "Kiểm tra file mỗi 60s thay vì mỗi request.",
        },
        {
            "key": "opcache.save_comments",
            "value": "1",
            "reason": "Bắt buộc giữ: nhiều thư viện PHP đọc annotation trong comment.",
        },
        {
            "key": "opcache.enable_cli",
            "value": "0",
            "reason": "WP-CLI và cron chạy một lần rồi thoát, cache không kịp dùng.",
        },
        {
            "key": "realpath_cache_size",
            "value": "4096k",
            "reason": "Mặc định 256k là quá nhỏ cho cây thư mục WordPress; giảm số lần stat().",
        },
        {
            "key": "realpath_cache_ttl",
            "value": "600",
            "reason": "Giữ đường dẫn đã phân giải 10 phút.",
        },
        {
            "key": "expose_php",
            "value": "Off",
            "reason": "Không quảng cáo phiên bản PHP trong header trả về.",
        },
        {
            "key": "zlib.output_compression",
            "value": "Off",
            "reason": "Nginx đã nén rồi; nén hai lần chỉ tốn CPU.",
        },
    ]


def _read_ini_values(paths: list[Path], keys: set[str]) -> dict:
    values: dict[str, str] = {}
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith((";", "#")) or "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if key in keys:
                values[key] = value.strip('"')
    return values


def current_values(php_version: str) -> dict:
    """What PHP is using now, later files winning as PHP itself resolves them."""
    if php_version not in php.SUPPORTED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version: {php_version}")
    base = Path(f"/etc/php/{php_version}/fpm")
    paths = [base / "php.ini"]
    conf_d = base / "conf.d"
    if conf_d.is_dir():
        paths.extend(sorted(conf_d.glob("*.ini")))
    return _read_ini_values(paths, set(TUNABLE_KEYS))


def _normalise(value: str) -> str:
    text = (value or "").strip().strip('"').lower()
    if text in {"on", "true", "yes"}:
        return "1"
    if text in {"off", "false", "no", ""}:
        return "0"
    match = re.fullmatch(r"(\d+)\s*([kmg])?", text)
    if match:
        size, unit = match.groups()
        factor = {"k": 1, "m": 1024, "g": 1024 * 1024}.get(unit or "", 0)
        # A bare number is a plain integer setting, not a size; keep it as is.
        return f"{int(size) * factor}k" if factor else size
    return text


def plan(php_version: str) -> dict:
    """Current beside recommended, so an administrator can see the difference."""
    facts = server_facts()
    live = current_values(php_version)
    rows = []
    for item in recommendations(facts):
        now = live.get(item["key"], "")
        rows.append({
            **item,
            "current": now,
            "changes": _normalise(now) != _normalise(item["value"]),
        })
    return {
        "php_version": php_version,
        "facts": facts,
        "settings": rows,
        "changes": sum(1 for row in rows if row["changes"]),
        "tune_file": f"/etc/php/{php_version}/fpm/conf.d/{TUNE_FILE_NAME}",
        # The panel's own PHP config page writes 99-bpanel.ini, which PHP reads
        # after this file: anything set there keeps winning.
        "overridden_by": f"/etc/php/{php_version}/fpm/conf.d/99-bpanel.ini",
    }


def render_ini(php_version: str) -> str:
    facts = server_facts()
    lines = [
        "; Generated by BPanel from this server's CPU and RAM.",
        f"; {facts['total_memory_mb']} MB RAM, {facts['cpu_count']} CPU, "
        f"{facts['pool_count']} PHP pool(s), {facts['php_budget_mb']} MB budget for PHP.",
        "; Values in 99-bpanel.ini are read after this file and still win.",
        "",
    ]
    for item in recommendations(facts):
        lines.append(f"{item['key']} = {item['value']}")
    return "\n".join(lines) + "\n"


def apply(php_version: str) -> dict:
    """Write the tuning file and reload PHP-FPM."""
    from app.services.shell import shell

    if php_version not in php.SUPPORTED_PHP_VERSIONS:
        raise ValueError(f"Unsupported PHP version: {php_version}")
    body = render_ini(php_version)
    result = shell.privileged(
        "php-tune-write",
        helper_args=[php_version],
        input=body,
        check=False,
        timeout=120,
        fallback=["bash", "-lc", "echo dry-run-php-tune"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Could not write the PHP tuning file").strip()[-2000:])
    return {"message": (result.stdout or "").strip() or f"PHP {php_version} đã tune.", "plan": plan(php_version)}


def retune_pools() -> dict:
    """Recalculate every managed FPM pool against the machine as it is now.

    Pool sizing is decided when a pool is written, so a server that gained RAM
    keeps the old numbers until each site is touched. This asks for all of them
    at once.
    """
    from app.services.shell import shell

    result = shell.privileged(
        "php-pools-retune",
        check=False,
        timeout=600,
        fallback=["bash", "-lc", "echo dry-run-retune"],
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Could not retune the pools").strip()[-2000:])
    return {"message": "Đã tính lại các pool PHP-FPM.", "output": (result.stdout or "").strip()[-4000:]}
