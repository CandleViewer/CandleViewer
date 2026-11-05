"""Build every board twice and check the set (python3 -X utf8 -I -B check_all.py; CV_CHECKOUT names the checkout
unless the kit sits in one). Gates: the kit self-test; every generator exits 0 (validator exit 0 inside); the rebuild is
byte-identical (raw sheets, .md, packed); per board: 0 inst nodes, only the local icons, no boolean wrap, no banned
string (raw, .md, packed), no backtick in drawn text, table cells padded 8 px a side (>= 16 px between texts), a "state: <id>"
caption per frame, no "/" in the root name after the prefix, md line 3 (and the light-twin line on 01, 05, 09), the
packed sheet's compactOf = the raw sheet's bare name and sha256, mkcall4 count = its sections, no never-token bound
(color.text.disabled, opacity.disabled), the data statement under the frames; the set: the source md5 pins, ≤ 10 boards
with twins ≤ ⅓, §10's every state drawn on its §0 board, the T2 renderings (the 500 option on 02, Save on 08: the
CMP-019 lock, color.surface.raised + color.border.default, the reason or notice in the frame), DEMO and LIVE badges as
separate frames on 05."""
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
import e21d03kit as k  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # -X utf8: the children read and write UTF-8 on every platform (a cp1252 Windows host included)
    return subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=900, cwd=cwd, check=False)


