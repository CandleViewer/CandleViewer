"""Build every board twice and check the set (python3 -X utf8 -I -B check_all.py; CV_CHECKOUT names the checkout unless
the kit sits in one). Gates: the kit self-test; every generator exits 0 (validator exit 0 inside); the rebuild is
byte-identical (raw sheets, .md, packed); per board: 0 inst nodes, only the local icons, no boolean wrap, no banned
string (raw, .md, packed outside the pack-source record), no backtick in any drawn text, LF line ends only, greyscale
(no hue bound), table cells padded 8 px a side (>= 16 px between texts), a "state: <id>" caption per frame, no "/" in
the root name after the prefix, md line 3, the packed sheet's source sha256 = the raw sheet's and mkcall4 count = its
sections, the packed sections expanding to the raw ones, no never-token bound (color.text.disabled, opacity.disabled),
the synthetic-data and C-2.11 statement under the frames, the spec md5 pin in the sheet's sources; the set: the
source md5 pins, <= 10 boards with twins <= 1/3, §2's every state drawn on its §0 board, the T2 renderings (E09-D09
§2.1: the CMP-019 lock, color.surface.raised + color.border.default, the label color.text.tertiary, the reason its
own line in color.text.secondary), AC 3 (every breached cell on the greyscale frame carries its word and its glyph
slot and no shade), no focus ring wider than the parent that clips it (its left edge, the flex parent's leading
padding or its own x, plus its width within the parent's w). Every Python child runs with -X utf8."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
import e20d02kit as k  # noqa: E402

sys.path.insert(0, str(KIT / "gen"))
import ui  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return k.run_py(args, 900)


def digest() -> dict[str, str]:
    out = {}
    for d in (k.CAP_DIR, k.V4_DIR):
        for p in sorted(d.glob("[0-9][0-9]-*")):
            if p.suffix in (".json", ".md"):
                out[f"{d.name}/{p.name}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def build_all() -> None:
    for nn in sorted(k.BOARDS):
        r = run([str(KIT / "gen" / f"gen_{nn:02d}.py")])
        tail = (r.stdout + r.stderr).strip().splitlines()
        check(r.returncode == 0, f"gen_{nn:02d}: {tail[-1][:160] if tail else ''}")


def frame_nodes(raw: dict, fid: str) -> list[dict]:
    fn = k.frame_name(fid)
    return [n for s in raw["sections"] for p, n in k.walk(s["node"], s["into"]) if p.split("/")[0] == fn]


def load(nn: int) -> dict:
    return json.loads((k.CAP_DIR / k.BOARDS[nn].sheet).read_text(encoding="utf-8"))


def tick_nodes(sheet: dict) -> list[str]:
    """Drawn text carrying a markdown backtick (text() strips them; any survivor fails the set)."""
    return [n["name"] for s in sheet["sections"] for _p, n in k.walk(s["node"])
            if n.get("t") == "text" and "`" in str(n.get("chars", ""))]


def ring_overflows(sheet: dict) -> tuple[int, list[str]]:
    """Every focus ring against the parent that holds (and clips) it: the ring's left edge (a flex parent's leading
    padding, else the ring's own x) plus its width must lie within the parent's w, or Penpot cuts the ring's right
    side (07's 192 px ring in its 184 px menu item, live check 2026-11-04). Parents that hug have no w and pass."""
    rings, over = 0, []
    for sec in sheet["sections"]:
        for p, n in k.walk(sec["node"], sec["into"]):
            if n["t"] != "board" or not n.get("w"):
                continue
            o = n.get("o") or {}
            lead = k._px(o.get("pad")) + k._px(o.get("padX")) + k._px(o.get("padL"))
            for c in n.get("kids") or []:
                if not c.get("name", "").startswith("focus ring"):
                    continue
                rings += 1
                left = lead if o.get("dir") and not c.get("abs") else float(c.get("x") or 0)
                if left + k.est_width(c) > float(n["w"]) + 0.5:
                    over.append(f"{p}/{c['name']} {left:g} + {k.est_width(c):g} > {n['w']}")
    return rings, over


def ring_checks() -> None:
    total, over = 0, []
    for nn in sorted(k.BOARDS):
        r, o = ring_overflows(load(nn))
        total += r
        over += [f"{nn:02d} {x}" for x in o]
    check(total > 0 and not over, f"focus rings: {total}, none wider than its container {over[:3]}")


def mutation_checks() -> None:
    """The backtick gate fires on a planted backtick, and the ring gate on a widened ring (in memory; nothing is
    written)."""
    raw7 = json.loads(json.dumps(load(7)))
    ring = next(c for s in raw7["sections"] for _p, n in k.walk(s["node"]) for c in n.get("kids") or []
                if n.get("w") and c.get("name", "").startswith("focus ring"))
    ring["w"] = 10_000
    check(not ring_overflows(load(7))[1] and len(ring_overflows(raw7)[1]) == 1,
          "mutation: a widened focus ring fails the set")
    raw = load(1)
    mut = json.loads(json.dumps(raw))
    first = next(n for s in mut["sections"] for _p, n in k.walk(s["node"]) if n.get("t") == "text")
    first["chars"] = "`" + first["chars"]
    check(not tick_nodes(raw) and len(tick_nodes(mut)) == 1, "mutation: a planted backtick fails the set")


def scan(nn: int) -> None:
    b = k.BOARDS[nn]
    raw_p, md_p, pk_p = k.CAP_DIR / b.sheet, k.CAP_DIR / (b.sheet[:-5] + ".md"), k.V4_DIR / b.sheet
    raw = json.loads(raw_p.read_text(encoding="utf-8"))
    pk = json.loads(pk_p.read_text(encoding="utf-8"))
    src_key = next(x for x in pk if x.startswith("compact"))
    nodes = [n for s in raw["sections"] for _p, n in k.walk(s["node"])]
    pnodes = json.dumps(pk["sections"], ensure_ascii=False)
    check(not any(n["t"] == "inst" for n in nodes) and '"t":"inst"' not in pnodes.replace(" ", ""),
          f"{nn:02d}: 0 inst nodes ({len(nodes)} shapes, {len(raw['sections'])} raw / {len(pk['sections'])} packed "
          f"sections)")
    bad_icons = sorted({n["icon"] for n in nodes if n["t"] == "icon"} - k.ICONS_OK)
    check(not bad_icons, f"{nn:02d}: icons in the local set {bad_icons}")
    check(all((n.get("o") or {}).get("wrap", "nowrap") in ("wrap", "nowrap") for n in nodes),
          f"{nn:02d}: no boolean wrap")
    banned = k._scan_banned(raw) + k._scan_banned({x: y for x, y in pk.items() if x != src_key})
    banned += sorted({m.group(0) for m in k.BANNED.finditer(md_p.read_text(encoding="utf-8"))})
    check(not banned, f"{nn:02d}: no forbidden strings {banned}")
    ticks = tick_nodes(raw) + tick_nodes(pk)
    check(not ticks, f"{nn:02d}: no backtick in drawn text {ticks[:3]}")
    crlf = [p.name for p in (raw_p, md_p, pk_p) if b"\r" in p.read_bytes()]
    check(not crlf, f"{nn:02d}: LF line ends only {crlf}")
    hues = sorted({v for n in nodes for v in [n.get("color"), *(n.get("o") or {}).values()]
                   if isinstance(v, str) and v.startswith("color.") and v not in k.GREY})
    check(not hues, f"{nn:02d}: greyscale only {hues}")
    cells = [(p, n) for s in raw["sections"] for p, n in k.walk(s["node"], s["into"])
             if n["t"] == "board" and re.search(r"/(header row|row · \d+)/[^/]+$", p, re.DOTALL)]
    check(all((n.get("o") or {}).get("padX") == k.INSET_SM for _p, n in cells),
          f"{nn:02d}: {len(cells)} table cells, 8 px a side (>= 16 px between texts)")
    caps = {n["chars"] for n in nodes if n["t"] == "text" and n["name"].startswith("caption ")}
    check(all(f"state: {f}" in caps for f in b.frames), f"{nn:02d}: a caption on each of {len(b.frames)} frames")
    check("/" not in raw["board"]["name"].split(f"{k.KEY} / {nn:02d} ", 1)[1], f"{nn:02d}: no '/' after the prefix")
    md = md_p.read_text(encoding="utf-8").split("\n")
    check(md[2] == k.md_line3(nn), f"{nn:02d}: md line 3")
    side = KIT / md_p.name
    check(side.is_file() and side.read_bytes() == md_p.read_bytes(), f"{nn:02d}: the sidecar beside the kit = the build")
    check(raw["board"]["h"] == k.MEASURED_H.get(nn), f"{nn:02d}: root h = the measured {k.MEASURED_H.get(nn)}")
    check(pk[src_key] == {"file": raw_p.name, "sha256": hashlib.sha256(raw_p.read_bytes()).hexdigest()},
          f"{nn:02d}: packed source = bare raw file name (no path) + sha256 = raw")
    c = k.run_py([str(k.MKCALL), str(pk_p), "count"], 900, cwd=k.CAP_DIR)
    check(c.returncode == 0 and c.stdout.strip() == str(len(pk["sections"])), f"{nn:02d}: mkcall4 count "
          f"{c.stdout.strip()} = {len(pk['sections'])} sections")
    bound = {v for n in nodes for v in [*(n.get("o") or {}).values(), n.get("color"), n.get("typo"), n.get("size")]
             if isinstance(v, str)}
    check(not bound & set(k.NEVER), f"{nn:02d}: never-tokens bound nowhere ({len(bound)} tokens bound)")
    stmt = [n["chars"] for n in nodes if n["name"] == "footer · data statement"]
    check(len(stmt) == 1 and stmt[0].startswith("Data: synthetic only") and "C-2.11" in stmt[0],
          f"{nn:02d}: synthetic data and C-2.11 declared")
    check(any(k.DOCS["spec"][1] in s for s in raw["notes"]["sources"]), f"{nn:02d}: spec md5 pin in the sources")
    v = k.validate(raw_p)
    check(v[0] == 0, f"{nn:02d}: {v[1].splitlines()[-1]}")
    sys.path.insert(0, str(k.TOOLS))
    import compact  # noqa: E402
    exp = [(s["into"], compact.materialize(compact.expand_styles(s["node"], s.get("styles", {}))))
           for s in pk["sections"]]
    check(len(exp) == len(raw["sections"]) and all(i == s.get("into", "") and compact.same(n, s["node"])
                                                    for (i, n), s in zip(exp, raw["sections"]))
          and all(pk[x] == raw[x] for x in ("board", "export", "notes")),
          f"{nn:02d}: packed sections expand to the raw ones ({len(exp)}), so the raw validator verdict covers them")


def is_t2(n: dict) -> bool:
    """E09-D09 §2.1: raised fill + the default hairline, the lock leading, the label tertiary; no never-token."""
    o = n.get("o") or {}
    ks = [x for _p, x in k.walk(n)]
    return (o.get("fill") == k.RAISED and o.get("stroke") == k.BORDER and o.get("strokeWidth") == k.HAIR
            and ks[1]["t"] == "icon" and ks[1]["icon"] == "locked" and ks[1]["color"] == k.TEXT_3
            and any(x["t"] == "text" and x["color"] == k.TEXT_3 for x in ks)
            and not any(v in k.NEVER for x in ks for v in [x.get("color"), *(x.get("o") or {}).values()]))


def t2_checks() -> None:
    sites = ((8, "SCR-033/source-unavailable", "checkbox OI Δ · T2 2a", "T2 reason (W-14)", k.W("W-14")),
             (8, "SCR-033/view-as", "CMP-001 Apply · T2 2a", "words", k.W("W-17", user=k.VIEW_AS_USER)),
             (7, "SCR-033/row-menu", "menuitem Move up · T2 2a", "T2 reason (W-16, second line)", k.W("W-16", 0)),
             (8, "SCR-033/apply-no-write", "CMP-001 Apply · T2 2a", "T2 reason (Apply)",
              "Your role can't save workspaces."))
    for nn, fid, nm, rn, words in sites:
        ns = frame_nodes(load(nn), fid)
        t2 = [n for n in ns if n["name"] == nm]
        rs = [n for n in ns if n["t"] == "text" and n["name"] == rn and n["chars"] == words]
        ok = len(t2) == 1 and is_t2(t2[0]) and len(rs) == 1 and rs[0]["color"] == k.TEXT_2 and \
            not any(x is rs[0] for _p, x in k.walk(t2[0]))
        check(ok, f"{nn:02d} {fid}: T2 — lock, raised + default hairline, tertiary label; the reason \"{words}\" its "
                  f"own line in color.text.secondary")
    ns = frame_nodes(load(8), "SCR-033/source-unavailable")
    gate = [n for n in ns if n["name"] == "CMP-079 RbacGate"]
    check(len(gate) == 1 and any(x["name"] == "checkbox OI Δ · T2 2a" for _p, x in k.walk(gate[0])),
          "08: CMP-079 RbacGate wraps the OI Δ checkbox")
    ns = frame_nodes(load(8), "SCR-033/view-as")
    nt = [n for n in ns if n["name"] == "header notice (view-as)"]
    check(len(nt) == 1 and any(x["t"] == "icon" and x["icon"] == "locked" for _p, x in k.walk(nt[0])),
          "08: view-as — one header notice with the lock (R32:57)")


def ac3_checks() -> None:
    raw = load(4)
    want = sorted((lab, b.t) for b in k.window(16) for lab in ("Delta", "Delta %") if k.breached(lab, b))
    for fid, shade in (("SCR-030/strip-ThresholdsBreached", len(want)), ("SCR-030/strip-ThresholdsBreached-greyscale",
                                                                         0)):
        ns = frame_nodes(raw, fid)
        words = [n for n in ns if n["name"].startswith("Strong · ") and n["chars"] == k.W("W-3")]
        slots = [n for n in ns if n["name"].startswith("breach-glyph slot · ")]
        shades = [n for n in ns if n["name"].startswith("shade slot")]
        check(len(words) == len(slots) == len(want) and len(shades) == shade,
              f"04 {fid}: {len(want)} breached cells, each with the word and the glyph slot; {len(shades)} shades")


def live_fold_checks() -> None:
    """The live check's marker fold: each pinned 'how' caption is drawn once, wrapped at its marker's w - 16, and its
    marker takes the pinned h; every other 'how' caption is one line."""
    seen: dict[str, list[tuple[int, int, int]]] = {}
    plain = 0
    for nn in sorted(k.BOARDS):
        for _p, n in (x for sec in load(nn)["sections"] for x in k.walk(sec["node"])):
            if n["t"] != "board" or not n["name"].startswith("board marker · "):
                continue
            for c in n.get("kids") or []:
                if c.get("name") != "how":
                    continue
                if c["chars"] in ui.LIVE_HOW:
                    seen.setdefault(c["chars"], []).append((nn, n["w"] - 16 - (c.get("w") or 0), n["h"]))
                else:
                    plain += 0 if c.get("w") else 1
    ok = sorted(seen) == sorted(ui.LIVE_HOW) and all(
        len(v) == 1 and v[0][1] == 0 and v[0][2] == ui.LIVE_HOW[s][1] for s, v in seen.items())
    check(ok, f"live fold: {len(seen)} wrapped 'how' captions at marker w - 16 with their pinned h; {plain} one-line")


def main() -> int:
    r = run([str(KIT / "e20d02kit.py"), "selftest"])
    out = r.stdout.strip().splitlines()
    check(r.returncode == 0, f"kit self-test: {out[-1] if out else r.stderr.strip()[-200:]}")
    check(all(k.spec_md5_ok().values()), "spec / floor / fixture md5 pins: " +
          ", ".join(f"{x} {m[:8]}" for x, (_p, m) in k.DOCS.items()))
    check(len(k.BOARDS) <= 10 and 3 * sum(b.twin for b in k.BOARDS.values()) <= len(k.BOARDS),
          f"{len(k.BOARDS)} boards, {sum(b.twin for b in k.BOARDS.values())} light twins (≤ ⅓)")
    check(all(k.board_of(f) == k.STATES[f][1] for f in k.ALL_FRAMES) and sorted(k.STATES) == sorted(k.ALL_FRAMES),
          f"§2: all {len(k.STATES)} states drawn on their §0 boards")
    build_all()
    first = digest()
    build_all()
    second = digest()
    diff = sorted(x for x in set(first) | set(second) if first.get(x) != second.get(x))
    check(not diff and len(first) == 3 * len(k.BOARDS), f"rebuild byte-identical ({len(first)} files; differing "
                                                         f"{diff[:4]})")
    for nn in sorted(k.BOARDS):
        scan(nn)
    t2_checks()
    ac3_checks()
    live_fold_checks()
    ring_checks()
    mutation_checks()
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failures")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
