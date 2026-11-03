"""Build every board twice and check the set (python3 -X utf8 -I -B check_all.py; CV_CHECKOUT names the checkout
unless the kit sits in one). Gates: the kit self-test; every generator exits 0 (validator exit 0 inside); the rebuild is
byte-identical (raw sheets, .md, packed); per board: 0 inst nodes, only the local icons, no boolean wrap, no banned
string (raw, .md, packed outside compactOf), table cells padded 8 px a side (>= 16 px between texts), a "state: <id>"
caption per frame, no "/" in the root name after the prefix, md line 3 (and the light-twin line on 01, 05, 07), the
packed sheet's source sha256 = the raw sheet's and mkcall4 count = its sections, no never-token bound
(color.text.disabled, opacity.disabled), the data statement under the frames; the set: the source md5 pins, <= 10 boards
with twins <= 1/3, §4's every state drawn on its §0 board, the T2 renderings (the 500 option on 02, the ARM pill on 07,
the footer's four trade buttons and the one notice on every panel frame: the CMP-019 lock, color.surface.raised +
color.border.default), DEMO and LIVE badges as separate frames on 07 with no own order under LIVE."""
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
import e21d02kit as k  # noqa: E402

FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        FAILS.append(what)


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", *args], capture_output=True, text=True, timeout=900,
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
    banned = k._scan_banned(raw) + k._scan_banned({x: y for x, y in pk.items() if x != "compactOf"})
    banned += sorted({m.group(0) for m in k.BANNED.finditer(md_p.read_text(encoding="utf-8"))})
    check(not banned, f"{nn:02d}: no forbidden strings {banned}")
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
          f"{nn:02d}: packed compactOf = the bare raw-sheet name + its sha256")
    tmp = k.CAP_DIR / (".count-" + raw_p.name)  # mkcall4 reads the pack source by compactOf.file
    tmp.write_text(json.dumps(dict(pk, compactOf=dict(pk["compactOf"], file=str(raw_p.resolve()))),
                              ensure_ascii=False), encoding="utf-8")
    c = run([str(k.MKCALL), str(tmp), "count"])
    tmp.unlink()
    check(c.returncode == 0 and c.stdout.strip() == str(len(pk["sections"])), f"{nn:02d}: mkcall4 count "
          f"{c.stdout.strip()} = {len(pk['sections'])} sections")
    bound = {v for n in nodes for v in [*(n.get("o") or {}).values(), n.get("color"), n.get("typo"), n.get("size")]
             if isinstance(v, str)}
    check(not bound & set(k.NEVER), f"{nn:02d}: never-tokens bound nowhere ({len(bound)} tokens bound)")
    check(any(n["name"] == "footer · data statement" and n["chars"].startswith("Data: synthetic only") for n in nodes),
          f"{nn:02d}: synthetic data declared")
    v = k.validate(raw_p)
    check(v[0] == 0, f"{nn:02d}: {v[1].splitlines()[-1]}")
    # the v1 validator reads raw sections only (a packed sheet's styles / s refs / clones fail it by design): expand the
    # packed sections with the packer's own functions and require them equal to the raw ones, so the raw verdict holds
    sys.path.insert(0, str(k.TOOLS))
    import compact  # noqa: E402
    exp = [(s["into"], compact.materialize(compact.expand_styles(s["node"], s.get("styles", {}))))
           for s in pk["sections"]]
    check(len(exp) == len(raw["sections"]) and all(i == s.get("into", "") and compact.same(n, s["node"])
                                                    for (i, n), s in zip(exp, raw["sections"]))
          and all(pk[x] == raw[x] for x in ("board", "export", "notes")),
          f"{nn:02d}: packed sections expand to the raw ones ({len(exp)}), so the raw validator verdict covers them")




def is_t2(n: dict) -> bool:
    return (n.get("o") or {}).get("fill") == k.RAISED and (n.get("o") or {}).get("stroke") == k.BORDER and any(
        x["t"] == "icon" and x["icon"] == "locked" for _p, x in k.walk(n))


