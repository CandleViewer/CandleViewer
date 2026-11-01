"""Scan the ten E47-D03 sheets in build/: validator, pack (bare source name + sha256), mkcall4 count, shapes, inst,
icons, boolean wrap, forbidden strings, table-cell padding (>= 16 px between texts), a caption per frame, md line 3 (the
committed .md beside the kit equals build/'s), spec md5 pin. Run from this folder: python3 -I -B check_all.py"""
import glob, hashlib, json, os, re, subprocess, sys
KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import e47d03kit as k  # noqa: E402
CAP, V4 = str(k.CAP_DIR), str(k.V4_DIR)
FORB = k.BANNED
SP = {"space.inset.sm": 8, "space.inset.xs": 4, "space.inset.md": 12, "space.inset.lg": 16, "space.inset.xl": 24}
tot = {"shapes": 0, "frames": 0, "bad": 0}
for p in sorted(glob.glob(CAP + "/[0-9][0-9]-*.json")):
    base = os.path.basename(p); nn = int(base[:2]); b = k.BOARDS[nn]
    d = json.load(open(p, encoding="utf-8"))
    v = subprocess.run([sys.executable, "-I", "-B", str(k.VALIDATOR), p, "--components", str(k.COMPONENTS),
                        "--tokens", str(k.TOKENS_FILE)], capture_output=True, text=True)
    pk = json.load(open(V4 + "/" + base, encoding="utf-8"))
    # mkcall4 reads the pack source by compactOf.file, so count a temporary copy beside the raw sheet
    tmp = os.path.join(CAP, ".count-" + base)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(pk, compactOf=dict(pk["compactOf"], file=p)), f, ensure_ascii=False)
    c = subprocess.run([sys.executable, "-I", "-B", str(k.MKCALL), tmp, "count"], capture_output=True, text=True)
    os.remove(tmp)
    bareok = (pk["compactOf"]["file"] == base
              and pk["compactOf"]["sha256"] == hashlib.sha256(open(p, "rb").read()).hexdigest())
    cnt = {"shapes": 0, "inst": 0, "wrap": 0}; badicon, forb, nopad = set(), [], []

    def g(n):
        cnt["shapes"] += 1
        o = n.get("o") or {}
        if n.get("t") == "inst": cnt["inst"] += 1
        if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"): cnt["wrap"] += 1
        if n.get("t") == "icon" and n.get("icon") not in k.ICONS_OK: badicon.add(n.get("icon"))
        for key in ("name", "chars", "note"):
            if isinstance(n.get(key), str) and FORB.search(n[key]): forb.append(n[key][:40])
        if n.get("t") == "board" and o.get("dir") == "row" and re.match(r"(row|header row)", n.get("name", "")):
            kids = n.get("kids") or []
            if len(kids) >= 3 and all(x.get("t") == "board" for x in kids):
                for x in kids:
                    if '"t": "text"' in json.dumps(x) and SP.get((x.get("o") or {}).get("padX"), 0) < 8:
                        nopad.append(n["name"] + ">" + x.get("name", ""))
        for x in n.get("kids") or []: g(x)
    frames = caps = 0
    for s in d["sections"]:
        g(s["node"])
        if s["into"] == "" and s["node"]["name"] in [k.frame_name(f) for f in b.frames]: frames += 1
        if s["into"] == "" and s["node"].get("chars", "").startswith("state: "): caps += 1
    md = open(p[:-5] + ".md", encoding="utf-8").read()
    mine = open(os.path.join(KIT, base[:-5] + ".md"), encoding="utf-8").read() == md
    md3 = md.split("\n")[2] == k.md_line3(nn) and re.search(r"theme (dark|light|hc)\.$", md.split("\n")[2])
    ok = (v.returncode == 0 and c.returncode == 0 and c.stdout.strip() == str(len(pk["sections"])) and bareok
          and not cnt["inst"] and not cnt["wrap"] and not badicon and not forb and not nopad and frames == len(b.frames)
          and caps == frames and md3 and mine and not FORB.search(md))
    tot["shapes"] += cnt["shapes"]; tot["frames"] += frames; tot["bad"] += not ok
    print(f"{base}: {'ok' if ok else 'FAIL'} frames {frames} caps {caps} shapes {cnt['shapes']} inst {cnt['inst']} "
          f"wrap {cnt['wrap']} icons {sorted(badicon)} forb {forb[:2]} nopad {nopad[:2]} md3 {bool(md3)} "
          f"| {v.stdout.strip().splitlines()[-1]}")
print("spec md5 pinned:", all(k.spec_md5_ok().values()), "| totals", tot)
print("OK: 0 findings" if not tot["bad"] and all(k.spec_md5_ok().values()) else f"FAIL: {tot['bad']} sheet(s)")
sys.exit(1 if tot["bad"] or not all(k.spec_md5_ok().values()) else 0)
