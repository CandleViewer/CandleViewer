"""Group B helpers (boards 10D, 18D, 21D, 15D): build-run-validate-pack and the cite audit. Never edits the kit."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import e08d06kit as k  # noqa: E402

NUMERIC = re.compile(r"^[\s0-9.,:%+−\-−·×/()A-Za-z]{0,3}[0-9][0-9.,:%+−\-−· ]*[A-Za-z%]{0,6}$")


def texts(nodes: Iterable[dict[str, Any]]) -> list[str]:
    out = []
    for n in nodes:
        for _p, x in k.walk(n):
            if x["t"] == "text":
                out.append(x.get("chars") or x.get("text") or "")
    return out


def uncited(frames: Iterable[dict[str, Any]]) -> list[str]:
    """Frame strings that are neither verbatim in the spec/hand-off nor plain numbers (derived values)."""
    bad = []
    for s in texts(frames):
        s2 = s.strip()
        if not s2 or k.in_spec(s2) or NUMERIC.match(s2):
            continue
        bad.append(s2)
    return sorted(set(bad))


def cl(s: str) -> str:
    """A string with its spec / hand-off line, for an annotation line."""
    c = k.cite(s)
    if not c:
        raise LookupError(f"not verbatim in the spec or hand-off: {s!r}")
    return f"\"{s}\" ({c})"


def scan(packed: Path) -> list[str]:
    s = packed.read_text(encoding="utf-8")
    sh = json.loads(s)
    bad = []
    if re.search(r'"t"\s*:\s*"inst"', s):
        bad.append("inst node")
    if re.search(r'"wrap"\s*:\s*(true|false)', s):
        bad.append("boolean wrap")
    for ic in set(re.findall(r'"icon"\s*:\s*"([^"]+)"', s)):
        if ic not in k.ICONS_OK:
            bad.append(f"icon {ic}")
    body = json.dumps({kk: v for kk, v in sh.items() if kk != "compactOf"}, ensure_ascii=False)
    m = k.BANNED.search(body)  # compactOf.file is the absolute raw path by design (pack_sheet checks it)
    if m:
        bad.append(f"banned {m.group(0)!r}")
    if not sh.get("sections"):
        bad.append("no sections")
    return bad


def shapes(p: Path) -> int:
    sh = json.loads(p.read_text(encoding="utf-8"))
    n = 0

    def rec(x: Any) -> None:
        nonlocal n
        if isinstance(x, dict):
            if "t" in x and "name" in x:
                n += 1
            for v in x.values():
                rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)
    for s in sh["sections"]:
        rec(s["node"])
    return n + 1


def run(key: str, frames: list[dict[str, Any]], ann: dict[str, Any], *, summary: str = "",
        frames_info: Iterable[str] = (), allow_uncited: Iterable[str] = (), **kw: Any) -> None:
    left = [s for s in uncited(frames) if s not in set(allow_uncited)]
    if left:
        raise RuntimeError(f"board {key}: uncited frame strings {left[:12]}")
    p = k.write_sheet(key, frames, ann, **kw)
    md = k.write_md(key, p, summary=summary, frames_info=frames_info)
    v4 = k.pack_sheet(p)
    rc, msg = k.validate(p)
    cnt = subprocess.run([sys.executable, "-I", "-B", str(k.MKCALL), str(v4), "count"], capture_output=True,
                         text=True, timeout=120, check=False, cwd=str(k.CAP_DIR))  # bare compactOf.file
    bad = scan(v4) + scan(p)
    line3 = md.read_text(encoding="utf-8").splitlines()[2]
    print(f"{key}: {p.name} frames {len(frames)} shapes {shapes(p)} | validator exit {rc}: "
          f"{msg.splitlines()[-1] if msg else ''} | mkcall4 count {cnt.stdout.strip()} rc {cnt.returncode} | "
          f"scan {bad or 'clean'} | md3 ends {line3[-14:]!r}")
    if rc or cnt.returncode or bad:
        raise SystemExit(1)


def lean_cell(key: str, content: Any, w_: int, *, h: int, end: bool = False, typo: str = k.BODY,
              color: str = k.TEXT_1) -> dict[str, Any]:
    """k.cell's padding (8 px a side, the kit lint's rule) with fewer bytes: no gap / justify unless needed; the
    texts sit at the cell's top (a multi-line row reads from its first line)."""
    room = w_ - 2 * k.PX[k.INSET_SM]
    kids = [] if content in (None, "") else [k.fit_text("text", content, typo, color, room)] if isinstance(
        content, str) else (content if isinstance(content, list) else [content])
    o = {"dir": "row", "padX": k.INSET_SM, **({"justify": "end"} if end else {}),
         **({"gap": k.INSET_SM} if isinstance(content, list) and len(content) > 1 else {})}
    return k.box(f"cell · {key}", kids, o, w=w_, h=h)


def table(name: str, head: list[str] | None, rows: list[list[Any]], widths: list[int], *,
          typos: list[str] | None = None, ends: list[bool] | None = None, colors: list[str] | None = None,
          density: str = "compact", rules: bool = True) -> dict[str, Any]:
    """A padded-cell table (every cell 8 px a side via k.cell); a str / Node / None per cell; rows hairline-ruled."""
    n = len(widths)
    typos = typos or [k.BODY] * n
    ends = ends or [False] * n
    colors = colors or [k.TEXT_1] * n
    w = sum(widths)
    kids: list[Any] = []
    if head:
        hc = [lean_cell(f"h{j}", hd, widths[j], h=1, typo=k.LABEL, color=k.TEXT_2, end=ends[j]) for j, hd in
              enumerate(head)]
        hh = k._row_h(hc, density)
        kids += [k.hbox("header row", [dict(c, h=hh) for c in hc], None, w=w, h=hh),
                 k.rect("header rule", w, 1, k.BORDER)]
    for i, r in enumerate(rows, 1):
        cs = [lean_cell(f"c{j}", v, widths[j], h=1, typo=typos[j], color=colors[j], end=ends[j])
              for j, v in enumerate(r)]
        hh = k._row_h(cs, density)
        kids += [k.box(f"row {i:02d}", [dict(c, h=hh) for c in cs], {"dir": "row"}, w=w, h=hh)]
        if rules:
            kids.append(k.rect(f"rule {i:02d}", w, 1, k.BORDER_SUBTLE))
    return k.vbox(name, kids, None, w=w)


def section(name: str, title: str, kids: list[Any], w: int, note: str | None = None) -> dict[str, Any]:
    return k.vbox(name, [k.text("title", title, k.HEADING_SM, k.TEXT_1), *kids], {"gap": k.STACK_SM}, w=w,
                  note=note)


def size_rings(n: dict[str, Any]) -> dict[str, Any]:
    """k.ring() leaves its wrapper without w / h; a text-less ring (the close glyph) then fails the kit lint
    ("flex child without text and without h"). Give each such wrapper its child's size + 4 px a side."""
    kids = n.get("kids")
    if kids:
        n = dict(n, kids=[size_rings(c) for c in kids])
    if n.get("name") == "focus-ring" and not n.get("h") and kids and kids[0].get("h") and kids[0].get("w"):
        n = dict(n, w=kids[0]["w"] + 8, h=kids[0]["h"] + 8)
    return n


R2_CREDIT = (f"Seed data: the r2 board script's DATA block, sha256 {k.R2_SHA256[:8]}…{k.R2_SHA256[-4:]}, posted "
             f"2026-10-23 on #174 (values re-derived by the §5 formatters)")
