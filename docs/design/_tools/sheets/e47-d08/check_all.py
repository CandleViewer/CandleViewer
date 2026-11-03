"""Scan the ten E47-D08 sheets: validator, pack (bare source name + sha256), mkcall4 count, shapes, inst, icons,
boolean wrap, forbidden strings, backticks in drawn text, table-cell padding (>= 16 px between texts), a caption per
frame, md line 3 (the .md beside the kit equals the cap copy), the source md5 pins. Run: python3 -I -B check_all.py (CV_CHECKOUT outside a
checkout)."""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
import e47d08kit as k  # noqa: E402

CAP, V4 = str(k.CAP_DIR), str(k.V4_DIR)
FORB = k.BANNED
SP = {"space.inset.sm": 8, "space.inset.xs": 4, "space.inset.md": 12, "space.inset.lg": 16, "space.inset.xl": 24}
CELLROW = re.compile(r"(row \d+|row · |header row)", re.DOTALL)
tot = {"sheets": 0, "shapes": 0, "frames": 0, "sections": 0, "bad": 0}
for p in sorted(glob.glob(CAP + "/[0-9][0-9]-*.json")):
    base = os.path.basename(p)
    nn = int(base[:2])
    b = k.BOARDS[nn]
    d = json.load(open(p, encoding="utf-8"))
    v = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(k.VALIDATOR), p, "--components",
                        str(k.COMPONENTS), "--tokens", str(k.TOKENS_FILE)], capture_output=True, text=True)
    pk = json.load(open(V4 + "/" + base, encoding="utf-8"))
    tmp = os.path.join(CAP, ".count-" + base)  # mkcall4 reads the pack source by compactOf.file
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dict(pk, compactOf=dict(pk["compactOf"], file=p)), f, ensure_ascii=False)
    c = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(k.MKCALL), tmp, "count"], capture_output=True,
                       text=True)
    os.remove(tmp)
    bareok = (pk["compactOf"]["file"] == base
              and pk["compactOf"]["sha256"] == hashlib.sha256(open(p, "rb").read()).hexdigest())
    cnt = {"shapes": 0, "inst": 0, "wrap": 0}
    badicon, forb, nopad, tick = set(), [], [], []

    def g(n):
        cnt["shapes"] += 1
        o = n.get("o") or {}
        if n.get("t") == "inst":
            cnt["inst"] += 1
        if "wrap" in o and o["wrap"] not in ("wrap", "nowrap"):
            cnt["wrap"] += 1
        if n.get("t") == "icon" and n.get("icon") not in k.ICONS_OK:
            badicon.add(n.get("icon"))
        if "`" in str(n.get("chars", "")):
            tick.append(n["chars"][:40])  # a cite mark is markdown, never board text
        for key in ("name", "chars", "note"):
            if isinstance(n.get(key), str) and FORB.search(n[key]):
                forb.append(n[key][:40])
        if n.get("t") == "board" and o.get("dir") == "row" and CELLROW.match(n.get("name", "")):
            kids = [x for x in n.get("kids") or [] if not x.get("abs")]
            if len(kids) >= 3 and all(x.get("t") == "board" for x in kids):
                for x in kids:
                    if '"t": "text"' in json.dumps(x) and SP.get((x.get("o") or {}).get("padX"), 0) < 8:
                        nopad.append(n["name"] + ">" + x.get("name", ""))
        for x in n.get("kids") or []:
            g(x)

    frames = caps = 0
    names = [k.frame_name(f) for f in b.frames]
    for s in d["sections"]:
        g(s["node"])
        if s["into"] == "" and s["node"]["name"] in names:
            frames += 1
        if s["into"] == "" and s["node"].get("chars", "").startswith("state: "):
            caps += 1
    tops = [x["node"] for x in d["sections"] if x["into"] == ""]
    fr_nodes = [t for t in tops if t["name"] in names]
    anns = [t for t in tops if t["name"] == "annotations"]
    right = max(f["x"] + f["w"] for f in fr_nodes)
    hug = (len(anns) == 1 and anns[0]["w"] == k.ANN_W and d["board"]["w"] == right + 80 + k.ANN_W + 80
           and all((f["w"], f["h"]) == (k.FRAME_W, k.FRAME_H) for f in fr_nodes)
           and "/" not in d["board"]["name"][len(f"{k.KEY} / {nn:02d} "):])
    md = open(p[:-5] + ".md", encoding="utf-8").read()
    mine = open(os.path.join(KIT, base[:-5] + ".md"), encoding="utf-8").read() == md
    md3 = md.split("\n")[2] == k.md_line3(nn) and re.search(r"theme (dark|light|hc)\.$", md.split("\n")[2])
    ok = (v.returncode == 0 and c.returncode == 0 and c.stdout.strip() == str(len(pk["sections"])) and bareok
          and not cnt["inst"] and not cnt["wrap"] and not badicon and not forb and not nopad and not tick and frames == len(b.frames)
          and caps == frames and hug and bool(md3) and mine and not FORB.search(md))
    tot["sheets"] += 1
    tot["shapes"] += cnt["shapes"]
    tot["frames"] += frames
    tot["sections"] += len(pk["sections"])
    tot["bad"] += not ok
    print(f"{base}: {'ok' if ok else 'FAIL'} frames {frames} caps {caps} shapes {cnt['shapes']} sections "
          f"{len(pk['sections'])} inst {cnt['inst']} wrap {cnt['wrap']} icons {sorted(badicon)} forb {forb[:2]} "
          f"nopad {nopad[:2]} tick {tick[:1]} hug {hug} md3 {bool(md3)} sha {bareok} | {v.stdout.strip().splitlines()[-1]}")
pins = all(k.spec_md5_ok().values())
print("source md5 pinned:", pins, "| totals", tot)
good = not tot["bad"] and pins and tot["sheets"] == len(k.BOARDS)
print("OK: 0 findings" if good else f"FAIL: {tot['bad']} sheet(s), {tot['sheets']} of {len(k.BOARDS)} present")
sys.exit(0 if good else 1)
