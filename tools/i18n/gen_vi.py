"""Generate frontend/src/locales/vi.js from the Python translation parts.

The parts are the source of truth: a Python dict is easier to review and to
diff than 600 lines of JavaScript, and generating the JS means the escaping is
done once, correctly, rather than by hand 600 times.
"""

import pathlib
import runpy
import sys

HERE = pathlib.Path(__file__).parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/src/locales/vi.js")

merged = {}
for n in (1, 2, 3, 4):
    part = HERE / f"vi_part{n}.py"
    if not part.exists():
        continue
    merged.update(runpy.run_path(str(part))[f"PART{n}"])

HEADER = '''/* Vietnamese. Keys are the English strings exactly as they appear in the
 * interface or come back from the API; see i18n.js for why the English is the
 * key rather than a name like nav.websites.
 *
 * Hosting words that Vietnamese administrators already say in English stay in
 * English - website, database, backup, SSL, token, plugin, port, cron. A panel
 * that translates those reads as machine output and is harder to use, not
 * easier. What is translated is the ordinary language around them.
 *
 * Anything absent here renders in English, which is the designed fallback, so
 * this file is never in a half-broken state and a string added tomorrow does
 * not have to wait for a translator.
 *
 * Generated from tools/i18n/vi_part*.py. Edit those and run
 *
 *     python tools/i18n/gen_vi.py frontend/src/locales/vi.js
 *
 * rather than editing here, or the next regeneration will overwrite you. The
 * parts are Python because a dict reviews and diffs better than 650 lines of
 * JavaScript, and because generating means the escaping is done once.
 */

export const vi = {
'''


def js(value):
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# A term whose Vietnamese is the English word does not belong in the file. The
# fallback already returns the English, so the entry is dead weight that makes
# the dictionary look more complete than it is. The decision to leave those
# terms alone is recorded in the header instead, where the next translator
# reads it before "fixing" them.
kept_in_english = sorted(key for key, value in merged.items() if key == value)
merged = {key: value for key, value in merged.items() if key != value}

note = []
if kept_in_english:
    note = [
        " *",
        " * Deliberately left in English. Vietnamese administrators say these",
        " * words in English, and translating them makes the panel harder to",
        " * read, not easier:",
        " *",
    ]
    row = " *   "
    for term in kept_in_english:
        if len(row) + len(term) > 72:
            note.append(row.rstrip().rstrip(","))
            row = " *   "
        row += term + ", "
    note.append(row.rstrip().rstrip(","))

header = HEADER.rstrip("\n")
if note:
    header = header.replace("\n */", "\n" + "\n".join(note) + "\n */", 1)

lines = [header]
for key in sorted(merged):
    lines.append(f"  {js(key)}: {js(merged[key])},")
lines += ["};", ""]

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"{OUT}: {len(merged)} entries, {OUT.stat().st_size} bytes")
