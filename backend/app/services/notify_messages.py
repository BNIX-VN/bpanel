"""What the Notifications addon can say, to whom, and in which words.

Two audiences. An administrator hears about the server: a service that
stopped, a disk filling up, the firewall off, a failed scheduled backup,
malware, certificates about to expire, a panel update. Every account - an
administrator's included - hears about itself: a sign-in from an address it
has not used before, a password or two-factor change, a suspension, and the
backups, malware, certificates and storage of its own websites.

Each message exists in Vietnamese and English; the panel-wide setting picks
one. A message is a title and a few lines, plain text, so the same words work
in an email and in Telegram.
"""
from __future__ import annotations

from collections.abc import Callable

ADMIN = "admin"
USER = "user"

# key -> audience, the label a person sees in their settings, a one-line hint.
EVENTS: dict[str, dict] = {
    # --- the server, to administrators ---------------------------------------
    "service_down": {"audience": ADMIN, "label": "A service stopped or came back",
                     "hint": "nginx, PHP-FPM, MariaDB, Redis or the panel itself, checked every 5 minutes."},
    "disk_high": {"audience": ADMIN, "label": "The disk is nearly full",
                  "hint": "Once when usage passes the threshold, again only after it has dropped back."},
    "firewall_off": {"audience": ADMIN, "label": "The firewall is off",
                     "hint": "Switched off, or on but not filtering."},
    "update_available": {"audience": ADMIN, "label": "A panel update is available",
                         "hint": "Once per new version."},
    "backup_failed_admin": {"audience": ADMIN, "label": "A scheduled backup failed",
                            "hint": "Any schedule on the server, with the error."},
    "malware_found_admin": {"audience": ADMIN, "label": "Malware found",
                            "hint": "Any scan on the server that finds something."},
    "ssl_expiring_admin": {"audience": ADMIN, "label": "Certificates about to expire",
                           "hint": "Every website's certificate, checked once a day."},
    # --- an account, to its own holder ----------------------------------------
    "login_new_ip": {"audience": USER, "label": "Sign-in from a new address",
                     "hint": "Your account signed in from an IP it has not used before."},
    "security_change": {"audience": USER, "label": "Password or two-factor changed",
                        "hint": "So a change you did not make does not go unnoticed."},
    "account_status": {"audience": USER, "label": "Account suspended or restored",
                       "hint": "Your websites stop, or start again."},
    "backup_failed": {"audience": USER, "label": "Your scheduled backup failed",
                      "hint": "The backup of your account did not complete."},
    "malware_found": {"audience": USER, "label": "Malware in your websites",
                      "hint": "A scan found suspicious files in a website you own."},
    "ssl_expiring": {"audience": USER, "label": "Your certificates about to expire",
                     "hint": "A website of yours whose SSL certificate runs out soon."},
    "quota_high": {"audience": USER, "label": "Your storage is nearly full",
                   "hint": "Checked once a day against your plan."},
}

LANGUAGES = ("vi", "en")
MAX_LISTED = 8


