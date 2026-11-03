"""Build every board twice and check the set (python3 -I -B check_all.py; CV_CHECKOUT names the checkout unless the
kit sits in one). Gates: the kit self-test; every generator exits 0 (validator exit 0 inside); the rebuild is
byte-identical (raw sheets, .md, packed); per board: 0 inst nodes, only the local icons, no boolean wrap, no banned
string (raw, .md, packed outside compactOf), table cells padded 8 px a side (>= 16 px between texts), a "state: <id>"
caption per frame, no "/" in the root name after the prefix, md line 3, the packed sheet's source sha256 = the raw
sheet's and mkcall4 count = its sections, frames 1280 x 800, the root = frames + 80 + 400 + 80; the source md5
pins."""
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
import e47d09kit as k  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", "-B", *args], capture_output=True, text=True, timeout=900,
                          check=False)


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
        check(r.returncode == 0, f"gen_{nn:02d}: {(r.stdout + r.stderr).strip().splitlines()[-1][:160]}")


def scan(nn: int) -> None:
    b = k.BOARDS[nn]
    b_frames = k.frames_of(nn)
    raw_p, md_p, pk_p = k.CAP_DIR / b.sheet, k.CAP_DIR / (b.sheet[:-5] + ".md"), k.V4_DIR / b.sheet
    raw = json.loads(raw_p.read_text(encoding="utf-8"))
    pk = json.loads(pk_p.read_text(encoding="utf-8"))
    nodes = [n for s in raw["sections"] for _p, n in k.walk(s["node"])]
    pnodes = json.dumps(pk["sections"], ensure_ascii=False)
    check(not any(n["t"] == "inst" for n in nodes) and '"t":"inst"' not in pnodes.replace(" ", ""),
          f"{nn:02d}: 0 inst nodes ({len(nodes)} shapes)")
    bad_icons = sorted({n["icon"] for n in nodes if n["t"] == "icon"} - k.ICONS_OK)
    check(not bad_icons, f"{nn:02d}: icons in the local set {bad_icons}")
    check(all((n.get("o") or {}).get("wrap", "nowrap") in ("wrap", "nowrap") for n in nodes), f"{nn:02d}: no boolean wrap")
    banned = k._scan_banned(raw) + k._scan_banned({x: y for x, y in pk.items() if x != "compactOf"})
    banned += sorted({m.group(0) for m in k.BANNED.finditer(md_p.read_text(encoding="utf-8"))})
    check(not banned, f"{nn:02d}: no forbidden strings {banned}")
    cells = [(p, n) for s in raw["sections"] for p, n in k.walk(s["node"], s["into"])
             if n["t"] == "board" and re.search(r"/(header row|row [^/]*)/(?!CMP-039 ring)[^/]+$", p, re.DOTALL)]
    check(all((n.get("o") or {}).get("padX") == k.INSET_SM for _p, n in cells),
          f"{nn:02d}: {len(cells)} table cells, 8 px a side (>= 16 px between texts)")
    caps = {n["chars"] for n in nodes if n["t"] == "text" and n["name"].startswith("caption ")}
    check(all(f"state: {k.frame_id(f)}" in caps for f in b_frames), f"{nn:02d}: a caption on each of {len(b_frames)} frames")
    check("/" not in raw["board"]["name"].split(f"{k.KEY} / {nn:02d} ", 1)[1], f"{nn:02d}: no '/' after the prefix")
    l3 = md_p.read_text(encoding="utf-8").split("\n")[2]
    check(l3 == k.md_line3(nn), f"{nn:02d}: md line 3")
    src = raw_p.name if k.IN_REPO else str(raw_p.resolve())  # in a checkout the committed v4/ keeps the bare name
    check(pk["compactOf"] == {"file": src, "sha256": hashlib.sha256(raw_p.read_bytes()).hexdigest()},
          f"{nn:02d}: packed source sha256 = raw")
    count_p = pk_p
    if k.IN_REPO:  # mkcall4 reads the pack source by compactOf.file: count a copy naming the raw sheet's full path
        count_p = k.CAP_DIR / f".count-{pk_p.name}"
        count_p.write_text(json.dumps(dict(pk, compactOf=dict(pk["compactOf"], file=str(raw_p.resolve()))),
                                      ensure_ascii=False), encoding="utf-8")
    c = run([str(k.MKCALL), str(count_p), "count"])
    if count_p != pk_p:
        count_p.unlink()
    check(c.returncode == 0 and c.stdout.strip() == str(len(pk["sections"])), f"{nn:02d}: mkcall4 count "
          f"{c.stdout.strip()} = {len(pk['sections'])} sections")
    frames = [s["node"] for s in raw["sections"] if s["into"] == "" and s["node"]["name"] in
              {k.frame_name(f) for f in b_frames}]
    check(len(frames) == len(b_frames) and all(f["w"] == k.FRAME_W and f["h"] == k.FRAME_H for f in frames),
          f"{nn:02d}: {len(frames)} frames, each 1280 x 800")
    right = max(f["x"] + f["w"] for f in frames)
    check(raw["board"]["w"] == right + k.MARGIN + k.ANN_W + k.MARGIN, f"{nn:02d}: root w {raw['board']['w']} = "
          "frames + 80 + 400 + 80")
    v = k.validate(raw_p)
    check(v[0] == 0, f"{nn:02d}: {v[1].splitlines()[-1]}")


def main() -> int:
    r = run([str(KIT / "e47d09kit.py"), "selftest"])
    check(r.returncode == 0, f"kit self-test: {r.stdout.strip().splitlines()[-1]}")
    check(all(k.spec_md5_ok().values()), "spec / hand-off / keymap / reserved / fixture md5 pins: " +
          ", ".join(f"{x} {m[:8]}" for x, (_p, m) in k.DOCS.items()))
    build_all()
    first = digest()
    build_all()
    second = digest()
    diff = sorted(x for x in set(first) | set(second) if first.get(x) != second.get(x))
    check(not diff and len(first) == 30, f"rebuild byte-identical ({len(first)} files; differing {diff[:4]})")
    for nn in sorted(k.BOARDS):
        scan(nn)
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failures")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
