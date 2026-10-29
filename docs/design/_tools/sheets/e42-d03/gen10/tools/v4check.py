"""v4check.py: for each packed cap10 sheet (../../v4/), expand every section (compact.py's expand_styles +
materialize, what cvsheet v4.1 does in Penpot), check it equals the cap10 sheet's section, check compactOf names that
sheet with its sha256, write the expansion to gen10/v4check/ and run validate_sheet.py on it (exit 0 required).
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SHEETS = Path(__file__).resolve().parents[3]  # docs/design/_tools/sheets
KIT = SHEETS / "e42-d03"
sys.path.insert(0, str(SHEETS / "tools"))
sys.dont_write_bytecode = True
import compact

OUT = KIT / "gen10" / "v4check"
OUT.mkdir(exist_ok=True)
bad = 0
for p in sorted((KIT / "v4").glob("*.json")):
    packed = json.loads(p.read_text(encoding="utf-8"))
    orig_p = KIT / "cap10" / p.name
    orig = json.loads(orig_p.read_text(encoding="utf-8"))
    sha = hashlib.sha256(orig_p.read_bytes()).hexdigest()
    co = json.dumps(packed.get("compactOf"))
    secs = []
    for s, o in zip(packed["sections"], orig["sections"]):
        n = compact.materialize(compact.expand_styles(s["node"], s.get("styles") or {}))
        secs.append({"into": s.get("into", ""), "node": n})
    same = len(secs) == len(orig["sections"]) and all(
        json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        for a, b in zip(secs, orig["sections"])
    )
    exp = {k: v for k, v in orig.items() if k != "sections"}
    exp["sections"] = secs
    xp = OUT / p.name
    xp.write_text(json.dumps(exp, ensure_ascii=False, indent=1), encoding="utf-8")
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SHEETS / "tools" / "validate_sheet.py"),
            str(xp),
            "--components",
            str(SHEETS / "tools" / "components.offline.json"),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    last = (r.stdout + r.stderr).strip().splitlines()[-1]
    ok = same and r.returncode == 0 and sha in co
    bad += not ok
    print(
        f"{p.name}: expands to the cap10 sheet {same}; compactOf sha256 matches {sha in co}; validator exit "
        f"{r.returncode}: {last}"
    )
sys.exit(1 if bad else 0)
