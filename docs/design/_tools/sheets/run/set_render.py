"""Render a design set's boards in its open per-set Penpot file, every board under the DARK theme.

Usage: python3 -I -B set_render.py [NN ...] --sheets SET --compact COMPACT --logs LOGS
           [--server NAME] [--project DIR] [--stop FILE]
Switches the file's token theme to dark, then runs render_exec.py on each board (light and
high-contrast boards are themed at export by set_post_export.py), logging LOGS/render-NN.log. It
keeps LOGS/shapes-since-reload: past 1,500 shapes it waits 25 s (so saves land), then runs the
command in CVSHEET_RELOAD_CMD (split like a shell would, run without a shell; it must reload your
own Penpot tab and return once the plugin is connected again), then warmup.js, and carries on.
Without CVSHEET_RELOAD_CMD it stops with "reload needed" (exit 4): reload the tab yourself and
re-run with the remaining boards. Never reload mid-board.
Exit 0: every board rendered and linted; 1-3: render_exec.py's code for the failing board;
4: a reload is needed or the reload command failed.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path

from _bridge import RUN, now, stopped
from _sets import THEMES, boards, bridge_argv, run_js, set_args, theme

RELOAD_AT = 1500
_SHAPES = re.compile(r"^report ok .* shapes=(\d+)", re.MULTILINE)


def reload_tab(a: argparse.Namespace) -> bool:
    cmd = os.environ.get("CVSHEET_RELOAD_CMD", "").strip()
    if not cmd:
        print(f"reload needed {now()}: set CVSHEET_RELOAD_CMD, or reload the tab and re-run")
        return False
    time.sleep(25)
    print(f"reload {now()}")
    r = subprocess.run(shlex.split(cmd), check=False)
    if r.returncode != 0:
        print(f"reload command failed rc={r.returncode}")
        return False
    print(f"warmup {now()} {run_js(RUN / 'warmup.js', a)[:80]}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    set_args(ap)
    a = ap.parse_args()
    logs = Path(a.logs)
    logs.mkdir(parents=True, exist_ok=True)
    counter = logs / "shapes-since-reload"
    total = int(counter.read_text().strip() or 0) if counter.exists() else 0
    todo = sorted(boards(a), key=lambda b: (THEMES.index(b.theme), b.nn))
    dark = False
    for b in todo:
        if stopped(a.stop):
            print(f"STOP before {b.nn}")
            return 3
        if total >= RELOAD_AT:
            if not reload_tab(a):
                return 4
            total, dark = 0, False
            counter.write_text("0\n")
        if not dark:
            print(f"theme dark: {theme('dark', a)}")
            dark = True
        log = logs / f"render-{b.nn}.log"
        t = time.time()
        cmd = [sys.executable, "-I", "-B", str(RUN / "render_exec.py"), str(b.sheet)]
        cmd += ["--page", b.page, "--progress", str(log)] + bridge_argv(a)
        rc = subprocess.run(cmd, capture_output=True, check=False).returncode
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        tail = [x for x in text.splitlines() if x.startswith(("report ", "lint "))][-2:]
        print(f"{b.nn} {b.theme} rc={rc} secs={time.time() - t:.0f} {' | '.join(tail)[:300]}")
        if rc != 0:
            return rc
        shapes = _SHAPES.findall(text)
        total += int(shapes[-1]) if shapes else 0
        counter.write_text(f"{total}\n")
    print(f"RENDER DONE {now()} shapes since reload: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
