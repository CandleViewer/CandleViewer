"""Shared by set_render.py and set_post_export.py: a design set's sheets and their sidecars.

A set folder holds, per board, the original sheet `NN-slug.json` and its sidecar `NN-slug.md`,
whose third line names the page (the word page, then the page name in backticks) and the theme
(`theme dark.`, `theme light.` or `theme high-contrast.`). The compact folder holds compact.py's
output under the same file names.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _bridge import RUN, add_bridge_args

THEMES = ("dark", "light", "high-contrast")
THEME_JS = {"dark": "theme-dark.js", "light": "theme-light.js", "high-contrast": "theme-hc.js"}
_PAGE = re.compile(r"page `([^`]+)`")
_THEME = re.compile(r"\btheme (dark|light|high-contrast)\.")


@dataclass(frozen=True)
class Board:
    nn: str
    page: str
    theme: str
    sheet: Path  # the compact sheet


def set_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "boards", nargs="*", help="board numbers (NN); default: every sheet in --sheets"
    )
    ap.add_argument(
        "--sheets", required=True, help="the set folder (original sheets + .md sidecars)"
    )
    ap.add_argument("--compact", required=True, help="the folder of the compact sheets")
    ap.add_argument("--logs", required=True, help="a local folder for logs and the shape counter")
    add_bridge_args(ap)


def bridge_argv(a: argparse.Namespace) -> list[str]:
    out = ["--server", a.server, "--stop", a.stop]
    return out + (["--project", a.project] if a.project else [])


def _one(folder: Path, pattern: str) -> Path:
    hits = sorted(folder.glob(pattern))
    if len(hits) != 1:
        raise SystemExit(f"{folder.name}/{pattern}: {len(hits)} matches, want 1")
    return hits[0]


def boards(a: argparse.Namespace) -> list[Board]:
    sheets, compact = Path(a.sheets), Path(a.compact)
    nns = a.boards or sorted({p.name[:2] for p in sheets.glob("[0-9][0-9]-*.json")})
    out = []
    for nn in nns:
        md = _one(sheets, f"{nn}-*.md")
        lines = md.read_text(encoding="utf-8").splitlines()
        third = lines[2] if len(lines) > 2 else ""
        page, theme = _PAGE.search(third), _THEME.search(third)
        if not page or not theme:
            raise SystemExit(
                f"{md.name}: line 3 names no page `...` or no theme dark|light|high-contrast."
            )
        out.append(Board(nn, page.group(1), theme.group(1), _one(compact, f"{nn}-*.json")))
    return out


def load(sheet: Path) -> dict[str, Any]:
    data = json.loads(sheet.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{sheet.name}: not a sheet")
    return data


def run_js(file: Path, a: argparse.Namespace) -> str:
    """Run a plugin script through run_js.py; return its last output line (rc + parsed result)."""
    cmd = [sys.executable, "-I", "-B", str(RUN / "run_js.py"), str(file), "--server", a.server]
    cmd += ["--project", a.project] if a.project else []
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else f"rc {r.returncode} (no output)"


def theme(name: str, a: argparse.Namespace) -> str:
    return run_js(RUN / THEME_JS[name], a)[:120]
