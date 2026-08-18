"""Import a customer's docker-compose file onto the panel's own model.

The file a customer pastes is never the file that runs. It is parsed, checked
against an allowlist, and a fresh compose file is generated from what survived.
That direction matters: a blocklist would have to keep up with every key Compose
adds, and one missed key (`privileged`, `network_mode`, a host bind mount) undoes
every guardrail around the container. Anything this module does not recognise is
refused by name so the customer can see exactly what to change.
"""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from app.services import site_apps

# Keys the panel understands. Everything else is refused, including keys that
# have not been invented yet.
ALLOWED_TOP_LEVEL = {"services", "volumes", "version", "name"}
ALLOWED_SERVICE_KEYS = {
    "image", "environment", "command", "entrypoint", "depends_on",
    "ports", "expose", "volumes", "user", "working_dir", "hostname",
    "healthcheck", "labels", "restart", "stop_grace_period",
    "tty", "stdin_open", "container_name",
    # Accepted and then overridden by the panel's own limits.
    "mem_limit", "memswap_limit", "cpus", "pids_limit",
}
# Refused with a specific explanation rather than the generic message, because
# these are the ones people actually reach for.
EXPLAINED_SERVICE_KEYS = {
    "privileged": "chạy container ở chế độ privileged",
    "network_mode": "đặt network_mode (host network bỏ qua chốt firewall)",
    "cap_add": "thêm capability",
    "devices": "gắn thiết bị của máy chủ",
    "pid": "dùng chung PID namespace với máy chủ",
    "ipc": "dùng chung IPC namespace",
    "userns_mode": "đổi user namespace",
    "security_opt": "đổi tuỳ chọn bảo mật",
    "sysctls": "đặt sysctl",
    "build": "build image tại chỗ; panel chỉ chạy image có sẵn",
    "extra_hosts": "ghi đè phân giải tên máy",
    "volumes_from": "mượn volume của container khác",
    "cgroup_parent": "đổi cgroup cha",
    "group_add": "thêm group phụ",
    "env_file": "đọc biến môi trường từ file; dán thẳng vào phần Environment",
    "networks": "tự khai network; panel tạo network riêng cho ứng dụng",
    "deploy": "khai báo deploy của swarm",
}
SERVICE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
VOLUME_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_SERVICES = 8
MAX_SOURCE_BYTES = 64 * 1024
# The minimum an image needs to drop from root to its own account at startup —
# what the official Postgres and MySQL entrypoints do through gosu. Without
# these the container cannot initialise its data directory.
PRIVILEGE_DROP_CAPS = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]


@dataclass
class Issue:
    service: str
    message: str

    def as_dict(self) -> dict:
        return {"service": self.service, "message": self.message}


@dataclass
class Service:
    name: str
    image: str
    environment: dict[str, str] = field(default_factory=dict)
    command: Any = None
    entrypoint: Any = None
    depends_on: list[str] = field(default_factory=list)
    container_port: int | None = None
    named_volumes: list[str] = field(default_factory=list)   # "data:/var/lib/x"
    bind_mounts: list[str] = field(default_factory=list)      # "./src:/app/src"
    user: str | None = None
    working_dir: str | None = None
    healthcheck: dict | None = None

    @property
    def touches_app_files(self) -> bool:
        return bool(self.bind_mounts)


@dataclass
class Plan:
    services: list[Service] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    web_service: str = ""
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues and bool(self.services)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "web_service": self.web_service,
            "issues": [issue.as_dict() for issue in self.issues],
            "services": [
                {
                    "name": service.name,
                    "image": service.image,
                    "container_port": service.container_port,
                    "volumes": service.named_volumes + service.bind_mounts,
                    "environment": sorted(service.environment),
                    "web": service.name == self.web_service,
                }
                for service in self.services
            ],
            "volumes": self.volumes,
        }


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _parse_environment(raw: Any, service: str, issues: list[Issue]) -> dict[str, str]:
    entries: dict[str, str] = {}
    if raw is None:
        return entries
    items: list[tuple[str, Any]] = []
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        for line in raw:
            text = str(line)
            if "=" not in text:
                # `- FOO` inherits from the host environment, which for us is the
                # panel's own process. Never pass that through.
                issues.append(Issue(service, f"biến môi trường {text[:40]} không có giá trị"))
                continue
            key, value = text.split("=", 1)
            items.append((key, value))
    else:
        issues.append(Issue(service, "environment phải là danh sách hoặc mapping"))
        return entries

    for key, value in items:
        name = str(key).strip()
        if not ENV_KEY_RE.fullmatch(name):
            issues.append(Issue(service, f"tên biến môi trường không hợp lệ: {name[:40]}"))
            continue
        text = "" if value is None else str(value)
        if any(char in text for char in "\r\n\x00"):
            issues.append(Issue(service, f"giá trị của {name} chứa xuống dòng"))
            continue
        entries[name] = text
    return entries


