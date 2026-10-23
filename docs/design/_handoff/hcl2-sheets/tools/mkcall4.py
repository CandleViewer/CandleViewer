"""Print the exact execute_code body for one step of rendering a cvsheet v4 board sheet (compact or plain) in Penpot.

Usage: python3 -I mkcall4.py <sheet.json> <step> [--page NAME]        (<sheet.json> "-" reads the sheet from stdin)
  step = install   the cvsheet library in cvsheet-v4.js (run once per plugin session, after cvlib v8 is installed);
                   it returns { cvsheet: <version installed now>, was: <version installed before, or null> }
       = root      enter/create the page, find-or-create the root board, return its report
       = <i>       render section i (0-based) into the root (replaces the same-named child; idempotent); the section
                   is passed as it is in the sheet, so a compact sheet's styles / s refs / clone nodes are expanded by
                   cvsheet v4.1 inside Penpot
       = touch     cv.touchTexts(root)   (a LATER call than the last section)
       = relayout  cv.relayout(root)     (a LATER call than touch)
       = report    read-only report of the root (sizes, unmeasured texts, children)
       = lint      read-only sh.lint(root): { counts, findings (at most 40), shapes }  (after touch and relayout)
       = count     print the number of sections (no JS)
       = size <i>  print the byte size (UTF-8) of the call that step <i> prints (no JS); <i> may be any step above
Same as mkcall.py except: the GUARD requires the version that cvsheet-v4.js declares (`const S = { v: X }`, read here
at run time, so the GUARD and the library cannot drift; a lower or missing version answers { needSheetLib: true }),
`install` prints cvsheet-v4.js, the `lint` and `size` steps, and JSON in calls uses compact separators.
Staleness (v4.1): a compact sheet carries compactOf {file, sha256} (stamped by compact.py). Every step except `install`
exits with "stale compact sheet: ..." when that file is missing or its sha256 differs, and refuses a compact sheet
without the stamp (or stamped from stdin); re-run compact.py on the original. A plain (original) sheet needs no stamp.
The page defaults to the sheet's key (board name up to the second "-": "E35-D01-03-..." -> "E35-D01") or the part of
the board name before " / " (E08-D07 boards); override with --page.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = (HERE / "cvsheet-v4.js").read_text(encoding="utf-8")
_ver = re.search(r"const S = \{ v: ([0-9]+(?:\.[0-9]+)?) \}", LIB)
if not _ver:
    raise SystemExit("cvsheet-v4.js: no `const S = { v: <version> }` line")
V = _ver.group(1)
if f"storage.cvsheet.v < {V}) {{" not in LIB:
    raise SystemExit(f"cvsheet-v4.js: its install guard does not test `storage.cvsheet.v < {V}`")


def js(x: object) -> str:
    # The plugin's SES sandbox rejects "-->" and "<!--" anywhere in source text (SES_HTML_COMMENT_REJECTED), even
    # inside a string literal; emit them with a JS \x escape (\x3e, \x3c): the same text at run time, and the tool-call layer keeps \x escapes (it decodes \u ones back into the raw token).
    s = json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    return s.replace("-->", "--\\x3e").replace("<!--", "\\x3c!--")


def compacted(n: object) -> bool:
    return isinstance(n, dict) and ("s" in n or n.get("t") == "clone" or any(compacted(k) for k in n.get("kids", []) or []))


def stale(sheet: dict) -> str | None:
    """Why this sheet must not be rendered, or None: a compact sheet must name an original whose bytes still hash the
    same as when it was compacted."""
    co = sheet.get("compactOf")
    if co is None:
        if any(isinstance(s, dict) and ("styles" in s or compacted(s.get("node"))) for s in sheet.get("sections") or []):
            return "compact sheet without compactOf (hand-made, or from an older compact.py): re-run compact.py on its original"
        return None
    if not isinstance(co, dict) or not isinstance(co.get("file"), str) or not co["file"] or not isinstance(co.get("sha256"), str):
        return "compactOf names no original file (compacted from stdin?): re-run compact.py on the original file"
    p = Path(co["file"])
    if not p.is_file():
        return f"stale compact sheet: its original {co['file']} is missing"
    if hashlib.sha256(p.read_bytes()).hexdigest() != co["sha256"]:
        return f"stale compact sheet: {co['file']} changed after it was compacted; re-run compact.py"
    return None


args = sys.argv[1:]
page_arg = None
if "--page" in args:
    i = args.index("--page")
    page_arg = args[i + 1]
    del args[i:i + 2]
if len(args) < 2:
    print(__doc__, file=sys.stderr)
    sys.exit(2)
sheet_path, step = args[0], args[1]
sheet = json.loads(sys.stdin.read() if sheet_path == "-" else Path(sheet_path).read_text(encoding="utf-8"))
if step != "install":
    why = stale(sheet)
    if why:
        raise SystemExit(why)
b = sheet["board"]
name = b["name"]
if page_arg is not None:
    page = page_arg
elif " / " in name:
    page = name.split(" / ")[0]
else:
    m = re.match(r"^([A-Z]\d\d-[A-Z]\d\d)", name)
    page = m.group(1) if m else name

GUARD = f"""const cv = storage.cvd02; if (!cv || cv.v < 8) {{ await new Promise((r) => setTimeout(r, 20000)); return {{ needLib: true, inst: storage.cvd02inst || null }}; }}
if (storage.cvd02inst !== cv.WRITER) {{ await new Promise((r) => setTimeout(r, 20000)); return {{ skip: "not-writer" }}; }}
if (!storage.cvsheet || storage.cvsheet.v < {V}) return {{ needSheetLib: true }};
const sh = storage.cvsheet;
const PAGE = {js(page)};
let page = penpotUtils.getPageByName(PAGE);
"""
ENTER_EXISTING = """if (!page) return { error: "page not found: " + PAGE };
await penpot.openPage(page);
if (!penpot.currentPage || penpot.currentPage.id !== page.id) return { retry: "page" };
"""
ROOTSPEC = js({k: b[k] for k in ("w", "h", "x", "y", "o") if k in b})
FIND_ROOT = f"""const hits = penpot.currentPage.root.children.filter((c) => c.name === {js(name)} && c.type === "board");
if (hits.length !== 1) return {{ error: "root boards named like this: " + hits.length }};
const root = hits[0];
"""
READ_STEPS = {
    "touch": "return { touched: cv.touchTexts(root), report: sh.report(root) };",
    "relayout": "return { relaid: cv.relayout(root), report: sh.report(root) };",
    "report": "return sh.report(root);",
    "lint": "return sh.lint(root);",
}


def call(st: str) -> str:
    if st == "install":
        return ("const cvsheetWas = storage.cvsheet ? storage.cvsheet.v : null;\n" + LIB
                + "\nreturn { cvsheet: storage.cvsheet.v, was: cvsheetWas };")
    if st == "root":
        return GUARD + """if (!page) { page = penpot.createPage(); page.name = PAGE; }
await penpot.openPage(page);
if (!penpot.currentPage || penpot.currentPage.id !== page.id) return { retry: "page" };
""" + f"const root = sh.root({js(name)}, {ROOTSPEC});\nreturn Object.assign({{ page: page.id }}, sh.report(root));"
    if st in READ_STEPS:
        return GUARD + ENTER_EXISTING + FIND_ROOT + READ_STEPS[st]
    i = int(st)
    if not 0 <= i < len(sheet["sections"]):
        raise SystemExit(f"section {i} out of range (0..{len(sheet['sections']) - 1})")
    sec = sheet["sections"][i]
    return (GUARD + ENTER_EXISTING + FIND_ROOT + f"const SEC = {js(sec)};\n"
            f"const made = sh.section(root, SEC);\nreturn {{ section: {i}, of: {len(sheet['sections'])}, made: made.name, "
            f"id: made.id, report: sh.report(root) }};")


if step == "count":
    print(len(sheet["sections"]))
elif step == "size":
    if len(args) < 3:
        raise SystemExit("usage: mkcall4.py <sheet.json> size <i|step>")
    print(len(call(args[2]).encode("utf-8")))
else:
    print(call(step))
