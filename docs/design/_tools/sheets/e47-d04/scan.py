"""Scan the E47-D04 sheets: python3 -I -B scan.py  (exit 0 when every check passes).

Raw sheets (build/NN-*.json): no inst node; icons only from the local set; o.wrap only "wrap"/"nowrap";
no banned string (local paths, hosts, agent names); every frame has its "state: <id>" caption; no "/" in a node
name below the root; table cells padded 8 px a side (adjacent cell texts >= 16 px apart); every frame 1280 x 800;
the root hugs the frames + ONE 400 px annotation column + 80. Packed sheets (v4/): compactOf.file is the raw
sheet's bare name and its sha256 matches. The spec md5 pin holds (the kit refuses to import otherwise).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e47d04kit as k  # noqa: E402


def walk(n: dict, path: str = ""):
    p = f"{path}/{n.get('name')}"
    yield p, n
    for c in n.get("kids") or []:
        yield from walk(c, p)


def main() -> int:
    bad: list[str] = []
    sheets = sorted(k.CAP_DIR.glob("[0-9][0-9]-*.json"))
    if len(sheets) != 10:
        bad.append(f"{len(sheets)} raw sheets, expected 10")
    totals = {"frames": 0, "shapes": 0}
    for sp in sheets:
        sh = json.loads(sp.read_text(encoding="utf-8"))
        nn = int(sp.name[:2])
        b = k.BOARDS[nn]
        if sh["board"]["name"] != b.name or "/" in sh["board"]["name"][len("E47-D04 / "):]:
            bad.append(f"{sp.name}: root name {sh['board']['name']!r}")
        if k.BANNED.search(json.dumps(sh, ensure_ascii=False)):
            bad.append(f"{sp.name}: banned string")
        tops = [s["node"] for s in sh["sections"] if s["into"] == ""]
        frames = [t for t in tops if t["name"] in {k.frame_name(f) for f in k.frames_of(nn)}]
        caps = {t["chars"] for t in tops if t["t"] == "text" and t["name"].startswith("caption")}
        anns = [t for t in tops if t["name"] == "annotations"]
        totals["frames"] += len(frames)
        if len(frames) != len(k.frames_of(nn)):
            bad.append(f"{sp.name}: {len(frames)} frames vs §H {len(k.frames_of(nn))}")
        for f in frames:
            if (f["w"], f["h"]) != (1280, 800):
                bad.append(f"{sp.name}: {f['name']} is {f['w']} x {f['h']}")
            if f"state: {f['name'].split(' · ')[0]}" not in caps:
                bad.append(f"{sp.name}: no caption for {f['name']}")
        if len(anns) != 1 or anns[0]["w"] != 400:
            bad.append(f"{sp.name}: annotation columns {[a.get('w') for a in anns]}")
        right = max(f["x"] + f["w"] for f in frames)
        if sh["board"]["w"] != right + 80 + 400 + 80:
            bad.append(f"{sp.name}: root w {sh['board']['w']} != frames {right} + 80 + 400 + 80")
        for s in sh["sections"]:
            for p, n in walk(s["node"], s["into"]):
                totals["shapes"] += 1
                if n["t"] == "inst":
                    bad.append(f"{sp.name}: inst {p}")
                if n["t"] == "icon" and n.get("icon") not in k.ICONS_OK:
                    bad.append(f"{sp.name}: icon {n.get('icon')} {p}")
                o = n.get("o") or {}
                if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
                    bad.append(f"{sp.name}: wrap {o['wrap']!r} {p}")
                if "/" in n.get("name", ""):
                    bad.append(f"{sp.name}: '/' in {n.get('name')!r}")
                if p.split("/")[-2:-1] and (p.split("/")[-2].startswith("row ") or p.split("/")[-2] == "header row") \
                        and n["t"] == "board" and not n["name"].startswith("CMP-039") and o.get("padX") != k.INSET_SM:
                    bad.append(f"{sp.name}: cell padX {o.get('padX')} at {p}")
        pk = k.V4_DIR / sp.name
        if not pk.exists():
            bad.append(f"{pk.name}: no packed sheet")
        else:
            cf = json.loads(pk.read_text(encoding="utf-8")).get("compactOf") or {}
            if cf.get("file") != sp.name or cf.get("sha256") != hashlib.sha256(
                    sp.read_bytes()).hexdigest():
                bad.append(f"{pk.name}: compactOf {cf}")
    print(f"sheets {len(sheets)}, frames {totals['frames']}, shapes {totals['shapes']}; md5 pin "
          f"{all(k.spec_md5_ok().values())}")
    for x in bad:
        print("FAIL", x)
    print("OK" if not bad else f"FAILED: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
