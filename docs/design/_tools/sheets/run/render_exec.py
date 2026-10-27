"""Render one cvsheet v4 board sheet in your Penpot tab through the repo's penpot_exec.py.

Usage: python3 -I -B render_exec.py <compact sheet> [--page NAME] [--from STEP] [--progress FILE]
           [--server NAME] [--project DIR] [--stop FILE]
Steps: root (installs cvlib 8.2 and cvsheet when the GUARD asks), sections 0..N-1, touch, relayout
(repeated while texts stay unmeasured, at most 3 times), report, lint. --from resumes at a step (a
section index, touch, relayout, report or lint). The calls come from ../tools/mkcall4.py; the
library from ../lib/cvlib-v8.js. The tool's answer is parsed and only selected fields are logged,
never its raw text; the STOP file ends the run at a step boundary. A failed call is retried twice,
30 s apart (the bridge gives up on a call after about 120 s; a timed-out call may still have run,
and every step is idempotent).
Exit 0: built and linted; 1: a step failed (the log says which; resume with --from); 3: stopped.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path

from _bridge import (
    CVLIB,
    MKCALL,
    add_bridge_args,
    brief,
    call,
    now,
    progress,
    stopped,
)


def mk(sheet: str, step: str, page: str | None) -> str:
    cmd = [sys.executable, "-I", "-B", str(MKCALL), sheet, step] + (
        ["--page", page] if page else []
    )
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit(f"mkcall4 {step}: {r.stderr.strip()[-300:]}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("sheet")
    ap.add_argument("--page")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--progress")
    add_bridge_args(ap)
    a = ap.parse_args()
    n = int(mk(a.sheet, "count", a.page).strip())
    steps = ["root"] + [str(i) for i in range(n)] + ["touch", "relayout", "report", "lint"]
    if a.start is not None:
        if a.start not in steps:
            raise SystemExit(
                f"--from {a.start}: not one of root, 0..{n - 1}, touch, relayout, report, lint"
            )
        steps = steps[steps.index(a.start) :]
    with progress(a.progress) as log:
        return render(a, n, steps, log)


def render(a: argparse.Namespace, n: int, steps: list[str], log: TextIO) -> int:
    t0 = time.time()

    def say(s: str) -> None:
        print(s, file=log, flush=True)

    def run(code: str) -> tuple[int, object]:
        return call(code, a.server, a.project)

    say(f"# render_exec {now()} sheet={Path(a.sheet).name} sections={n} page={a.page or '(sheet)'}")
    for step in steps:
        if stopped(a.stop):
            say(f"STOP {now()} before {step}")
            return 3
        t = time.time()
        rc: int = 1
        res: object = None
        for attempt in range(1, 4):
            rc, res = run(mk(a.sheet, step, a.page))
            if isinstance(res, dict) and res.get("needLib"):  # also after a reload (a --from run)
                rc2, r2 = run(CVLIB.read_text(encoding="utf-8") + "\nreturn storage.cvd02.v;")
                say(f"install cvlib {now()} rc={rc2} {brief(r2) if isinstance(r2, dict) else r2}")
                continue
            if isinstance(res, dict) and res.get("needSheetLib"):
                rc2, r2 = run(mk(a.sheet, "install", a.page))
                say(f"install cvsheet {now()} rc={rc2} {brief(r2)}")
                continue
            if isinstance(res, dict) and (res.get("skip") or res.get("abort")):
                say(f"{step} REFUSED {now()} {brief(res)}")
                return 1
            if rc == 0:
                break
            say(f"{step} attempt {attempt} rc={rc} {brief(res)}; waiting 30 s")
            time.sleep(30)
        else:
            say(f"{step} FAILED {now()} {brief(res)}")
            return 1
        if step == "relayout" and isinstance(res, dict) and res.get("unmeasured"):
            for _ in range(2):
                time.sleep(5)
                rc, res = run(mk(a.sheet, "relayout", a.page))
                if not (isinstance(res, dict) and res.get("unmeasured")):
                    break
        say(f"{step} ok {now()} {time.time() - t:.1f}s {brief(res)}")
    say(f"# done {now()} total {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