def _parse_port(raw: Any, service: str, issues: list[Issue]) -> int | None:
    """Read the port the process listens on inside the container.

    Host publishing from the file is ignored: the panel decides the loopback port
    so two customers cannot claim the same one.
    """
    if isinstance(raw, dict):
        target = raw.get("target")
    else:
        text = str(raw).split("/", 1)[0]          # drop /tcp
        parts = text.split(":")
        target = parts[-1]
    try:
        port = int(str(target))
    except (TypeError, ValueError):
        issues.append(Issue(service, f"cổng không đọc được: {str(raw)[:40]}"))
        return None
    if not 1 <= port <= 65535:
        issues.append(Issue(service, f"cổng ngoài phạm vi: {port}"))
        return None
    return port


def _parse_volume(raw: Any, service: str, declared: set[str], issues: list[Issue]) -> tuple[str, str] | None:
    """Returns (kind, spec) where kind is 'named' or 'bind'."""
    if isinstance(raw, dict):
        kind = raw.get("type", "volume")
        source = str(raw.get("source", ""))
        target = str(raw.get("target", ""))
        read_only = bool(raw.get("read_only"))
        if not source or not target:
            issues.append(Issue(service, "volume thiếu source hoặc target"))
            return None
        spec = f"{source}:{target}" + (":ro" if read_only else "")
        if kind == "bind":
            return _parse_volume(spec, service, declared, issues)
        if kind != "volume":
            issues.append(Issue(service, f"loại volume không hỗ trợ: {kind}"))
            return None
        return _parse_volume(spec, service, declared, issues)

    text = str(raw)
    parts = text.split(":")
    if len(parts) < 2:
        issues.append(Issue(service, f"volume phải có dạng nguồn:đích — {text[:50]}"))
        return None
    source, target = parts[0], parts[1]
    suffix = f":{parts[2]}" if len(parts) > 2 and parts[2] in {"ro", "rw"} else ""
    if not target.startswith("/"):
        issues.append(Issue(service, f"đích của volume phải là đường dẫn tuyệt đối — {text[:50]}"))
        return None

    if source.startswith("/"):
        issues.append(Issue(service, f"mount đường dẫn máy chủ không được phép — {text[:50]}"))
        return None
    if source.startswith(".") or "/" in source:
        # A path relative to the project, which is the application directory.
        relative = PurePosixPath(source)
        if any(part == ".." for part in relative.parts):
            issues.append(Issue(service, f"volume trỏ ra ngoài thư mục ứng dụng — {text[:50]}"))
            return None
        cleaned = "/".join(part for part in relative.parts if part not in (".", ""))
        return "bind", f"./{cleaned}:{target}{suffix}" if cleaned else f".:{target}{suffix}"

    if not VOLUME_NAME_RE.fullmatch(source):
        issues.append(Issue(service, f"tên volume không hợp lệ: {source[:40]}"))
        return None
    declared.add(source)
    return "named", f"{source}:{target}{suffix}"


def home_for(service: "Service") -> tuple[str, bool]:
    """Where a service run under a forced uid should keep its home.

    Overriding `user` with a numeric id leaves the container with no matching
    passwd entry, so HOME falls back to `/` and the first thing the process
    writes there fails. Point it at the directory the customer mounted, which is
    the one place inside the container they own.

    A mount at `/home/node/.n8n` is the app's own dot-directory inside a home
    the image owns, so the home is its parent — and that parent belongs to the
    image's account, not ours. Returns True alongside it to say the home itself
    needs to be made writable; the mount underneath it stays persistent either
    way, because Docker mounts the deeper path last.
    """
    target = service.bind_mounts[0].split(":")[1]
    path = PurePosixPath(target)
    if path.name.startswith("."):
        return str(path.parent), True
    return str(path), False


