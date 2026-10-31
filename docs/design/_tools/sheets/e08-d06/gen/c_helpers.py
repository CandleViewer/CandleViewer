"""Group C helpers (boards 23D, 25D and 25's high-contrast twin): the §6 states-matrix table, the verbatim-copy
block, the hc board path and an independent packed-sheet scan. The kit (e08d06kit.py) is imported, never edited."""
from __future__ import annotations

import contextlib
import json
import re
import sys
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator

KIT_DIR = Path(__file__).resolve().parent.parent
if str(KIT_DIR) not in sys.path:
    sys.path.insert(0, str(KIT_DIR))
import e08d06kit as k  # noqa: E402

R2_CREDIT = (f"r2 board data: the DATA block of the posted board script (posted 2026-10-23, 4 parts), sha256 "
             f"{k.R2_SHA256[:8]}…{k.R2_SHA256[-4:]}; read as data only, every value re-derived by the kit")
CVD_LIVE = ("CVD: run the colour-vision simulation (protanopia, deuteranopia) on the exported PNG; every state stays "
            "readable by its words and glyphs (§10.3 'Colour'); tritanopia deferred (no simulator output; a C-row to "
            "the tool's owner, ruling 2026-10-31)")


# --- copy: every drawn string with its spec / hand-off line, grouped by line (one annotation block)
def strings_of(nodes: Iterable[k.Node]) -> list[str]:
    seen: dict[str, None] = {}
    for n in nodes:
        for _p, x in k.walk(n):
            if x["t"] == "text":
                seen.setdefault(x["chars"], None)
    return list(seen)


def subst_source(s: str) -> str | None:
    """r2's recorded substitution that produced s (its spec source and pairs), or None."""
    for key, v in k.D["_subst"].items():
        out = v["src"]
        for p in v["pairs"]:
            out = out.replace(p[0], p[1])
        if out == s:
            src = k.cite(v["src"])
            evid = "; ".join(f"{p[0]!r} -> {p[1]!r} per "
                             f"{(k.cite(p[2]) or p[2][:40]) if len(p) > 2 else 'the fixture'}" for p in v["pairs"])
            return f"r2 substitution {key}: {src} {v['src']!r} with {evid}"
    return None


def cite_pref(s: str) -> str | None:
    """The line in §3 (anatomy) or §4 (field catalogue) holding s verbatim, else k.cite(s): a label's home line beats
    its first mention (e.g. "Status" on the ticket's header line)."""
    lo, hi = k.L("## 3. Anatomy"), k.L("## 5. Number formatting")
    probe = s.strip()
    if len(probe) >= 4:
        for i in range(lo, hi):
            ln = k.SPEC_LINES[i - 1]
            if probe in ln or probe in ln.replace("`", ""):
                return f"L{i}"
    return k.cite(s)


def copy_block(nodes: Iterable[k.Node], derived_values: dict[str, str], *, title: str = "Copy (verbatim)",
               max_line: int = 340) -> tuple[str, list[str]]:
    """Group every drawn string by the spec/hand-off line that holds it verbatim; derived values name their source
    (F-rule + fixture); substituted strings name r2's recorded substitution. Raises on an unaccounted string."""
    by_line: dict[str, list[str]] = {}
    extra: list[str] = []
    for s in strings_of(nodes):
        if s in derived_values:
            k.derived(f"{s!r}: {derived_values[s]}")
            continue
        c = cite_pref(s)
        if c:
            by_line.setdefault(c, []).append(s)
            continue
        sub = subst_source(s)
        if sub:
            k.copy_gap(f"{s!r}: {sub}")
            extra.append(f"{s} ({sub.split(':')[0]}; see notes)")
            continue
        if k.in_spec(s):
            by_line.setdefault("wrapped", []).append(s)
            continue
        raise LookupError(f"string not in the spec, the hand-off, the derivations or r2's substitutions: {s!r}")
    lines, cur = [], ""
    order = sorted(by_line, key=lambda c: (c[0], int(c[1:]) if c[1:].isdigit() else 10 ** 6))
    for c in order:
        part = f"{c}: " + "; ".join(f'"{s}"' for s in by_line[c])
        if cur and len(cur) + 3 + len(part) > max_line:
            lines.append(cur)
            cur = part
        else:
            cur = f"{cur} · {part}" if cur else part
    if cur:
        lines.append(cur)
    return title, lines + extra


# --- Decimal helpers for the rule examples (§5 F3 examples re-derived from the fixture's tick / step)
def round_to(v: str, inc: str, mode: str) -> str:
    d, q = Decimal(v), Decimal(inc)
    r = (d / q).quantize(Decimal(1), rounding=ROUND_HALF_UP if mode == "nearest" else ROUND_DOWN) * q
    return k.minimal(str(r))


# --- board 23: the §6 states × bands matrix (r2 `matrix`: head + 23 rows; every cell a verbatim excerpt of its row)
MATRIX_STATE_W = 192
T2_ROWS = ("Not recorded, Manager or Viewer", "Not recorded, Owner viewing as")


