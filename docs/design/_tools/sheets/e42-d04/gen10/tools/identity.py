"""identity.py [--drift]: for each cap10b board, rebuild every frame root from the earlier sheet and the current one
(../E42-D04-cap10b/) and report which frame roots are node-identical (json, sorted keys), which differ only in node
"note" fields, and which differ in any drawing field; the annotation column is compared as text.

Default (Fix pass 3): the earlier sheets are gen10/pre-repin/cap10b/ (before the re-pin to cbec19a92); every frame
root must be identical or notes-only: a drawing diff exits 1. --drift: the drift fix pass's proof (gen10/pre-drift/
cap10b/ vs today), where the seven redrawn frames were expected to differ.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from framediff import tree, walk  # noqa: E402

G10 = Path(__file__).resolve().parent.parent
DRIFT = "--drift" in sys.argv
OLD = G10 / ("pre-drift" if DRIFT else "pre-repin") / "cap10b"
NEW = G10.parent / "cap10b"
EXPECTED = {"AL-18 · 1280×800 [18]", "AD-1 · 1280×800 [30]", "AD-1 · 2560×1440 [30]", "MM-2 · 1280×800 [55]",
            "MM-6 · 1280×800 [59]", "motion-safe storyboard · 1280×800 [63]",
            "motion-reduce twins · 1280×800 [64]"} if DRIFT else set()


def strip(n):
    """n without its "note" fields (recursively)."""
    n = {k: v for k, v in n.items() if k != "note"}
    if "kids" in n:
        n["kids"] = [strip(k) for k in n["kids"]]
    return n


def dump(n):
    return json.dumps(n, sort_keys=True, ensure_ascii=False)


tot = {"same": 0, "notes": 0, "drawing": 0, "notes_changed": 0, "ann_changed": 0}
bad = []
for op in sorted(OLD.glob("*.json")):
    sa, sb = json.load(open(op, encoding="utf-8")), json.load(open(NEW / op.name, encoding="utf-8"))
    a, b = tree(sa), tree(sb)
    root = {k: (sa["board"].get(k), sb["board"].get(k)) for k in sorted(set(sa["board"]) | set(sb["board"]))
            if sa["board"].get(k) != sb["board"].get(k)}
    root.update({k: (sa.get(k), sb.get(k)) for k in ("export",) if sa.get(k) != sb.get(k)})
    tot["root"] = tot.get("root", []) + ([f"{op.stem}: " + ", ".join(f"{k} {v[0]} -> {v[1]}" for k, v in root.items())]
                                         if root else [])
    frames = [n for n in a if n != "annotations"]
    if sorted(frames) != sorted(n for n in b if n != "annotations"):
        bad.append(f"{op.name}: frame roots differ {sorted(frames)} vs {sorted(b)}")
    same = [n for n in frames if dump(a[n]) == dump(b.get(n))]
    notes = [n for n in frames if n not in same and dump(strip(a[n])) == dump(strip(b[n]))]
    drawing = [n for n in frames if n not in same and n not in notes]
    nch = sum(1 for n in notes for (_p, x), (_q, y) in zip(walk(a[n]), walk(b[n])) if x.get("note") != y.get("note"))
    at = [x.get("chars") for _p, x in walk(a["annotations"])]
    bt = [x.get("chars") for _p, x in walk(b["annotations"])]
    ach = sum(1 for x, y in zip(at, bt) if x != y) + abs(len(at) - len(bt))
    nodes = sum(sum(1 for _ in walk(b[n])) for n in frames)
    tot["same"] += len(same)
    tot["notes"] += len(notes)
    tot["drawing"] += len(drawing)
    tot["notes_changed"] += nch
    tot["ann_changed"] += ach
    bad += [f"{op.name}: unexpected drawing diff in {n}" for n in drawing if n not in EXPECTED]
    print(f"{op.stem}: {len(frames)} frame roots ({nodes} nodes): {len(same)} identical, {len(notes)} notes only "
          f"({nch} notes changed){': ' + ', '.join(notes) if notes else ''}; {len(drawing)} drawing diffs"
          f"{': ' + ', '.join(drawing) if drawing else ''}; annotation column: {ach} text nodes changed "
          f"({len(at)} -> {len(bt)}); root: {', '.join(f'{k} {v[0]} -> {v[1]}' for k, v in root.items()) or 'same'}")
print(f"TOTAL ({OLD.relative_to(G10)} -> E42-D04-cap10b): {tot['same']} frame roots node-identical, {tot['notes']} "
      f"differ only in node notes ({tot['notes_changed']} notes), {tot['drawing']} with drawing diffs; annotation "
      f"text nodes changed {tot['ann_changed']}; unexpected: {bad or 'none'}")
sys.exit(1 if bad else 0)