def t2_checks() -> None:
    for nn, fid, nm, words in ((2, "SCR-050/500-unavailable", "option 500 · T2 2a", k.W("W-3")),
                               (7, "SCR-050/arm-locked", "CMP-229 ArmToggle · LOCKED · T2 2a", k.W("W-20"))):
        ns = frame_nodes(json.loads((k.CAP_DIR / k.BOARDS[nn].sheet).read_text(encoding="utf-8")), fid)
        t2 = [n for n in ns if n["name"] == nm]
        ok = bool(t2) and is_t2(t2[0]) and any(n["t"] == "text" and n["chars"] == words for n in ns)
        check(ok, f"{fid}: T2 2a — the lock, color.surface.raised + color.border.default, the reason drawn")
    n_frames = 0
    for nn, b in k.BOARDS.items():
        raw = json.loads((k.CAP_DIR / b.sheet).read_text(encoding="utf-8"))
        for fid in b.frames:
            if fid in k.MARKER_FRAMES:
                continue
            ns = frame_nodes(raw, fid)
            btn = [n for n in ns if n["name"].startswith("footer ") and n["name"].endswith(" · T2 2a")]
            nt = [n for n in ns if n["name"] == "header notice (G-T2.5)"]
            ok = len(btn) == 4 and all(is_t2(n) for n in btn) and len(nt) == 1 and any(
                x["t"] == "icon" and x["icon"] == "locked" for _p, x in k.walk(nt[0]))
            check(ok, f"{nn:02d} {fid}: BUY MKT, SELL MKT, FLAT, CXL T2 2a and the one notice")
            n_frames += ok
    check(n_frames > 0, f"T2 footer and notice on {n_frames} panel frames")


def texts(nn: int) -> list[str]:
    raw = json.loads((k.CAP_DIR / k.BOARDS[nn].sheet).read_text(encoding="utf-8"))
    return [n["chars"] for s in raw["sections"] for _p, n in k.walk(s["node"]) if n["t"] == "text"]


def verbatim_checks() -> None:
    """The check's findings: W-5 / W-6 / W-24 drawn as the spec writes them (digits included), W-26 kept, no split
    "(estimated)" chip beside W-24, the ARMED inset named for its owner."""
    def q(wid: str) -> str:
        return re.findall(r'"([^"]+)"', k.COPY[wid][0][2])[0]
    t5, t8 = texts(5), texts(8)
    for wid in ("W-5", "W-6", "W-26"):
        check(q(wid) in t5, f"05: {wid} drawn verbatim \"{q(wid)}\"")
    stray = sorted({t for t in t5 if re.fullmatch(r"Stale \d+s|Last update \d+ s ago", t, re.DOTALL)}
                   - {q("W-5"), q("W-6"), q("W-26")})
    check(not stray, f"05: no stale chip or line with another age {stray}")
    check(q("W-24") in t8 and "(estimated)" not in t8 and not any(t.startswith("ahead ") and t != q("W-24")
                                                                  for t in t8),
          f"08: W-24 one verbatim string \"{q('W-24')}\", no separate \"(estimated)\" node")
    check(k.ARMED == "inset · ARMED (E30-D04)" and any(f"state: {k.ARMED}" == t for t in texts(7)),
          f"07: the ARMED inset named for its owner ({k.ARMED})")


def main() -> int:
    r = run([str(KIT / "e21d02kit.py"), "selftest"])
    check(r.returncode == 0, f"kit self-test: {r.stdout.strip().splitlines()[-1]}")
    check(all(k.spec_md5_ok().values()), "spec / fixture md5 pins: " +
          ", ".join(f"{x} {m[:8]}" for x, (_p, m) in k.DOCS.items()))
    check(len(k.BOARDS) <= 10 and 3 * sum(b.twin for b in k.BOARDS.values()) <= len(k.BOARDS),
          f"{len(k.BOARDS)} boards, {sum(b.twin for b in k.BOARDS.values())} light twins (≤ ⅓)")
    check(all(s in [k.state_of(f) for f in k.BOARDS[int(k.plain(c[7]))].frames] for s, (c, _i) in k.STATES.items()),
          f"§4: all {len(k.STATES)} states drawn on their §0 boards")
    build_all()
    first = digest()
    build_all()
    second = digest()
    diff = sorted(x for x in set(first) | set(second) if first.get(x) != second.get(x))
    check(not diff and len(first) == 3 * len(k.BOARDS), f"rebuild byte-identical ({len(first)} files; differing {diff[:4]})")
    for nn in sorted(k.BOARDS):
        scan(nn)
    t2_checks()
    raw7 = json.loads((k.CAP_DIR / k.BOARDS[7].sheet).read_text(encoding="utf-8"))
    envs = {fid: {n["name"] for n in frame_nodes(raw7, fid) if n["name"].startswith("env badge")}
            for fid in k.BOARDS[7].frames if fid.startswith("SCR-050/")}
    check(envs == {"SCR-050/arm-locked": {"env badge · DEMO"}, "SCR-050/demo": {"env badge · DEMO"},
                   "SCR-050/live": {"env badge · LIVE"}}, f"07: DEMO and LIVE separate frames, the badge from the "
          f"session ({envs})")
    live_own = [n["name"] for n in frame_nodes(raw7, "SCR-050/live") if "Your orders" in n["name"] and n["t"] ==
                "text" and not n["name"].startswith("th ")]
    check(not live_own, f"07: no own order under LIVE ({live_own[:3]})")
    verbatim_checks()
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failures")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
