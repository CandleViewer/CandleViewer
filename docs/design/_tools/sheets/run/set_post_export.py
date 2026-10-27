"""Post-steps and one PNG export per board of a rendered design set, each under its own theme.

Usage: python3 -I -B set_post_export.py [NN ...] --sheets SET --compact COMPACT --logs LOGS
           [--png-dir DIR] [--server NAME] [--project DIR] [--stop FILE]
Run after set_render.py. Boards go theme by theme (dark, light, high-contrast). On a theme switch it
WAITS 90 s (text token binds re-resolve slowly; an early light or high-contrast export comes out
half dark). Per board: post.tmpl.js with the board's page and root name (U+2215 -> "/" in frame
names; "dashed · ..." strokes and "hatch line · ..." rotation when the sheet's notes.live_checks
ask for them), then export_exec.py with the board id from LOGS/render-NN.log. The PNG goes to the
sheet's `export` path under the repository root (a stem gets docs/design/ and .png added), or to
--png-dir/<file name>. The file is switched back to dark at the end.
Exit 0: every board done; 1: a post-step or an export failed; 3: stopped.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path

from _bridge import REPO, RUN, now, stopped
from _sets import THEMES, boards, bridge_argv, load, run_js, set_args, theme

THEME_WAIT_S = 90
_ID = re.compile(r"^report ok .* id=([0-9a-f-]{36}) ", re.MULTILINE)
_PAGE_ID = re.compile(r'"page": "([0-9a-f-]{36})"')


def js(x: object) -> str:
    """A JSON literal the plugin's SES sandbox accepts (it rejects the HTML comment tokens)."""
    s = json.dumps(x, ensure_ascii=False)
    return s.replace("-->", "--\\x3e").replace("<!--", "\\x3c!--")


def png_path(export: str, png_dir: str | None) -> Path:
    rel = export if export.startswith("docs/design/") else "docs/design/" + export
    rel = rel if rel.endswith(".png") else rel + ".png"
    return Path(png_dir) / Path(rel).name if png_dir else REPO / rel


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    set_args(ap)
    ap.add_argument("--png-dir")
    a = ap.parse_args()
    logs = Path(a.logs)
    tmpl = (RUN / "post.tmpl.js").read_text(encoding="utf-8")
    todo = sorted(boards(a), key=lambda b: (THEMES.index(b.theme), b.nn))
    cur, rc_all = "", 0
    for b in todo:
        if stopped(a.stop):
            print(f"STOP before {b.nn}")
            return 3
        sheet = load(b.sheet)
        name, export = sheet["board"]["name"], sheet["export"]
        checks = " ".join(str(c) for c in (sheet.get("notes") or {}).get("live_checks", []))
        if b.theme != cur:
            print(f"theme {b.theme}: {theme(b.theme, a)}; waiting {THEME_WAIT_S} s")
            cur = b.theme
            time.sleep(THEME_WAIT_S)
        post = logs / f"post-{b.nn}.js"
        post.write_text(
            tmpl.replace('"__PAGE__"', js(b.page))
            .replace('"__ROOT__"', js(name))
            .replace("__HATCH__", js("hatch line" in checks))
            .replace("__DASH__", js("dashed style" in checks)),
            encoding="utf-8",
        )
        res = run_js(post, a)
        print(f"{b.nn} post: {res[:220]}")
        page_id = _PAGE_ID.search(res)
        ids = _ID.findall((logs / f"render-{b.nn}.log").read_text(encoding="utf-8"))
        if not res.startswith("rc 0 ") or not page_id or not ids:
            print(f"{b.nn} FAILED {now()}: post-step failed, or no page/board id")
            rc_all = 1
            continue
        tsv = logs / f"exp-{b.nn}.tsv"
        out = png_path(export, a.png_dir)
        tsv.write_text(f"{page_id.group(1)}\t{ids[-1]}\t{name}\t{out}\n", encoding="utf-8")
        cmd = [sys.executable, "-I", "-B", str(RUN / "export_exec.py"), str(tsv)] + bridge_argv(a)
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        last = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        print(f"{b.nn} export rc={r.returncode}: {last[:200]}")
        rc_all = rc_all or (1 if r.returncode else 0)
    if cur not in ("", "dark"):
        print(f"theme dark: {theme('dark', a)}")
    print(f"EXPORT DONE {now()}")
    return rc_all


if __name__ == "__main__":
    sys.exit(main())