def _parse_service(name: str, raw: Any, declared_volumes: set[str], issues: list[Issue]) -> Service | None:
    if not SERVICE_NAME_RE.fullmatch(name):
        issues.append(Issue(name, "tên service chỉ được dùng chữ thường, số, gạch ngang và gạch dưới"))
        return None
    if not isinstance(raw, dict):
        issues.append(Issue(name, "service phải là một mapping"))
        return None

    for key in raw:
        if key in ALLOWED_SERVICE_KEYS:
            continue
        reason = EXPLAINED_SERVICE_KEYS.get(str(key))
        if reason:
            issues.append(Issue(name, f"{key}: {reason}"))
        else:
            issues.append(Issue(name, f"khoá không được hỗ trợ: {key}"))

    image = str(raw.get("image", "") or "").strip()
    if not image:
        issues.append(Issue(name, "thiếu image"))
        return None
    try:
        image = site_apps.validate_image(image)
    except ValueError as exc:
        issues.append(Issue(name, str(exc)))
        return None

    service = Service(name=name, image=image)
    service.environment = _parse_environment(raw.get("environment"), name, issues)
    service.command = raw.get("command")
    service.entrypoint = raw.get("entrypoint")
    service.working_dir = raw.get("working_dir")
    healthcheck = raw.get("healthcheck")
    service.healthcheck = healthcheck if isinstance(healthcheck, dict) else None

    depends = raw.get("depends_on")
    if isinstance(depends, dict):
        service.depends_on = [str(key) for key in depends]
    else:
        service.depends_on = [str(item) for item in _as_list(depends)]

    ports = _as_list(raw.get("ports"))
    if ports:
        service.container_port = _parse_port(ports[0], name, issues)
    elif raw.get("expose"):
        service.container_port = _parse_port(_as_list(raw.get("expose"))[0], name, issues)

    for entry in _as_list(raw.get("volumes")):
        parsed = _parse_volume(entry, name, declared_volumes, issues)
        if not parsed:
            continue
        kind, spec = parsed
        (service.named_volumes if kind == "named" else service.bind_mounts).append(spec)

    user = raw.get("user")
    if user is not None:
        text = str(user).strip()
        if text in {"root", "0", "0:0"} or text.startswith("0:"):
            issues.append(Issue(name, "không cho phép chạy service bằng root"))
        elif not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", text):
            issues.append(Issue(name, f"giá trị user không hợp lệ: {text[:30]}"))
        else:
            service.user = text
    return service


def analyse(source: str, web_service: str = "") -> Plan:
    """Read a customer's compose file and report what the panel can run."""
    plan = Plan()
    if not (source or "").strip():
        plan.issues.append(Issue("", "chưa có nội dung docker-compose"))
        return plan
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        plan.issues.append(Issue("", "file compose quá lớn"))
        return plan
    try:
        document = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        plan.issues.append(Issue("", f"YAML không hợp lệ: {str(exc).splitlines()[0][:120]}"))
        return plan
    if not isinstance(document, dict):
        plan.issues.append(Issue("", "nội dung phải là một mapping YAML"))
        return plan

    for key in document:
        name = str(key)
        if name in ALLOWED_TOP_LEVEL or name.startswith("x-"):
            continue
        reason = EXPLAINED_SERVICE_KEYS.get(name)
        plan.issues.append(Issue("", f"{name}: {reason}" if reason else f"khoá không được hỗ trợ: {name}"))

    raw_services = document.get("services")
    if not isinstance(raw_services, dict) or not raw_services:
        plan.issues.append(Issue("", "không tìm thấy service nào"))
        return plan
    if len(raw_services) > MAX_SERVICES:
        plan.issues.append(Issue("", f"tối đa {MAX_SERVICES} service cho một ứng dụng"))
        return plan

    declared: set[str] = set()
    for name, raw in raw_services.items():
        service = _parse_service(str(name), raw, declared, plan.issues)
        if service:
            plan.services.append(service)

    declared_top = document.get("volumes")
    if isinstance(declared_top, dict):
        for name, options in declared_top.items():
            if not VOLUME_NAME_RE.fullmatch(str(name)):
                plan.issues.append(Issue("", f"tên volume không hợp lệ: {str(name)[:40]}"))
                continue
            if isinstance(options, dict) and options.get("driver_opts"):
                # driver_opts with o=bind is a host mount wearing a disguise.
                plan.issues.append(Issue("", f"volume {name}: driver_opts không được phép"))
                continue
            declared.add(str(name))
    plan.volumes = sorted(declared)

    plan.web_service = _pick_web_service(plan, web_service)
    return plan


