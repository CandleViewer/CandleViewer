"""Scan the ten E19-D05 sheets (raw in the cap folder, packed in the v4 folder): validator (with the shared components
list and the default token-sync.json), mkcall4 count, packed sha256 = raw sheet's, no inst, local icons only, no boolean wrap,
no '/' in node names, no banned string, a "state:" caption per frame, table cells padded 8 px a side with their text
inside (>= 16 px between texts), row / column overflow and sibling text overlap by the kit's estimates, the spec md5
pin. Run: python3 -I -B check_all.py"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e19d05kit as k  # noqa: E402

CAP, V4 = k.CAP_DIR, k.V4_DIR
# drawn on top by design (board markers, rails, rays, leaders, the ring, hatch, the tooltip, the scrim, the dialog,
# a menu, pins): excluded from the sibling-overlap estimate
OVERLAY = re.compile(r"^(board marker|POC rail|nPOC ray|tested ray|VA bracket|bracket emphasis|POC trace band|"
                     r"header strip|plot|legend strip|busy bar|CMP-078|bar |VAH tick|VAL tick|region|axis|"
                     r"second tick|band start|cut |event \d+$|spoken|wick|body|overlay|strip \d+ cell \d+ · )",
                     re.DOTALL)


GROUP = re.compile(r"^group \d{2}$", re.DOTALL)  # the kit's section groups (k.chunk): positions unchanged


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


def main() -> int:
    bad: list[str] = []
    total = {"boards": 0, "frames": 0, "shapes": 0, "sections": 0}
    for nn, b in k.BOARDS.items():
        raw, packed = CAP / b.sheet, V4 / b.sheet
        r = subprocess.run([sys.executable, "-X", "utf8", "-I", str(k.VALIDATOR), str(raw), "--components", str(k.COMPONENTS)],
                           capture_output=True, text=True, encoding="utf-8", check=False)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1]
        c = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(k.MKCALL), str(packed.resolve()), "count"],
                           capture_output=True, text=True, encoding="utf-8", cwd=CAP, check=False)
        sh = json.loads(raw.read_text(encoding="utf-8"))
        pk = json.loads(packed.read_text(encoding="utf-8"))
        if r.returncode or c.returncode or c.stdout.strip() != str(len(pk["sections"])):
            bad.append(f"{b.sheet}: validator {r.returncode} / mkcall4 {c.returncode} {c.stdout.strip()}")
        if pk["compactOf"] != {"file": raw.name, "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}:
            bad.append(f"{b.sheet}: compactOf is not the raw sheet's bare name and sha256")
        t = tree(sh)
        nodes = list(walk(t))
        total["boards"] += 1
        total["shapes"] += len(nodes) - 1
        names = {k.frame_name(f) for f in b.frames}
        frames = [n for n in t["kids"] if n["name"] in names]
        total["frames"] += len(frames)
        caps = [n for n in t["kids"] if n["name"].startswith("caption ") and n["chars"].startswith("state: ")]
        if len(caps) != len(frames) or len(frames) != len(b.frames):
            bad.append(f"{b.sheet}: {len(frames)} frames, {len(caps)} captions, §0 plan {len(b.frames)}")
        if "/" in t["name"].split(f"{k.KEY} / {nn:02d} ", 1)[1]:
            bad.append(f"{b.sheet}: '/' in the root name")
        if k.DOCS["spec"][1][:8] not in " ".join(sh["notes"]["sources"]):
            bad.append(f"{b.sheet}: spec md5 pin missing")
        if k._scan_banned(sh) or k._scan_banned(pk):
            bad.append(f"{b.sheet}: banned {k._scan_banned(sh) + k._scan_banned(pk)}")
        md_text = (CAP / (raw.stem + ".md")).read_text(encoding="utf-8")
        md = md_text.split("\n")
        if md[2] != k.md_line3(nn):
            bad.append(f"{b.sheet}: md line 3 {md[2]!r}")
        side = k.KIT_DIR / (raw.stem + ".md")
        if k.IN_REPO and (not side.is_file() or side.read_text(encoding="utf-8") != md_text):
            bad.append(f"{b.sheet}: the .md beside the kit differs from the build copy")
        for p, n in nodes[1:]:
            o = n.get("o") or {}
            if n["t"] not in ("board", "text", "rect", "ellipse", "icon"):
                bad.append(f"{p}: type {n['t']}")
            if "/" in n["name"]:
                bad.append(f"{p}: '/' in name")
            if "`" in n.get("chars", "") or "`" in n["name"]:
                bad.append(f"{p}: a backtick in a drawn string")
            if n["t"] == "icon" and n["icon"] not in k.ICONS_OK:
                bad.append(f"{p}: icon {n['icon']}")
            if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
                bad.append(f"{p}: wrap {o['wrap']!r}")
            if any(v in k.NEVER for v in [n.get("color"), *o.values()] if isinstance(v, str)):
                bad.append(f"{p}: a NEVER token")
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
            if (n["t"] == "board" and not o.get("dir") and n.get("kids") and p != t["name"]
                    and not GROUP.match(n["name"])):
                flat = [y for x in n["kids"] for y in (x.get("kids") or [] if GROUP.match(x["name"]) else [x])]
                boxes = [(x["name"], x.get("x", 0), x.get("y", 0), k.est_width(x), k.est_height(x))
                         for x in flat if x["t"] in ("text", "board") and not OVERLAY.match(x["name"])]
                for i, a in enumerate(boxes):
                    for c2 in boxes[i + 1:]:
                        if (a[1] < c2[1] + c2[3] - 1 and c2[1] < a[1] + a[3] - 1 and a[2] < c2[2] + c2[4] - 1
                                and c2[2] < a[2] + a[4] - 1):
                            bad.append(f"{p}: {a[0]!r} overlaps {c2[0]!r}")
            if re.search(r"/(header row|row ·[^/]*)/[^/]+$", p) and n["t"] == "board" and "padX" in o:
                if o["padX"] != k.INSET_SM:
                    bad.append(f"{p}: cell padX {o['padX']}")
                inner = n["w"] - 16
                for x in n.get("kids") or []:
                    if x["t"] == "text" and not x.get("w") and k.est_width(x) > inner + 0.5:
                        bad.append(f"{p}: text {k.est_width(x):.0f} px > cell inner {inner}")
        total["sections"] += len(pk["sections"])
        print(f"{b.sheet}: {tail} | mkcall4 count {c.stdout.strip()} rc {c.returncode} | frames {len(frames)} | "
              f"shapes {len(nodes) - 1} | packed sections {len(pk['sections'])}")
    print(json.dumps(total))
    for x in bad[:80]:
        print("BAD", x)
    print(f"{'OK' if not bad else 'FAILED'}: {len(bad)} findings")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