def _listed(items: list[str], more_vi: str, more_en: str, lang: str) -> list[str]:
    shown = [f"- {item}" for item in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        rest = len(items) - MAX_LISTED
        shown.append((more_vi if lang == "vi" else more_en).format(n=rest))
    return shown


def _service_down(p: dict, lang: str) -> tuple[str, list[str]]:
    names = ", ".join(p.get("services") or [])
    if p.get("recovered"):
        return (
            (f"Dịch vụ đã chạy lại: {names}", ["Dịch vụ hoạt động bình thường trở lại."])
            if lang == "vi" else
            (f"Service running again: {names}", ["The service is back to normal."])
        )
    return (
        (f"Dịch vụ đã dừng: {names}", [
            "Dịch vụ không chạy trong hai lần kiểm tra liên tiếp.",
            "Vào trang Dịch vụ trong panel để khởi động lại và xem log.",
        ]) if lang == "vi" else
        (f"Service stopped: {names}", [
            "The service was not running at two checks in a row.",
            "Open Services in the panel to start it again and read its log.",
        ])
    )


def _disk_high(p: dict, lang: str) -> tuple[str, list[str]]:
    return (
        (f"Ổ đĩa đã dùng {p['percent']}%", [
            f"Đã dùng {p['used']} trên {p['total']}, còn trống {p['free']}.",
            "Khi đầy, MariaDB, backup và việc tải file lên đều sẽ lỗi.",
        ]) if lang == "vi" else
        (f"Disk {p['percent']}% full", [
            f"{p['used']} of {p['total']} used, {p['free']} free.",
            "When it is full, MariaDB, backups and uploads all start failing.",
        ])
    )


def _firewall_off(p: dict, lang: str) -> tuple[str, list[str]]:
    return (
        ("Tường lửa đang tắt", ["Server không được tường lửa bảo vệ. Vào trang Tường lửa để bật lại."])
        if lang == "vi" else
        ("The firewall is off", ["The server is not protected by its firewall. Open Firewall to turn it back on."])
    )


def _update_available(p: dict, lang: str) -> tuple[str, list[str]]:
    return (
        (f"Có bản cập nhật BPanel {p['version']}", [
            f"Đang chạy {p['current']}. Cập nhật bằng lệnh: bpanel-update --release",
        ]) if lang == "vi" else
        (f"BPanel {p['version']} is available", [
            f"This server runs {p['current']}. Update with: bpanel-update --release",
        ])
    )


def _backup_failed(p: dict, lang: str) -> tuple[str, list[str]]:
    errors = p.get("errors") or []
    if lang == "vi":
        return (f"Backup theo lịch bị lỗi ({p.get('when', '')})",
                ["Lần chạy backup theo lịch không hoàn tất:", *_listed(errors, "...và {n} lỗi khác", "", lang)])
    return (f"Scheduled backup failed ({p.get('when', '')})",
            ["The scheduled backup did not complete:", *_listed(errors, "", "...and {n} more", lang)])


def _malware_found(p: dict, lang: str) -> tuple[str, list[str]]:
    lines = [f"{t['path']} ({t['signature']})" for t in p.get("threats") or []]
    count = p.get("count", len(lines))
    if lang == "vi":
        return (f"Phát hiện {count} file nghi nhiễm mã độc",
                [*_listed(lines, "...và {n} file khác", "", lang),
                 "Xem chi tiết trong trang Quét mã độc. File chưa bị xoá hay cách ly."])
    return (f"{count} suspicious file(s) found",
            [*_listed(lines, "", "...and {n} more", lang),
             "See the Malware scanner page. Nothing was deleted or quarantined."])


def _ssl_expiring(p: dict, lang: str) -> tuple[str, list[str]]:
    lines = [f"{s['domain']}: {s['days']} ngày ({s['expires']})" if lang == "vi"
             else f"{s['domain']}: {s['days']} day(s) ({s['expires']})" for s in p.get("sites") or []]
    if lang == "vi":
        return (f"{len(lines)} chứng chỉ SSL sắp hết hạn",
                [*_listed(lines, "...và {n} website khác", "", lang),
                 "Chứng chỉ Let's Encrypt lẽ ra đã tự gia hạn; hãy mở trang SSL để gia hạn lại."])
    return (f"{len(lines)} SSL certificate(s) about to expire",
            [*_listed(lines, "", "...and {n} more", lang),
             "Let's Encrypt certificates should have renewed on their own; open SSL to renew them."])


def _login_new_ip(p: dict, lang: str) -> tuple[str, list[str]]:
    agent = p.get("agent") or ""
    if lang == "vi":
        return ("Đăng nhập từ địa chỉ mới", [
            f"Tài khoản {p['username']} vừa đăng nhập từ {p['ip']} lúc {p['when']}.",
            *( [f"Trình duyệt: {agent}"] if agent else [] ),
            "Nếu không phải bạn, hãy đổi mật khẩu và bật đăng nhập hai lớp ngay.",
        ])
    return ("Sign-in from a new address", [
        f"Account {p['username']} signed in from {p['ip']} at {p['when']}.",
        *( [f"Browser: {agent}"] if agent else [] ),
        "If this was not you, change your password and turn on two-factor sign-in now.",
    ])


_SECURITY_KINDS = {
    "password": ("Mật khẩu tài khoản đã được đổi", "Your password was changed"),
    "2fa_off": ("Đăng nhập hai lớp đã bị tắt", "Two-factor sign-in was turned off"),
    "2fa_reset": ("Quản trị viên đã đặt lại đăng nhập hai lớp", "An administrator reset your two-factor sign-in"),
}


def _security_change(p: dict, lang: str) -> tuple[str, list[str]]:
    vi, en = _SECURITY_KINDS.get(p.get("kind"), _SECURITY_KINDS["password"])
    if lang == "vi":
        return (vi, [f"Tài khoản {p['username']}, lúc {p['when']}.",
                     "Nếu không phải bạn làm, hãy liên hệ nhà cung cấp hosting ngay."])
    return (en, [f"Account {p['username']}, at {p['when']}.",
                 "If this was not you, contact your hosting provider now."])


def _account_status(p: dict, lang: str) -> tuple[str, list[str]]:
    suspended = p.get("suspended")
    if lang == "vi":
        return (("Tài khoản đã bị tạm khoá" if suspended else "Tài khoản đã được mở lại"),
                [f"Tài khoản {p['username']}: "
                 + ("các website và SFTP tạm ngừng hoạt động." if suspended else "các website và SFTP hoạt động trở lại."),
                 *( ["Liên hệ nhà cung cấp hosting để biết lý do."] if suspended else [] )])
    return (("Your account was suspended" if suspended else "Your account was restored"),
            [f"Account {p['username']}: "
             + ("its websites and SFTP are stopped." if suspended else "its websites and SFTP are running again."),
             *( ["Contact your hosting provider for the reason."] if suspended else [] )])


def _quota_high(p: dict, lang: str) -> tuple[str, list[str]]:
    if lang == "vi":
        return (f"Dung lượng đã dùng {p['percent']}%", [
            f"Tài khoản {p['username']} đã dùng {p['used']} trên {p['limit']} của gói.",
            "Khi đầy, việc tải file lên và backup sẽ bị từ chối. Hãy dọn bớt hoặc nâng gói.",
        ])
    return (f"Storage {p['percent']}% used", [
        f"Account {p['username']} uses {p['used']} of the plan's {p['limit']}.",
        "When it is full, uploads and backups are refused. Clean up or upgrade the plan.",
    ])


_RENDER: dict[str, Callable[[dict, str], tuple[str, list[str]]]] = {
    "service_down": _service_down,
    "disk_high": _disk_high,
    "firewall_off": _firewall_off,
    "update_available": _update_available,
    "backup_failed_admin": _backup_failed,
    "backup_failed": _backup_failed,
    "malware_found_admin": _malware_found,
    "malware_found": _malware_found,
    "ssl_expiring_admin": _ssl_expiring,
    "ssl_expiring": _ssl_expiring,
    "login_new_ip": _login_new_ip,
    "security_change": _security_change,
    "account_status": _account_status,
    "quota_high": _quota_high,
}


def render(event: str, params: dict, lang: str = "vi") -> tuple[str, str]:
    """(title, body) for one event in one language."""
    lang = lang if lang in LANGUAGES else "vi"
    title, lines = _RENDER[event](params, lang)
    return title, "\n".join(line for line in lines if line is not None)


def events_for(role_is_admin: bool) -> list[str]:
    """The events a person can receive: their own, plus the server's for admins."""
    return [key for key, entry in EVENTS.items() if entry["audience"] == USER or role_is_admin]
