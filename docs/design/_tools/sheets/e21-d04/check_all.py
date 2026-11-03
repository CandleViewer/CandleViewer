"""Scan the ten E21-D04 sheets (raw in CAP_DIR, packed in V4_DIR): validator (with the shared components list), mkcall4
count, compactOf (bare name + the raw sheet's sha256), every T2 control with its reason and the notice (forced colours
too), no inst, local icons only, no boolean wrap, no '/' in node names, no banned string, no NEVER token, colour binds
semantic only, a "state:" caption per frame, table cells padded 8 px a side with their text inside (>= 16 px between
texts), row / column overflow and sibling overlap by the kit's estimates, the spec md5 pin. With --rebuild it first
runs every generator twice and requires byte-identical raw, md and packed files. Run: python3 -I -B check_all.py
[--rebuild]"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e21d04kit as k  # noqa: E402

CAP, V4 = k.CAP_DIR, k.V4_DIR
# drawn on top by design (board markers, trays, announcements, the thumb on its track, the frame and chip over a
# panel, strips, scrims, an open menu): excluded from the sibling-overlap estimate
OVERLAY = re.compile(r"^(board marker|CMP-041 Menu|pulled mark|CMP-227 marker|visible word|ask run|bid run|"
                     r"bid riser|label (bid|ask)|ring gap|mark rule|leader)", re.DOTALL)


def tree(sheet: dict) -> dict:
    root = dict(sheet["board"], t="board", kids=[])
    for s in sheet["sections"]:
        parent = root
        for seg in [x for x in s["into"].split("/") if x]:
            parent = next(c for c in parent["kids"] if c["name"] == seg)
        node = json.loads(json.dumps(s["node"]))
        same = [c for c in parent.setdefault("kids", []) if c["name"] == node["name"]]
        if same:  # a continuation section: kids appended to the node drawn earlier
            same[0].setdefault("kids", []).extend(node.get("kids") or [])
        else:
            parent["kids"].append(node)
    return root


def walk(n: dict, path: str = ""):
    p = f"{path}/{n['name']}" if path else n["name"]
    yield p, n
    for c in n.get("kids") or []:
        yield from walk(c, p)


def _digest() -> dict[str, str]:
    files = [*sorted(CAP.glob("[0-9][0-9]-*")), *sorted(V4.glob("[0-9][0-9]-*.json"))]
    return {str(f.relative_to(f.parent.parent)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def rebuild() -> list[str]:
    """Run every generator twice; the second run must leave every raw, md and packed file byte-identical."""
    runs = []
    for _ in range(2):
        for nn in k.BOARDS:
            r = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(HERE / "gen" / f"gen_{nn:02d}.py")],
                               capture_output=True, text=True, encoding="utf-8", check=False)
            if r.returncode:
                return [f"gen_{nn:02d}.py exit {r.returncode}: {(r.stdout + r.stderr).strip()[-300:]}"]
        runs.append(_digest())
    diff = sorted(f for f in set(runs[0]) | set(runs[1]) if runs[0].get(f) != runs[1].get(f))
    print(f"rebuild: {len(runs[1])} files, {'byte-identical' if not diff else f'{len(diff)} differ'}")
    return [f"rebuild differs: {f}" for f in diff]


def t2_findings(frames: list[dict]) -> list[str]:
    """G-T2.1c / G-T2.2 / G-T2.5: a frame that draws a T2 control (a T2 item or the LOCKED pill) also draws its
    reason (W-20) and the panel's notice (the header notice, or the row menu's label that carries its sentence);
    under forced colours (§5.5's last row) the notice reads CanvasText on Canvas (the stand-ins TEXT_1 on APP)."""
    bad, w20 = [], k.W("W-20")
    for f in frames:
        nodes = [n for _p, n in walk(f)]
        if not any(n["name"].startswith(("T2 item", "CMP-229 ArmToggle")) for n in nodes):
            continue
        notices = [n for n in nodes if n["name"] == "header notice (G-T2.5)" or n["name"].startswith("menu label")]
        said = [n for n in notices if any(c["t"] == "text" and c["name"] == "reason" and c["chars"] == w20
                                          for c in n.get("kids") or [])]
        if not said:
            bad.append(f"{f['name']}: a T2 control with no notice carrying W-20")
        menu = any(n["name"].startswith("CMP-041 Menu") for n in nodes)
        if not menu and not any(n["t"] == "text" and n["name"].startswith("reason (") and n["chars"] == w20
                                for n in nodes):
            bad.append(f"{f['name']}: a T2 control with no reason of its own (2a)")
        if "Forced colours" in f["name"]:
            for n in said:
                fill = (n.get("o") or {}).get("fill")
                ink = {c.get("color") for c in n.get("kids") or [] if c["name"] == "reason"}
                if n["name"].startswith("header notice") and (fill != k.APP or ink != {k.TEXT_1}):
                    bad.append(f"{f['name']}: forced notice {fill} / {sorted(ink)}, not CanvasText on Canvas")
    return bad


def main() -> int:
    bad: list[str] = rebuild() if sys.argv[1:] == ["--rebuild"] else []
    total = {"boards": 0, "frames": 0, "shapes": 0}
    for nn, b in k.BOARDS.items():
        raw, packed = CAP / b.sheet, V4 / b.sheet
        r = subprocess.run([sys.executable, "-X", "utf8", "-I", str(k.VALIDATOR), str(raw), "--components",
                            str(k.COMPONENTS), "--tokens", str(k.TOKENS_FILE)],
                           capture_output=True, text=True, encoding="utf-8", check=False)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1]
        c = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(k.MKCALL), str(packed.resolve()),
                            "count"],
                           # compactOf.file is bare: run in build/
                           capture_output=True, text=True, encoding="utf-8", cwd=CAP, check=False)
        sh = json.loads(raw.read_text(encoding="utf-8"))
        pk = json.loads(packed.read_text(encoding="utf-8"))
        if r.returncode or c.returncode or c.stdout.strip() != str(len(pk["sections"])):
            bad.append(f"{b.sheet}: validator {r.returncode} / mkcall4 {c.returncode} {c.stdout.strip()}")
        if pk["compactOf"] != {"file": raw.name, "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}:
            bad.append(f"{b.sheet}: compactOf.file")
        t = tree(sh)
        nodes = list(walk(t))
        total["boards"] += 1
        total["shapes"] += len(nodes) - 1
        want = [k.frame_name(f, nn) for f in k.FRAME_PLAN[nn]]
        frames = [n for n in t["kids"] if n["name"] in want]
        total["frames"] += len(frames)
        bad.extend(f"{b.sheet}: {x}" for x in t2_findings(frames))
        caps = [n for n in t["kids"] if n["name"].startswith("caption ") and n["chars"].startswith("state: ")]
        if len(caps) != len(frames) or [f["name"] for f in frames] != want:
            bad.append(f"{b.sheet}: {len(frames)} frames, {len(caps)} captions, plan {len(want)}")
        cap_text = {c["chars"] for c in caps}
        for f in k.FRAME_PLAN[nn]:
            if f"state: {k.frame_label(f, nn)}" not in cap_text:
                bad.append(f"{b.sheet}: no caption for {f!r}")
        md_lines = (CAP / (Path(b.sheet).stem + ".md")).read_text(encoding="utf-8").split("\n")
        if md_lines[2] != k.md_line3(nn):
            bad.append(f"{b.sheet}: md line 3 {md_lines[2]!r}")
        if "/" in t["name"].split(f"{k.KEY} / {nn:02d} ", 1)[1]:
            bad.append(f"{b.sheet}: '/' in the root name")
        if k.DOCS["spec"][1][:8] not in " ".join(sh["notes"]["sources"]):
            bad.append(f"{b.sheet}: spec md5 pin missing")
        if k._scan_banned(sh):
            bad.append(f"{b.sheet}: banned {k._scan_banned(sh)}")
        for p, n in nodes[1:]:
            o = n.get("o") or {}
            if n["t"] not in ("board", "text", "rect", "ellipse", "icon"):
                bad.append(f"{p}: type {n['t']}")
            if "/" in n["name"]:
                bad.append(f"{p}: '/' in name")
            if n["t"] == "text" and "`" in n["chars"]:
                bad.append(f"{p}: backtick in drawn text")
            for tk in [n.get("color")] + list(o.values()):
                if isinstance(tk, str) and (tk in k.NEVER or tk.startswith("palette.")):
                    bad.append(f"{p}: token {tk}")
            if n["t"] == "icon" and n["icon"] not in k.ICONS_OK:
                bad.append(f"{p}: icon {n['icon']}")
            if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
                bad.append(f"{p}: wrap {o['wrap']!r}")
            if n["t"] == "board" and n.get("w") and o.get("dir") == "row" and o.get("wrap") != "wrap":
                kids = [x for x in n.get("kids") or [] if not x.get("abs")]
                pad = 2 * k._px(o.get("pad")) + 2 * k._px(o.get("padX"))
                need = pad + sum(k.est_width(x) for x in kids) + k._px(o.get("gap")) * max(len(kids) - 1, 0)
                if need > n["w"] + 1:
                    bad.append(f"{p}: row content {need:.0f} > w {n['w']}")
            if n["t"] == "board" and n.get("h") and o.get("dir") == "column":
                kids = [x for x in n.get("kids") or [] if not x.get("abs")]
                pad = 2 * k._px(o.get("pad")) + 2 * k._px(o.get("padY"))
                need = pad + sum(k.est_height(x) for x in kids) + k._px(o.get("gap")) * max(len(kids) - 1, 0)
                if need > n["h"] + 1:
                    bad.append(f"{p}: column content {need:.0f} > h {n['h']}")
            if n["t"] == "board" and not o.get("dir") and n.get("kids"):
                boxes = [(x["name"], x.get("x", 0), x.get("y", 0), k.est_width(x), k.est_height(x))
                         for x in n["kids"] if x["t"] in ("text", "board") and not x["name"].startswith("tick label")
                         and not OVERLAY.match(x["name"])]
                for i, a in enumerate(boxes):
                    for c2 in boxes[i + 1:]:
                        if (a[1] < c2[1] + c2[3] - 1 and c2[1] < a[1] + a[3] - 1 and a[2] < c2[2] + c2[4] - 1
                                and c2[2] < a[2] + a[4] - 1) and p != t["name"]:
                            bad.append(f"{p}: {a[0]!r} overlaps {c2[0]!r}")
            if re.search(r"/(header row|row[^/]*)/[^/]+$", p) and n["t"] == "board" and "padX" in o:
                if o["padX"] != k.INSET_SM:
                    bad.append(f"{p}: cell padX {o['padX']}")
                inner = n["w"] - 16
                for x in n.get("kids") or []:
                    if x["t"] == "text" and not x.get("w") and k.est_width(x) > inner + 0.5:
                        bad.append(f"{p}: text {k.est_width(x):.0f} px > cell inner {inner}")
        icons = {n["icon"] for _p, n in nodes if n["t"] == "icon"}
        if not icons <= k.ICONS_OK:
            bad.append(f"{b.sheet}: icons {sorted(icons - k.ICONS_OK)}")
        total["sections"] = total.get("sections", 0) + len(pk["sections"])
        print(f"{b.sheet}: {tail} | mkcall4 count {c.stdout.strip()} rc {c.returncode} | frames {len(frames)} | "
              f"shapes {len(nodes) - 1} | packed sections {len(pk['sections'])}")
    print(json.dumps(total))
    for x in bad[:60]:
        print("BAD", x)
    print(f"{'OK' if not bad else 'FAILED'}: {len(bad)} findings")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
