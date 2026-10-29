"""asdrawn.py [REV]: the packed sheets in ../../v4/ against the packed sheets the boards were drawn from (REV, default
cf47ac05b: the boards PR head the ten boards were rendered at), both expanded as cvsheet v4.1 does (compact.py's
expand_styles + materialize). Every section must be node-identical, but for the carried strings cap10.CARRIES names
(each changed text node must hold exactly its carry); the notes may differ. Exit 1 on any other difference.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
KIT = Path(__file__).resolve().parents[2]  # docs/design/_tools/sheets/e42-d03
SHEETS = KIT.parent
sys.path.insert(0, str(SHEETS / "tools"))
sys.path.insert(0, str(KIT / "gen10"))
import cap10
import compact

REV = sys.argv[1] if len(sys.argv) > 1 else "cf47ac05b"


def sections(sheet):
    return [
        json.dumps(
            {
                "into": s.get("into", ""),
                "node": compact.materialize(
                    compact.expand_styles(s["node"], s.get("styles") or {})
                ),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        for s in sheet["sections"]
    ]


bad = 0
for p in sorted((KIT / "v4").glob("*.json")):
    nn = int(p.name[:2])
    rel = p.relative_to(SHEETS.parents[3]).as_posix()
    old = json.loads(
        subprocess.run(
            ["git", "-C", str(KIT), "show", f"{REV}:{rel}"],
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout
    )
    new = json.loads(p.read_text(encoding="utf-8"))
    a, b = sections(old), sections(new)
    carried = a
    for o, n in cap10.CARRIES.get(nn, []):
        carried = [
            s.replace(
                json.dumps(o, ensure_ascii=False)[1:-1], json.dumps(n, ensure_ascii=False)[1:-1]
            )
            for s in carried
        ]
    same = (
        len(a) == len(b)
        and carried == b
        and old["board"] == new["board"]
        and old["export"] == new["export"]
    )
    diff = sum(x != y for x, y in zip(a, b))
    notes = sorted(
        k
        for k in set(old["notes"]) | set(new["notes"])
        if old["notes"].get(k) != new["notes"].get(k)
    )
    bad += not same
    print(
        f"{p.name}: {len(b)} sections, {diff} differ from {REV} ({len(cap10.CARRIES.get(nn, []))} carries); "
        f"{'OK' if same else 'FAIL'}; notes changed: {', '.join(notes) or 'none'}"
    )
sys.exit(1 if bad else 0)
