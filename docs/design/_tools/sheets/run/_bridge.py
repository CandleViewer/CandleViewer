"""Shared helpers of the sheet drivers: one Penpot call through the repo's penpot_exec.py.

The answer is parsed and only selected fields are logged, never its raw text. The MCP entry is chosen
like penpot_exec.py does: --server (default: PENPOT_MCP_SERVER, else `penpot`) and --project (a
local-scope entry; default: PENPOT_MCP_PROJECT). The STOP file (--stop, default: CVSHEET_STOP, else
`STOP` in the current directory) ends a run at a step boundary.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import TextIO

RUN = Path(__file__).resolve().parent  # docs/design/_tools/sheets/run
SHEETS = RUN.parent  # docs/design/_tools/sheets
TOOLS = SHEETS.parent  # docs/design/_tools (penpot_exec.py)
REPO = TOOLS.parents[2]  # the repository root
MKCALL = SHEETS / "tools" / "mkcall4.py"
CVLIB = SHEETS / "lib" / "cvlib-v8.js"


def now() -> str:
    return time.strftime("%H:%M:%S", time.gmtime())


def add_bridge_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--server", default=os.environ.get("PENPOT_MCP_SERVER") or "penpot")
    ap.add_argument("--project", default=os.environ.get("PENPOT_MCP_PROJECT") or None)
    ap.add_argument("--stop", default=os.environ.get("CVSHEET_STOP") or "STOP")


def _px() -> ModuleType:
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    return importlib.import_module("penpot_exec")


def run_raw(code: str, server: str, project: str | None) -> tuple[int, str]:
    """Run code; return (rc, answer text). The caller must not log the text."""
    rc, text = _px().run(code, server, project)
    return int(rc), str(text)


def _scrub(text: str) -> str:
    t = re.sub(r"\w+://\S+", "<url>", text)
    t = re.sub(r"[A-Za-z0-9_\-]{24,}", "<long>", t)
    t = re.sub(r"(?i)(token|key|secret|bearer)\S*", "<k>", t)
    return " ".join(t.split())[:90]


def call(code: str, server: str, project: str | None) -> tuple[int, object]:
    """Run code; return (rc, parsed result or a short error). Never returns the raw answer text."""
    try:
        rc, text = run_raw(code, server, project)
    except SystemExit as e:  # penpot_exec reports errors without the URL or key
        return 1, {"error": _scrub(str(e.code))}
    except Exception as e:  # noqa: BLE001 - any bridge failure is reported by its class only
        return 1, {"error": type(e).__name__}
    try:
        obj = json.loads(text)
    except ValueError:
        return (rc or 1), {"error": "non-JSON answer", "len": len(text), "snip": _scrub(text)}
    res = obj.get("result", obj) if isinstance(obj, dict) else obj
    return rc, res


def brief(res: object) -> str:
    """A short, safe summary of a result: keys and small scalar values only (names whole)."""
    if not isinstance(res, dict):
        return type(res).__name__
    out = []
    for k, v in list(res.items())[:14]:
        secretish = "token" in str(k).lower() or "key" in str(k).lower()
        scalar = isinstance(v, (int, float, bool)) or v is None
        short = isinstance(v, str) and (len(v) <= 48 or k in ("name", "snip")) and not secretish
        if scalar or short:
            out.append(f"{k}={v}")
        elif isinstance(v, dict) and k == "counts":
            nums = ",".join(f"{a}:{b}" for a, b in v.items() if isinstance(b, (int, float)))
            out.append(f"{k}={nums}")
        else:
            out.append(f"{k}:{type(v).__name__}")
    return " ".join(out)


def stopped(stop: str) -> bool:
    return Path(stop).exists()


@contextlib.contextmanager
def progress(path: str | None) -> Iterator[TextIO]:
    """The progress log: the file (appended to) when given, else stdout."""
    if not path:
        yield sys.stdout
        return
    with open(path, "a", encoding="utf-8") as f:
        yield f
