"""Validate a cvsheet v1 board sheet (JSON) offline before it is rendered in Penpot.

Usage: python3 -I validate_sheet.py <sheet.json> [--tokens token-sync.json] [--components components.json]
(--tokens defaults to the token-sync.json beside this script)

Sheet shape: {"board": {"name", "w", "h", "x", "y", "o"}, "sections": [{"into": "" | "a/b", "node": node}, ...],
"export": "path-stem", "notes": {...}}. A section's "into" names an existing parent: "" (the root) or a path of
section/child names created by an EARLIER section.
Checks: node keys and required fields per type (mirrors cvsheet-v1.js), unique sibling names, every token name exists
with a type that fits its slot (colour tokens never from the primitives set; typography from the semantic set), x/y
only with abs inside a flex parent, component sets and variant props against an inventory when one is given.
Exit 1 on any error; warnings do not fail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KEYS = {
    "board": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "kids", "note"},
    "text": {"t", "name", "chars", "typo", "color", "w", "align", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "rect": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "ellipse": {"t", "name", "o", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
    "icon": {"t", "name", "icon", "color", "size", "x", "y", "abs", "alignSelf", "note"},
    "inst": {"t", "name", "set", "props", "texts", "hide", "show", "w", "h", "x", "y", "abs", "hs", "vs", "alignSelf", "note"},
}
BOARD_OPTS = {
    "dir": None, "align": None, "justify": None, "hs": None, "vs": None, "wrap": None, "clip": None, "kind": None,
    "fill": "color", "stroke": "color", "strokeWidth": "borderWidth", "strokeAlign": None, "radius": "borderRadius",
    "pad": "spacing", "padX": "spacing", "padY": "spacing", "padT": "spacing", "padR": "spacing", "padB": "spacing",
    "padL": "spacing", "gap": "spacing", "rowGap": "spacing", "colGap": "spacing", "height": "size", "width": "size",
    "minW": "size", "minH": "size", "opacity": "opacity", "shadow": "shadow",
}
SHAPE_OPTS = {"fill": "color", "stroke": "color", "strokeWidth": "borderWidth", "strokeAlign": None,
              "radius": "borderRadius", "opacity": "opacity", "width": "size", "height": "size"}
SIZING = {"fill", "fix", "auto"}

args = sys.argv[1:]
sheet_path = Path(args[0])
tok_path = Path(args[args.index("--tokens") + 1]) if "--tokens" in args else (
    Path(__file__).resolve().parent / "token-sync.json")  # default: the token dump beside this script
comp_path = Path(args[args.index("--components") + 1]) if "--components" in args else None

tokens: dict[str, set[tuple[str, str]]] = {}
for s, n, t, _v in json.loads(tok_path.read_text()):
    tokens.setdefault(n, set()).add((s, t))
inventory = json.loads(comp_path.read_text()) if comp_path and comp_path.exists() else None

errors: list[str] = []
warns: list[str] = []


def tok(where: str, name: object, kind: str) -> None:
    if not isinstance(name, str):
        errors.append(f"{where}: token is not a string: {name!r}")
        return
    hits = tokens.get(name)
    if not hits:
        errors.append(f"{where}: unknown token {name}")
        return
    types = {t for _s, t in hits}
    sets = {s for s, _t in hits}
    ok = {
        "color": {"color"}, "typography": {"typography"}, "spacing": {"spacing", "sizing"},
        "size": {"sizing", "spacing"}, "borderRadius": {"borderRadius"}, "borderWidth": {"borderWidth"},
        "opacity": {"opacity"}, "shadow": {"shadow"},
    }[kind]
    if not types & ok:
        errors.append(f"{where}: token {name} is {sorted(types)}, slot wants {kind}")
    if kind in ("color", "typography") and sets == {"primitives"}:
        errors.append(f"{where}: {kind} token {name} is a primitive; bind the semantic alias")
    elif sets == {"primitives"} and kind not in ("borderWidth",):
        warns.append(f"{where}: {name} is a Tier-1 primitive")


def opts(where: str, o: object, table: dict[str, str | None]) -> None:
    if o is None:
        return
    if not isinstance(o, dict):
        errors.append(f"{where}: o is not an object")
        return
    for k, v in o.items():
        if k not in table:
            errors.append(f"{where}: unknown option {k}")
        elif table[k]:
            tok(f"{where}.o.{k}", v, table[k])
        elif k in ("hs", "vs") and v not in SIZING:
            errors.append(f"{where}: o.{k} must be fill|fix|auto")


def node(n: object, path: str, parent_flex: bool) -> None:
    if not isinstance(n, dict) or n.get("t") not in KEYS:
        errors.append(f"{path}: bad node {str(n)[:80]}")
        return
    t = n["t"]
    where = f"{path}/{n.get('name', '?')}"
    extra = set(n) - KEYS[t]
    if extra:
        errors.append(f"{where}: unknown keys {sorted(extra)}")
    if not n.get("name"):
        errors.append(f"{where}: node without a name")
    if ("x" in n or "y" in n) and parent_flex and not n.get("abs"):
        errors.append(f"{where}: x/y inside a flex parent needs abs:true")
    for k in ("hs", "vs"):
        if k in n and n[k] not in SIZING:
            errors.append(f"{where}: {k} must be fill|fix|auto")
    if t == "board":
        opts(where, n.get("o"), BOARD_OPTS)
        flex = bool((n.get("o") or {}).get("dir"))
        names = [k.get("name") for k in n.get("kids", []) if isinstance(k, dict)]
        dup = {x for x in names if names.count(x) > 1}
        if dup:
            errors.append(f"{where}: duplicate child names {sorted(dup)}")
        for k in n.get("kids", []):
            node(k, where, flex)
    elif t == "text":
        for k in ("chars", "typo", "color"):
            if k not in n:
                errors.append(f"{where}: text needs {k}")
        if "typo" in n:
            tok(f"{where}.typo", n["typo"], "typography")
        if "color" in n:
            tok(f"{where}.color", n["color"], "color")
        if isinstance(n.get("chars"), str) and not n["chars"].strip():
            errors.append(f"{where}: empty text")
    elif t in ("rect", "ellipse"):
        opts(where, n.get("o"), SHAPE_OPTS)
        o = n.get("o") or {}
        if not ((n.get("w") and n.get("h")) or (o.get("width") and o.get("height"))):
            errors.append(f"{where}: {t} needs w and h (or o.width and o.height)")
    elif t == "icon":
        for k in ("icon", "color"):
            if k not in n:
                errors.append(f"{where}: icon needs {k}")
        if "color" in n:
            tok(f"{where}.color", n["color"], "color")
        if "size" in n:
            tok(f"{where}.size", n["size"], "size")
        if inventory and n.get("icon") not in inventory.get("icons", []):
            errors.append(f"{where}: icon '{n.get('icon')}' not in the inventory")
    elif t == "inst":
        if not n.get("set"):
            errors.append(f"{where}: inst needs set")
        elif inventory is not None:
            sets = inventory.get("sets", {})
            if n["set"] not in sets:
                errors.append(f"{where}: component set '{n['set']}' not in the inventory")
            else:
                info = sets[n["set"]]
                props = n.get("props") or {}
                variants = info.get("variants", [])
                if props and not any(all(v.get(k) == val for k, val in props.items()) for v in variants):
                    errors.append(f"{where}: no variant of '{n['set']}' matches {props}")
                texts = set(info.get("texts", []))
                for k in (n.get("texts") or {}):
                    if texts and k not in texts:
                        errors.append(f"{where}: '{n['set']}' has no text layer '{k}' (has {sorted(texts)})")


sheet = json.loads(sheet_path.read_text())
b = sheet.get("board") or {}
if not b.get("name") or not b.get("w") or not (b.get("h") or (b.get("o") or {}).get("dir")):
    errors.append("board: needs name, w and h (h may be omitted for a flex board that hugs its content)")
opts("board", b.get("o"), BOARD_OPTS)
root_flex = bool((b.get("o") or {}).get("dir"))
secs = sheet.get("sections") or []
if not secs:
    errors.append("sheet: no sections")
known: dict[str, bool] = {"": root_flex}  # path -> is flex


def collect(n: dict, base: str) -> None:
    if not isinstance(n, dict) or n.get("t") != "board":
        return
    p = (base + "/" if base else "") + str(n.get("name"))
    known[p] = bool((n.get("o") or {}).get("dir"))
    for k in n.get("kids", []):
        collect(k, p)


seen: list[str] = []
for i, sec in enumerate(secs):
    if not isinstance(sec, dict) or set(sec) - {"into", "node"} or "node" not in sec:
        errors.append(f"section {i}: must be {{into, node}}")
        continue
    into = sec.get("into", "")
    if into not in known:
        errors.append(f"section {i}: into '{into}' is not created by an earlier section")
        continue
    key = into + "//" + str(sec["node"].get("name"))
    if key in seen:
        errors.append(f"section {i}: '{sec['node'].get('name')}' rendered twice into '{into}'")
    seen.append(key)
    node(sec["node"], "sections[" + str(i) + "]" + (":" + into if into else ""), known[into])
    collect(sec["node"], into)

size = len(json.dumps(sheet))
if size > 60000:
    warns.append(f"sheet is {size} bytes; split sections so each call stays small")
for s in secs:
    n = len(json.dumps(s))
    if n > 24000:
        warns.append(f"section {(s.get('node') or {}).get('name')} is {n} bytes; split it")
for w in warns:
    print("WARN", w)
for e in errors:
    print("ERROR", e)
print(f"{sheet_path.name}: {len(errors)} errors, {len(warns)} warnings, {len(secs)} sections, {size} bytes")
sys.exit(1 if errors else 0)
