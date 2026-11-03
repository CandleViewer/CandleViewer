"""Build and scan the ten E47-D13 sheets: python3 -I -B check_all.py [--twice]   (exit 0 when every check passes).

Runs the kit self-test and every gen/gen_NN.py (each writes the raw sheet + .md to CAP_DIR, validated, and the packed
sheet to V4_DIR), then scans. Raw sheets: no inst node; icons only from the local set; o.wrap only "wrap"/"nowrap";
no banned string; no "/" in a node name (and none after the "<KEY> / NN " root prefix); every frame 1280 x 800 with
its "state: <id>" caption; table cells padded 8 px a side (adjacent cell texts >= 16 px apart); the root hugs the
frames + ONE 400 px annotation column + 80; validator exit 0. Packed sheets: compactOf = the raw sheet's bare name +
sha256; mkcall4 count (run in CAP_DIR, where the bare name resolves) exits 0 and equals the section count. The .md line 3 is the render drivers' line. The spec md5 pin holds. --twice builds a
second time and requires byte-identical outputs.
"""
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
import e47d13kit as k  # noqa: E402


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-B", *args], capture_output=True, text=True, timeout=900, check=False)


def build() -> list[str]:
    bad = []
    r = run([str(KIT / "e47d13kit.py"), "selftest"])
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
    if r.returncode:
        bad.append("selftest: " + (r.stdout + r.stderr)[-400:])
    for nn in sorted(k.BOARDS):
        r = run([str(KIT / "gen" / f"gen_{nn:02d}.py")])
        print((r.stdout or r.stderr).strip().splitlines()[-1])
        if r.returncode:
            bad.append(f"gen_{nn:02d}: " + r.stderr[-600:])
    return bad


def digest() -> dict[str, str]:
    out = {}
    for d in (k.CAP_DIR, k.V4_DIR):
        for p in sorted(d.glob("[0-9][0-9]-*")):
            out[str(p.relative_to(d.parent))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def walk(n: dict, path: str = ""):
    p = f"{path}/{n.get('name')}"
    yield p, n
    for c in n.get("kids") or []:
        yield from walk(c, p)


def scan() -> tuple[list[str], list[str]]:
    bad, rows = [], []
    for nn, b in sorted(k.BOARDS.items()):
        sp, pk, md = k.CAP_DIR / b.sheet, k.V4_DIR / b.sheet, k.CAP_DIR / (b.sheet[:-5] + ".md")
        if not sp.exists() or not pk.exists() or not md.exists():
            bad.append(f"{b.sheet}: missing raw / packed / md")
            continue
        sh = json.loads(sp.read_text(encoding="utf-8"))
        name = sh["board"]["name"]
        if name != b.name or "/" in name[len(f"{k.KEY} / NN "):]:
            bad.append(f"{sp.name}: root name {name!r}")
        if k.BANNED.search(json.dumps(sh, ensure_ascii=False)) or k.BANNED.search(md.read_text(encoding="utf-8")):
            bad.append(f"{sp.name}: banned string")
        tops = [s["node"] for s in sh["sections"] if s["into"] == ""]
        want = {k.frame_name(f) for f in k.frames_of(nn)}
        frames = [t for t in tops if t["name"] in want]
        caps = {t["chars"] for t in tops if t["t"] == "text" and t["name"].startswith("caption")}
        anns = [t for t in tops if t["name"] == "annotations"]
        if len(frames) != len(want):
            bad.append(f"{sp.name}: {len(frames)} frames vs {len(want)}")
        for f in frames:
            if (f["w"], f["h"]) != (k.FRAME_W, k.FRAME_H):
                bad.append(f"{sp.name}: {f['name']} is {f['w']} x {f['h']}")
            if f"state: {f['name'].split(' · ')[0]}" not in caps:
                bad.append(f"{sp.name}: no caption for {f['name']}")
        if len(anns) != 1 or anns[0]["w"] != k.ANN_W:
            bad.append(f"{sp.name}: annotation columns {[a.get('w') for a in anns]}")
        right = max(f["x"] + f["w"] for f in frames)
        if sh["board"]["w"] != right + k.MARGIN + k.ANN_W + k.MARGIN:
            bad.append(f"{sp.name}: root w {sh['board']['w']} != frames {right} + 80 + 400 + 80")
        shapes = 0
        for s in sh["sections"]:
            for p, n in walk(s["node"], s["into"]):
                shapes += 1
                o = n.get("o") or {}
                if n["t"] == "inst":
                    bad.append(f"{sp.name}: inst {p}")
                if n["t"] == "icon" and n.get("icon") not in k.ICONS_OK:
                    bad.append(f"{sp.name}: icon {n.get('icon')} {p}")
                if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
                    bad.append(f"{sp.name}: wrap {o['wrap']!r} {p}")
                if "/" in n.get("name", ""):
                    bad.append(f"{sp.name}: '/' in {n.get('name')!r}")
                parent = p.split("/")[-2] if p.count("/") >= 2 else ""
                if (re.match(r"(row \d+ · |header row$)", parent) and n["t"] == "board"
                        and not n["name"].startswith("CMP-039") and o.get("padX") != k.INSET_SM):
                    bad.append(f"{sp.name}: cell padX {o.get('padX')} at {p}")
        rc, msg = k.validate(sp)
        if rc:
            bad.append(f"{sp.name}: validator exit {rc}")
        cf = json.loads(pk.read_text(encoding="utf-8")).get("compactOf") or {}
        if cf != {"file": sp.name, "sha256": hashlib.sha256(sp.read_bytes()).hexdigest()}:
            bad.append(f"{pk.name}: compactOf {cf}")
        c = subprocess.run([sys.executable, "-I", "-B", str(k.MKCALL), str(pk), "count"], capture_output=True,
                           text=True, timeout=120, check=False, cwd=k.CAP_DIR)  # compactOf.file is the bare name
        if c.stdout.strip() != str(len(json.loads(pk.read_text(encoding="utf-8"))["sections"])):
            bad.append(f"{pk.name}: mkcall4 count {c.stdout.strip()!r} != its sections")
        if c.returncode:
            bad.append(f"{pk.name}: mkcall4 count exit {c.returncode}")
        l3 = md.read_text(encoding="utf-8").split("\n")[2]
        if l3 != k.md_line3(nn):
            bad.append(f"{md.name}: line 3 {l3!r}")
        rows.append(f"{b.sheet[:-5]}: {len(frames)} frames, {shapes} shapes, {len(sh['sections'])} sections, "
                    f"root {sh['board']['w']} x {sh['board']['h']}; packed count {c.stdout.strip()}; "
                    f"validator: {msg.splitlines()[-1] if msg else ''}")
    if not all(k.spec_md5_ok().values()):
        bad.append(f"md5 pin {k.spec_md5_ok()}")
    return bad, rows


def main() -> int:
    bad = build()
    first = digest()
    if "--twice" in sys.argv[1:]:
        bad += build()
        second = digest()
        diff = sorted(p for p in set(first) | set(second) if first.get(p) != second.get(p))
        print(f"rebuild byte-identical: {not diff} ({len(first)} files)")
        if diff:
            bad.append(f"rebuild differs: {diff[:6]}")
    sbad, rows = scan()
    bad += sbad
    for r in rows:
        print(r)
    print(f"md5 pin {all(k.spec_md5_ok().values())} ({', '.join(sorted(k.AT_BASE))} at {k.SPEC_BASE})")
    for x in bad:
        print("FAIL", x)
    print("OK" if not bad else f"FAILED: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