def matrix_rows() -> tuple[list[str], list[list[str]], list[tuple[int, int, int, int]]]:
    """r2's head and rows, checked against the spec: each row's state is a §6 state (same order as STATES), each cell
    a substring of that row's spec line; returns (head, rows, excerpts) where excerpts = (line, col, drawn, full)."""
    m = k.R2_BOARDS[23]["matrix"]
    head, rows = m["head"], m["rows"]
    if [r[0] for r in rows] != list(k.STATES):
        raise ValueError("matrix rows are not §6's 23 states in order")
    hl = k.find_line("| State (trigger)")
    src_head = k.SPEC_LINES[hl - 1]
    if any(h not in src_head for h in head):
        raise ValueError("matrix head not in §6's header line")
    excerpts = []
    for r in rows:
        ln = k.STATES[r[0]]
        src = k.SPEC_LINES[ln - 1].replace("`", "").replace("**", "")
        full = [c.strip() for c in src.strip().strip("|").split("|")]
        for j, c in enumerate(r):
            if c not in src:
                raise ValueError(f"L{ln} col {j}: {c!r} is not in the row")
            if j and c != full[j]:
                excerpts.append((ln, j, len(c), len(full[j])))
    return head, rows, excerpts


def _mrow(key: str, cells: list[tuple[str, int]], *, typo: str, color: str, first_typo: str, fill: str | None,
          density: str) -> k.Node:
    room = [w - 2 * k.PX[k.INSET_SM] for _c, w in cells]
    need = max(k.text_h(ty, k.text_lines(c, ty, r)) for i, ((c, _w), r) in enumerate(zip(cells, room))
               for ty in [first_typo if i == 0 else typo])
    h = max(k.ROW_H[density], int(-(-(need + 8) // 4) * 4))
    kids = [k.cell(f"{key} · c{i}", c, w, h=h, typo=first_typo if i == 0 else typo,
                   color=color) for i, (c, w) in enumerate(cells)]
    o = {"align": "start"}
    if fill:
        o["fill"] = fill
    return k.hbox(f"row · {key}", kids, o, w=sum(w for _c, w in cells), h=h)


def matrix(w_: int, *, density: str = "compact") -> tuple[k.Node, float]:
    """The table: a header row (color.surface.raised, label, secondary) and 23 rows (state in label primary, cells in
    caption primary), hairline rules (color.border.subtle) between rows; the two T2 rows on color.surface.sunken."""
    head, rows, _ex = matrix_rows()
    col_w = (w_ - MATRIX_STATE_W) // 4
    widths = [MATRIX_STATE_W] + [col_w] * 4
    widths[-1] += w_ - sum(widths)
    kids: list[k.Node] = [_mrow("head", list(zip(head, widths)), typo=k.LABEL, color=k.TEXT_2, first_typo=k.LABEL,
                                fill=k.RAISED, density=density)]
    for i, r in enumerate(rows, 1):
        row = _mrow(f"{i:02d}", list(zip(r, widths)), typo=k.CAPTION, color=k.TEXT_1,
                    first_typo=k.LABEL, fill=k.SUNKEN if r[0] in T2_ROWS else None, density=density)
        kids.append(k.vbox(f"tr · {i:02d}", [k.rect("rule", w_, 1, k.BORDER_SUBTLE), row], {}, w=w_,
                           h=row["h"] + 1))
    h = sum(x["h"] for x in kids)
    tbl = k.vbox("table · §6 states × bands", kids, {}, w=w_, h=h,
                 note='table, a caption names it ("States × bands"); row headers are the state cells (th scope=row)')
    return tbl, h


# --- the high-contrast twin (the kit has no hc path): same nodes, theme word "hc", root " · high contrast",
#     export §15's pattern with "-hc", token-bound like the light twins (theme `high-contrast` switched at export)
HC_THEME = "hc"
HC_TOKEN_THEME = "high-contrast"  # the token theme activated at export (set semantic-hc in token-sync.json)


@dataclass(frozen=True)
class HcBoard(k.Board):
    @property
    def key(self) -> str:
        return f"{self.n}H"

    @property
    def name(self) -> str:
        return f"E08-D06 / {self.n:02d} {self.sid.replace('/', '∕')} · high contrast"


def hc_board(n: int) -> HcBoard:
    b = k.BOARDS[f"{n}D"]
    return HcBoard(b.n, b.sid, b.w, b.h, b.twinned, b.content, b.line, HC_THEME)


@contextlib.contextmanager
def hc_registered(n: int) -> Iterator[HcBoard]:
    """Register board <n>H in the kit's registry for one write (key_of accepts "H"; the kit's theme live line names
    the `high-contrast` token theme); everything is restored on exit."""
    hb = hc_board(n)
    key_of0, live0 = k.key_of, k.live

    def key_of(nn: int | str) -> str:
        if isinstance(nn, str) and re.fullmatch(rf"0*{n}H", nn):
            return hb.key
        return key_of0(nn)

    def live(line: str) -> None:
        live0(line.replace("activate the hc token set", f"activate the {HC_TOKEN_THEME} token theme (set semantic-hc)")
              .replace("as the hc value", f"as the {HC_TOKEN_THEME} value"))

    k.BOARDS[hb.key] = hb
    k.key_of, k.live = key_of, live
    try:
        yield hb
    finally:
        k.key_of, k.live = key_of0, live0
        k.BOARDS.pop(hb.key, None)


def hc_annotations(hb: HcBoard, blocks: Iterable[tuple[str, list[str]]], *,
                   board_lines: Iterable[str] = ()) -> k.Node:
    """k.annotations' column for the hc twin, with the hc words (the kit's says 'light twin' / 'board NN light')."""
    head = [f"§15 L{hb.line}: {hb.content}",
            f"Size {hb.w} × {hb.h}; theme hc (high-contrast twin of board {hb.n}: same frames, same values, re-bound "
            f"by the {HC_TOKEN_THEME} theme switch at export)", f"Export: {hb.export}", *board_lines]
    kids = [k.text("title", hb.name, k.HEADING_SM, k.TEXT_1, w=k.ANN_TEXT_W)]
    for i, (lab, lines_) in enumerate([("Board", head), *blocks], 1):
        bk = [k.text("label", lab, k.LABEL, k.TEXT_2, w=k.ANN_TEXT_W)] + [
            k.text(f"value-{j}", ln, k.CAPTION, k.TEXT_1, w=k.ANN_TEXT_W) for j, ln in enumerate(lines_, 1)
            if ln.strip()]
        kids.append(k.vbox(f"block-{i:02d}", bk, {"gap": k.STACK_XS}, w=k.ANN_TEXT_W))
    kids.append(k.text("footer", f"page {k.PAGE} · board {hb.n:02d} high contrast · {k.REV}", k.CAPTION, k.TEXT_3,
                       w=k.ANN_TEXT_W))
    return k.vbox("annotations", kids, {"gap": k.STACK_SM, "pad": k.INSET_LG, "fill": k.CANVAS}, w=k.ANN_W)


# --- independent scan of a packed (or raw) sheet: 0 inst, allowed icons, no boolean wrap, no banned string,
#     no painted colour
def scan(path: Path) -> dict[str, Any]:
    sh = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, Any] = {"inst": 0, "icons": set(), "bad_icons": [], "bool_wrap": 0, "painted": [], "nodes": 0}

    def rec(x: Any) -> None:
        if isinstance(x, dict):
            if "t" in x and "name" in x:
                out["nodes"] += 1
                if x["t"] == "inst":
                    out["inst"] += 1
                if x["t"] == "icon":
                    out["icons"].add(x.get("icon"))
                    if x.get("icon") not in k.ICONS_OK:
                        out["bad_icons"].append(x.get("icon"))
                for ck in ("color",):
                    if ck in x and not str(x[ck]).startswith("color."):
                        out["painted"].append(x[ck])
            o = x.get("o") if isinstance(x.get("o"), dict) else {}
            if isinstance(o.get("wrap"), bool) or isinstance(x.get("wrap"), bool):
                out["bool_wrap"] += 1
            for ck in ("fill", "stroke"):
                if ck in o and not str(o[ck]).startswith("color."):
                    out["painted"].append(o[ck])
            for v in x.values():
                rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)

    rec(sh.get("sections", sh))
    body = {kk: v for kk, v in sh.items() if kk != "compactOf"}  # the packer's absolute source path, by design
    banned = sorted({m.group(0) for m in k.BANNED.finditer(json.dumps(body, ensure_ascii=False))})
    out["banned"] = banned
    out["icons"] = sorted(out["icons"])
    out["ok"] = not (out["inst"] or out["bad_icons"] or out["bool_wrap"] or out["painted"] or banned)
    return out


def finish(key_label: str, sheet: Path, md: Path) -> None:
    """Pack, mkcall4-count (the kit checks it), scan raw + packed, print one tail per board."""
    import subprocess
    packed = k.pack_sheet(sheet)
    cnt = subprocess.run([sys.executable, "-I", "-B", str(k.MKCALL), str(packed), "count"], capture_output=True,
                         text=True, timeout=120, check=False, cwd=str(k.CAP_DIR))  # bare compactOf.file
    rc, msg = k.validate(sheet)
    raw, pk = scan(sheet), scan(packed)
    if rc != 0 or cnt.returncode != 0 or not raw["ok"] or not pk["ok"]:
        raise RuntimeError(f"{key_label}: validator {rc}, mkcall4 {cnt.returncode}, scan raw {raw} packed {pk}")
    sh = json.loads(sheet.read_text(encoding="utf-8"))
    print(f"{key_label}: {sheet.name} | root {sh['board']['name']!r} {sh['board']['w']}x{sh['board']['h']} at "
          f"({sh['board']['x']}, {sh['board']['y']}) | sections {len(sh['sections'])} | shapes {raw['nodes']} | "
          f"validator exit {rc}: {msg.splitlines()[-1] if msg else ''} | mkcall4 count {cnt.stdout.strip()} | "
          f"scan inst {pk['inst']} icons {pk['icons']} boolwrap {pk['bool_wrap']} banned {pk['banned']} | "
          f"md {md.name} line3 {md.read_text(encoding='utf-8').splitlines()[2][-12:]!r} | packed {packed}")