def _pick_web_service(plan: Plan, requested: str) -> str:
    names = [service.name for service in plan.services]
    if requested:
        if requested not in names:
            plan.issues.append(Issue("", f"không có service tên {requested}"))
            return ""
        chosen = requested
    else:
        with_ports = [service for service in plan.services if service.container_port]
        if len(with_ports) == 1:
            chosen = with_ports[0].name
        elif with_ports:
            plan.issues.append(Issue("", "nhiều service khai cổng; hãy chọn service nào phục vụ domain"))
            return ""
        elif plan.services:
            plan.issues.append(Issue("", "không service nào khai cổng; hãy chọn service phục vụ domain và cổng của nó"))
            return ""
        else:
            return ""
    service = next(item for item in plan.services if item.name == chosen)
    if not service.container_port:
        plan.issues.append(Issue(chosen, "service này chưa khai cổng lắng nghe"))
        return ""
    return chosen


def render(
    plan: Plan,
    *,
    project: str,
    published_port: int,
    uid: int,
    gid: int,
    memory_mb: int,
    cpus: str,
) -> str:
    """Build the compose file the server actually runs."""
    if not plan.ok:
        raise ValueError("Không thể dựng compose khi còn lỗi chưa xử lý")

    services: dict[str, Any] = {}
    for service in plan.services:
        entry: dict[str, Any] = {"image": service.image}
        if service.environment:
            entry["environment"] = dict(service.environment)
        if service.command is not None:
            entry["command"] = service.command
        if service.entrypoint is not None:
            entry["entrypoint"] = service.entrypoint
        if service.depends_on:
            entry["depends_on"] = service.depends_on
        if service.working_dir:
            entry["working_dir"] = service.working_dir
        if service.healthcheck:
            entry["healthcheck"] = service.healthcheck

        volumes = service.named_volumes + service.bind_mounts
        if volumes:
            entry["volumes"] = volumes

        if service.name == plan.web_service:
            entry["ports"] = [f"127.0.0.1:{published_port}:{service.container_port}"]

        if service.user:
            entry["user"] = service.user
        elif service.touches_app_files:
            # It writes into the customer's own directory, so it has to write as
            # the customer or the files come out owned by someone else.
            entry["user"] = f"{uid}:{gid}"
            if "HOME" not in service.environment:
                home, ephemeral = home_for(service)
                entry.setdefault("environment", {})["HOME"] = home
                if ephemeral:
                    # A scratch home, so caches and lockfiles the process expects
                    # to write beside its data have somewhere to go. Nothing that
                    # has to survive a restart belongs here — that is what the
                    # customer's mount underneath it is for.
                    entry.setdefault("volumes", []).insert(0, {
                        "type": "tmpfs",
                        "target": home,
                        "tmpfs": {"size": 64 * 1024 * 1024, "mode": 0o1777},
                        # Compose reads mode as a number, and its own docs
                        # write 01777 for it; without one the mount lands
                        # 0755 root-owned and we are back where we started.
                    })

        entry["cap_drop"] = ["ALL"]
        if not entry.get("user"):
            # Images that start as root and drop to their own account — every
            # official database does — need these to set up their data directory.
            entry["cap_add"] = list(PRIVILEGE_DROP_CAPS)
        entry["security_opt"] = ["no-new-privileges:true"]
        entry["mem_limit"] = f"{memory_mb}m"
        entry["memswap_limit"] = f"{memory_mb}m"
        entry["cpus"] = float(cpus)
        entry["pids_limit"] = 256
        entry["restart"] = "unless-stopped"
        entry["logging"] = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
        services[service.name] = entry

    document: dict[str, Any] = {"name": project, "services": services}
    if plan.volumes:
        document["volumes"] = {name: None for name in plan.volumes}

    header = (
        "# Generated by BPanel from the imported docker-compose file.\n"
        "# Edits here are overwritten on the next import.\n"
    )
    return header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