def digest() -> dict[str, str]:
    out = {}
    for d in (k.CAP_DIR, k.V4_DIR, KIT):
        for p in sorted(d.glob("[0-9][0-9]-*")):
            if p.suffix in (".json", ".md"):
                out[f"{d.name}/{p.name}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def build_all() -> None:
    for nn in sorted(k.BOARDS):
        r = run([str(KIT / "gen" / f"gen_{nn:02d}.py")])
        check(r.returncode == 0, f"gen_{nn:02d}: {(r.stdout + r.stderr).strip().splitlines()[-1][:160]}")


def frame_nodes(raw: dict, fid: str) -> list[dict]:
    fn = k.frame_name(fid)
    out = []
    for s in raw["sections"]:
        for p, n in k.walk(s["node"], s["into"]):
            if p.split("/")[0] == fn or p.startswith(fn + "/"):
                out.append(n)
    return out


def scan(nn: int) -> None:
    b = k.BOARDS[nn]
    raw_p, md_p, pk_p = k.CAP_DIR / b.sheet, k.CAP_DIR / (b.sheet[:-5] + ".md"), k.V4_DIR / b.sheet
    raw = json.loads(raw_p.read_text(encoding="utf-8"))
    pk = json.loads(pk_p.read_text(encoding="utf-8"))
    nodes = [n for s in raw["sections"] for _p, n in k.walk(s["node"])]
    pnodes = json.dumps(pk["sections"], ensure_ascii=False)
    check(not any(n["t"] == "inst" for n in nodes) and '"t":"inst"' not in pnodes.replace(" ", ""),
          f"{nn:02d}: 0 inst nodes ({len(nodes)} shapes, {len(raw['sections'])} raw / {len(pk['sections'])} packed "
          f"sections)")
    bad_icons = sorted({n["icon"] for n in nodes if n["t"] == "icon"} - k.ICONS_OK)
    check(not bad_icons, f"{nn:02d}: icons in the local set {bad_icons}")
    check(all((n.get("o") or {}).get("wrap", "nowrap") in ("wrap", "nowrap") for n in nodes), f"{nn:02d}: no boolean wrap")
    banned = k._scan_banned(raw) + k._scan_banned(pk)
    banned += sorted({m.group(0) for m in k.BANNED.finditer(md_p.read_text(encoding="utf-8"))})
    check(not banned, f"{nn:02d}: no forbidden strings {banned}")
    ticks = [n["name"] for n in nodes if n["t"] == "text" and "`" in n["chars"]]
    check(not ticks, f"{nn:02d}: no backtick in drawn text {ticks[:5]}")  # a cite mark is markdown, never copy
    cells = [(p, n) for s in raw["sections"] for p, n in k.walk(s["node"], s["into"])
             if n["t"] == "board" and re.search(r"/(header row|row · \d+)/[^/]+$", p, re.DOTALL)]
    check(all((n.get("o") or {}).get("padX") == k.INSET_SM for _p, n in cells),
          f"{nn:02d}: {len(cells)} table cells, 8 px a side (>= 16 px between texts)")
    caps = {n["chars"] for n in nodes if n["t"] == "text" and n["name"].startswith("caption ")}
    check(all(f"state: {f}" in caps for f in b.frames), f"{nn:02d}: a caption on each of {len(b.frames)} frames")
    check("/" not in raw["board"]["name"].split(f"{k.KEY} / {nn:02d} ", 1)[1], f"{nn:02d}: no '/' after the prefix")
    md = md_p.read_text(encoding="utf-8").split("\n")
    check(md[2] == k.md_line3(nn) and (not b.twin or any(b.export_light in ln for ln in md[:8])),
          f"{nn:02d}: md line 3{' and the light-twin export line' if b.twin else ''}")
    check(pk["compactOf"] == {"file": raw_p.name, "sha256": hashlib.sha256(raw_p.read_bytes()).hexdigest()},
          f"{nn:02d}: packed compactOf = the raw sheet's bare name + sha256")
    c = run([str(k.MKCALL), str(pk_p.resolve()), "count"], cwd=k.CAP_DIR)  # compactOf.file is bare: run in build/
    check(c.returncode == 0 and c.stdout.strip() == str(len(pk["sections"])), f"{nn:02d}: mkcall4 count "
          f"{c.stdout.strip()} = {len(pk['sections'])} sections")
    bound = {v for n in nodes for v in [*(n.get("o") or {}).values(), n.get("color"), n.get("typo"), n.get("size")]
             if isinstance(v, str)}
    check(not bound & set(k.NEVER), f"{nn:02d}: never-tokens bound nowhere ({len(bound)} tokens bound)")
    check(any(n["name"] == "footer · data statement" and n["chars"].startswith("Data: synthetic only") for n in nodes),
          f"{nn:02d}: synthetic data declared")
    v = k.validate(raw_p)
    check(v[0] == 0, f"{nn:02d}: {v[1].splitlines()[-1]}")


def t2_checks() -> None:
    raw2 = json.loads((k.CAP_DIR / k.BOARDS[2].sheet).read_text(encoding="utf-8"))
    raw8 = json.loads((k.CAP_DIR / k.BOARDS[8].sheet).read_text(encoding="utf-8"))
    for raw, fid, nm, words in ((raw2, "SCR-051/500-unavailable", "CMP-006 option 500 · T2 2a", k.W("W-3")),
                                (raw8, "SCR-051/save-gated", "CMP-001 Save · T2 2a",
                                 k.W("W-32", user=k.VIEW_AS_USER))):
        ns = frame_nodes(raw, fid)
        t2 = [n for n in ns if n["name"] == nm]
        ok = bool(t2) and (t2[0]["o"].get("fill"), t2[0]["o"].get("stroke")) == (k.RAISED, k.BORDER) and any(
            x["t"] == "icon" and x["icon"] == "locked" for _p, x in k.walk(t2[0])) and any(
            n["t"] == "text" and n["chars"] == words for n in ns)
        check(ok, f"{fid}: T2 2a — the lock, color.surface.raised + color.border.default, the reason / notice drawn")


def main() -> int:
    r = run([str(KIT / "e21d03kit.py"), "selftest"])
    check(r.returncode == 0, f"kit self-test: {r.stdout.strip().splitlines()[-1]}")
    check(all(k.spec_md5_ok().values()), "spec / fixture md5 pins: " +
          ", ".join(f"{x} {m[:8]}" for x, (_p, m) in k.DOCS.items()))
    check(len(k.BOARDS) <= 10 and 3 * sum(b.twin for b in k.BOARDS.values()) <= len(k.BOARDS),
          f"{len(k.BOARDS)} boards, {sum(b.twin for b in k.BOARDS.values())} light twins (≤ ⅓)")
    check(all(k.board_of(fid) == int(k.plain(c[7])) for fid, (c, _i) in k.STATES.items()),
          f"§10: all {len(k.STATES)} states drawn on their §0 boards")
    build_all()
    first = digest()
    build_all()
    second = digest()
    diff = sorted(x for x in set(first) | set(second) if first.get(x) != second.get(x))
    check(not diff and len(first) == 4 * len(k.BOARDS), f"rebuild byte-identical ({len(first)} files; differing {diff[:4]})")
    for nn in sorted(k.BOARDS):
        scan(nn)
    t2_checks()
    raw5 = json.loads((k.CAP_DIR / k.BOARDS[5].sheet).read_text(encoding="utf-8"))
    envs = {fid: {n["name"] for n in frame_nodes(raw5, fid) if n["name"].startswith("env badge")}
            for fid in k.BOARDS[5].frames}
    check(envs == {"SCR-051/trading-demo": {"env badge · DEMO"}, "SCR-051/trading-live": {"env badge · LIVE"},
                   "SCR-051/live-confirm-off": {"env badge · LIVE"}},
          f"05: DEMO and LIVE separate frames, the badge from the session ({envs})")
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failures")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
