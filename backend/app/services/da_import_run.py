"""Run one DirectAdmin import in its own process.

The panel used to run imports in a ThreadPoolExecutor inside bpanel-api. A
multi-GB import takes minutes, and anything that restarts that service during
one - an update, a crash, an operator - killed it halfway. What was left was a
half-created account: the panel user and the Linux user existed, the website,
the database and the files did not, and the job record was an in-memory dict
that went with the process, so the page had nothing left to report.

Systemd starts this instead, through the helper, and it outlives bpanel-api.
The unit's own state says whether it is still running; the outcome goes to
RESULT_FILE, because systemd forgets a unit that finished cleanly.
"""

import os
import sys

# Python puts the script's own directory first on sys.path, and that directory
# is app/services, which has an ssl.py. Every `import ssl` that followed - fastapi
# pulls it in through anyio - got the panel's module instead of the standard
# library's, and every import died before it started (.88, 2026-10-02). Only os
# and sys may be imported above this line.
_HERE = os.path.dirname(os.path.realpath(__file__))
BACKEND_DIR = os.path.dirname(os.path.dirname(_HERE))
sys.path[:] = [p for p in sys.path if os.path.realpath(p or ".") != _HERE]
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import datetime  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402

# Must match da_import.IMPORT_RESULT_FILE. It is not imported from there because
# a failure to import da_import is one of the outcomes this file has to record.
RESULT_FILE = os.path.join(
    os.environ.get("DA_IMPORT_STAGE_BASE", "/var/lib/bpanel/da-import"), "last-import.json"
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def write_record(record: dict) -> None:
    """Replace RESULT_FILE in one step, readable by the panel user only.

    It holds the generated passwords of the import, as the API response did.
    """
    directory = os.path.dirname(RESULT_FILE)
    os.makedirs(directory, exist_ok=True)
    tmp = f"{RESULT_FILE}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, default=str)
    os.replace(tmp, RESULT_FILE)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: da_import_run.py <archive> [force]", file=sys.stderr)
        return 2

    # Settings reads .env relative to the working directory, and the bpanel user
    # cannot traverse the directory systemd would otherwise leave us in.
    os.chdir(BACKEND_DIR)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    archive = argv[0]
    force = len(argv) > 1 and argv[1] == "force"
    record = {
        "invocation": os.environ.get("INVOCATION_ID", ""),
        "archive": os.path.basename(archive),
        "status": "running",
        "started_at": _now(),
    }
    # A record that still says "running" once the unit has stopped means the
    # process died without getting to the end: the panel reports that as failed.
    write_record(record)
    print(f"importing {archive} force={force}", flush=True)
    try:
        from app.services import da_import

        result = da_import.import_da_backup(archive, force=force)
    except Exception as exc:  # recorded for the page, and the exit code tells systemd
        logging.exception("import failed")
        print(f"FAILED: {exc}", flush=True)
        write_record({**record, "status": "failed", "error": str(exc) or type(exc).__name__,
                      "finished_at": _now()})
        return 1
    write_record({**record, "status": "completed", "result": result, "finished_at": _now()})
    # The result carries the generated passwords: they go to RESULT_FILE, not
    # to the journal.
    summary = result.get("summary") or []
    domains = sum(len(item.get("imported_domains") or []) for item in summary)
    print(f"RESULT: {len(summary)} account(s), {domains} domain(s), "
          f"{len(result.get('errors') or [])} error(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
