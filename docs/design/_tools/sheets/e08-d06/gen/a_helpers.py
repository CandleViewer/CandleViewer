"""Group A helpers (boards 1D, 1L, 3D, 6D): the per-board strings block (every drawn string with the spec / hand-off
line that holds it verbatim), the r2 credit line, and emit() (sheet -> md -> packed -> mkcall4 count -> scan).
The kit (e08d06kit.py) is imported, never edited."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e08d06kit as k  # noqa: E402

R2_CREDIT = (f"Seed data: the r2 board script's DATA block, sha256 {k.R2_SHA256[:8]}…{k.R2_SHA256[-4:]}, posted "
             f"2026-10-23 on #174 (values re-derived by the §5 formatters)")
ANATOMY = (k.L("## 3. Anatomy"), k.L("**Tokens** (published names only"))
SYMS = ("LUNAUSDT", "SOLUSDT")


def _short_line(s: str) -> str | None:
    """A short string (< 6 chars: units, small values) cited by a word-bounded match, §3's anatomy first."""
    pat = re.compile(r"(?<![\w.,])" + re.escape(s) + r"(?![\w.,]\d|\w)")
    lo, hi = ANATOMY
    order = list(range(lo, hi)) + [i for i in range(1, len(k.SPEC_LINES) + 1) if not lo <= i < hi]
    for i in order:
        if pat.search(k.SPEC_LINES[i - 1].replace("`", "")):
            return f"L{i}"
    for i, ln in enumerate(k.HANDOFF_LINES, 1):
        if pat.search(ln.replace("`", "")):
            return f"H{i}"
    return None


def cite_any(s: str) -> tuple[str | None, str]:
    """(line tag, how): verbatim, short (word-bounded), or a symbol substitution of a verbatim line."""
    c = k.cite(s)
    if c:
        return c, ""
    if len(s.strip()) < 6:
        return _short_line(s.strip()), ""
    for sym in SYMS:
        if sym in s:
            c = k.cite(s.replace(sym, "BTCUSDT"))
            if c:
                return c, f" ({sym} for BTCUSDT)"
            base = sym.removesuffix("USDT")
            c = k.cite(s.replace(sym, "BTCUSDT").replace(f"{base} / USDT", "BTC / USDT"))
            if c:
                return c, f" ({base} for BTC)"
    return None, ""


def drawn_strings(frames: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for fr in frames:
        for _p, n in k.walk(fr):
            c = n.get("chars")
            if c and c not in out:
                out.append(c)
    return out


def strings_block(frames: list[dict[str, Any]], extra: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """One block: the drawn strings grouped by the line that holds them verbatim ("L<n>: "a", "b""). extra maps a
    string that is not verbatim to its source text (derived value, kit glyph); anything else raises."""
    extra = extra or {}
    by: "OrderedDict[str, list[str]]" = OrderedDict()
    other: list[str] = []
    bad: list[str] = []
    for s in drawn_strings(frames):
        if s in extra:
            other.append(f'"{s}" {extra[s]}')
            continue
        c, how = cite_any(s)
        if c is None:
            bad.append(s)
            continue
        by.setdefault(c, []).append(f'"{s}"{how}')
    if bad:
        raise ValueError(f"strings not in the spec or hand-off (map them in extra=): {bad}")
    keyf = (lambda t: (t[0][0] != "L", int(t[0][1:])))
    groups = [f"{c} {' '.join(v)}" for c, v in sorted(by.items(), key=keyf)] + other
    per = 8  # several line groups per text node: fewer nodes, fewer stack gaps, less partial-line waste
    lines = ["; ".join(groups[i:i + per]) for i in range(0, len(groups), per)]
    return "Strings drawn, each with the spec (L) or hand-off (H) line holding it verbatim", lines


def scan_packed(p: Path) -> list[str]:
    """0 inst, kit icons only, no boolean wrap, no banned string, in the packed sheet."""
    sh = json.loads(p.read_text(encoding="utf-8"))
    bad: list[str] = []

    def go(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("t") == "inst" or n.get("type") == "inst":
                bad.append(f"inst {n.get('name')}")
            g = n.get("icon")
            if isinstance(g, str) and g not in k.ICONS_OK:
                bad.append(f"icon {g}")
            o = n.get("o")
            if isinstance(o, dict) and isinstance(o.get("wrap"), bool):
                bad.append(f"boolean wrap {n.get('name')}")
            if n.get("wrap") is True or n.get("wrap") is False:
                bad.append(f"boolean wrap {n.get('name')}")
            for v in n.values():
                go(v)
        elif isinstance(n, list):
            for v in n:
                go(v)
        elif isinstance(n, str) and k.BANNED.search(n):
            bad.append("banned string")

    go({kk: v for kk, v in sh.items() if kk != "compactOf"})  # compactOf.file is the absolute source by design
    return bad


def emit(key: str, frames: list[dict[str, Any]], ann: dict[str, Any], *, notes: dict[str, Any] | None = None,
         summary: str = "", frames_info: tuple[str, ...] = (), **kw: Any) -> dict[str, Any]:
    """write_sheet -> validator (exit 0) -> write_md (line 3 theme word) -> pack_sheet -> mkcall4 count -> scans."""
    notes = dict(notes or {})
    notes.setdefault("sources", [])
    notes["sources"] = [*([notes["sources"]] if isinstance(notes["sources"], str) else notes["sources"]), R2_CREDIT]
    p = k.write_sheet(key, frames, ann, notes=notes, **kw)
    rc, msg = k.validate(p)
    md = k.write_md(key, p, summary=summary, frames_info=frames_info)
    l3 = md.read_text(encoding="utf-8").split("\n")[2]
    b = k.BOARDS[k.key_of(key)]
    if not l3.endswith(f"theme {b.theme}.") or f"page `{k.PAGE}`" not in l3:
        raise RuntimeError(f"md line 3: {l3}")
    pk = k.pack_sheet(p)
    cnt = subprocess.run([sys.executable, "-I", "-B", str(k.MKCALL), str(pk), "count"], capture_output=True,
                         text=True, timeout=120, check=False, cwd=str(k.CAP_DIR))  # bare compactOf.file
    raw = json.loads(p.read_text(encoding="utf-8"))
    bad = scan_packed(p) + scan_packed(pk)
    if bad or cnt.returncode != 0:
        raise RuntimeError(f"{pk.name}: scan {bad[:6]} mkcall4 rc {cnt.returncode}")
    shapes = sum(1 for s_ in raw["sections"] for _ in k.walk(s_["node"]))
    res = {"key": key, "sheet": str(p), "md": str(md), "packed": str(pk), "validator": msg.splitlines()[-1],
           "rc": rc, "sections": len(raw["sections"]), "count": cnt.stdout.strip(), "shapes": shapes,
           "frames": len(frames), "size": f"{raw['board']['w']} x {raw['board']['h']}", "line3": l3}
    print(json.dumps(res, ensure_ascii=False))
    return res
