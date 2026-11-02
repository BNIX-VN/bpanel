"""`bpanel addon ...`: addons from the server's shell.

Email and Resource limits are not offered on the Addons page any more
(operator, 2026-11-02); this is how they are installed. It runs the same
install and removal as the page (app.api.addons.perform_install /
perform_uninstall), to the end, so the outcome is the same; it works for
every other addon too.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.services import addons

USAGE = (
    "Usage: bpanel addon list\n"
    "       bpanel addon install <slug>\n"
    "       bpanel addon remove <slug>"
)


def _line(entry: dict) -> str:
    state = "installed" if entry["installed"] else "not installed"
    shell_only = "  (shell only)" if entry.get("cli_only") else ""
    return f"{entry['slug']:<18} {entry['name']:<28} {state}{shell_only}"


def _actor_id(db) -> int | None:
    """The audit log names the first administrator; the shell has no session."""
    from app.models.entities import User

    admin = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    return admin.id if admin else None


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0 if argv else 2
    action, args = argv[0], argv[1:]
    if action == "list" and not args:
        for entry in addons.state():
            print(_line(entry))
        return 0
    if action not in {"install", "remove"} or len(args) != 1:
        print(USAGE)
        return 2
    slug = args[0]
    if slug not in addons.CATALOGUE:
        print(f"Unknown addon: {slug}. See: bpanel addon list")
        return 2
    name = addons.CATALOGUE[slug]["name"]
    installed = addons.is_installed(slug)
    if action == "install" and installed:
        print(f"Not done: {name} is already installed")
        return 1
    if action == "remove" and not installed:
        print(f"Not done: {name} is not installed")
        return 1

    from app.api.addons import perform_install, perform_uninstall
    from app.core.database import SessionLocal

    print(f"{'Installing' if action == 'install' else 'Removing'} {name}; this can take a few minutes...", flush=True)
    db = SessionLocal()
    try:
        actor = _actor_id(db)
        if action == "install":
            result = perform_install(slug, db, actor)
        else:
            result = perform_uninstall(slug, db, actor)
    except HTTPException as exc:
        print(f"Failed: {exc.detail}")
        return 1
    except Exception as exc:  # noqa: BLE001 - say it in one line, as the page would
        print(f"Failed: {exc}")
        return 1
    finally:
        db.close()
    if result.get("next_step"):
        print(result["next_step"])
    if result.get("could_not_stop"):
        print("Could not stop: " + ", ".join(result["could_not_stop"]))
    if result.get("kept"):
        print(result["kept"])
    print(_line(next(e for e in addons.state() if e["slug"] == slug)))
    return 0
