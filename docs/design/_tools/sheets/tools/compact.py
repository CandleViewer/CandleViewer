"""Compact a cvsheet board sheet for cvsheet v4.1 (clone nodes + per-section styles) without changing its rendering.

Usage: python3 -I compact.py <sheet.json> <out.json>     ("-" reads stdin / writes the JSON to stdout, stats to stderr)

Writes a sheet with the same board / export / notes whose sections carry `styles` and `s` refs and `clone` nodes, then
prints the before -> after byte counts (JSON with compact separators, UTF-8) of the sheet and of its sections. v4.1: the
output carries "compactOf": {"file": the original's absolute path (null when read from stdin), "sha256": of the bytes
read}, and mkcall4.py refuses to render it once that file is missing or changed. The output file is written next to its
target and renamed over it, so a reader never sees half a file.

Clones. In every kids array a later sibling B becomes {"t":"clone","name":B.name,"of":A.name,"set":{...},"texts":{...}}
of the EARLIEST earlier sibling A that equals B except for the root name, text nodes' chars and color, and (when B is
itself an inst) its `texts` values (same keys). Everything else must be equal: types, keys, o, sizes, order, kids'
names, hide/show, props, x/y/abs, notes. Override paths are child names joined by "/" ("" = B itself); A's name must
be unique among the siblings, every path segment unique among its siblings and free of "/". B is replaced only when it
has kids and the clone saves at least 30 % of B's bytes. v4.1: a node without kids (text, rect, icon, inst, an empty
board) is never cloned, since with styles factored its plain form is about as small as a clone (the review's second
option; judging the 30 % against B's styled size instead made the corpus 0.8 % larger than v4, this rule 0.2 %
smaller). Not cloned: a difference in the `texts` of an inst NESTED inside B (a clone's `texts` must be keys of the
copied inst's own `texts`).
Styles. Per section, a node's keys other than name, chars, kids, texts, x, y form its style object; an object that
occurs at least twice gets a short key (a, b, ..., z, aa, ...; most frequent first) and those nodes carry "s": key.
Self-check: expanding the styles and materialising every clone (copy of the source + overrides, what cvsheet v4.1's
S.resolve does inside Penpot) must give back the original section exactly (canonical JSON), otherwise the script exits
3 and writes nothing.
Exit codes: 0 ok, 2 usage / not a sheet / already compact, 3 self-check failed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

NO_STYLE = ("name", "chars", "kids", "texts", "x", "y")
MIN_SAVING = 0.30


def dumps(x: object) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def nbytes(x: object) -> int:
    return len(dumps(x).encode("utf-8"))


def canon(x: object) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def same(a: object, b: object) -> bool:
    return canon(a) == canon(b)


class NoMatch(Exception):
    pass


def seg_ok(name: object, siblings: list[Any]) -> bool:
    """A child name usable as one path segment: a non-empty string without "/", unique among its siblings."""
    if not isinstance(name, str) or not name or "/" in name:
        return False
    return sum(1 for s in siblings if isinstance(s, dict) and s.get("name") == name) == 1


def walk_match(
    a: dict[str, Any],
    b: dict[str, Any],
    path: str,
    path_ok: bool,
    root: bool,
    sets: dict[str, Any],
    texts: dict[str, Any],
) -> None:
    if (
        not isinstance(a, dict)
        or not isinstance(b, dict)
        or set(a) != set(b)
        or a.get("t") != b.get("t")
    ):
        raise NoMatch
    t = a.get("t")
    for k, va in a.items():
        vb = b[k]
        if k == "name" and root:
            continue
        if t == "text" and k in ("chars", "color"):
            if not same(va, vb):
                if not path_ok:
                    raise NoMatch
                sets.setdefault(path, {})[k] = vb
            continue
        if t == "inst" and k == "texts" and root:
            if not isinstance(va, dict) or not isinstance(vb, dict) or set(va) != set(vb):
                raise NoMatch
            for layer in va:
                if not same(va[layer], vb[layer]):
                    texts[layer] = vb[layer]
            continue
        if k == "kids":
            if not isinstance(va, list) or not isinstance(vb, list) or len(va) != len(vb):
                raise NoMatch
            for x, y in zip(va, vb):
                if not isinstance(x, dict):
                    raise NoMatch
                nm = x.get("name")
                ok = path_ok and seg_ok(nm, va)
                walk_match(
                    x, y, (path + "/" + str(nm)) if path else str(nm), ok, False, sets, texts
                )
            continue
        if not same(va, vb):
            raise NoMatch


def match(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The overrides (set, texts) that turn a copy of A into B, or None when A and B differ anywhere else."""
    sets: dict[str, Any] = {}
    texts: dict[str, Any] = {}
    try:
        walk_match(a, b, "", True, True, sets, texts)
    except NoMatch:
        return None
    return sets, texts


def compact_node(n: dict[str, Any], st: dict[str, Any]) -> dict[str, Any]:
    """A copy of n whose kids arrays use clone nodes (recursively; a clone's own subtree is not visited)."""
    if not isinstance(n.get("kids"), list):
        return n
    kids = n["kids"]
    out = []
    for i, b in enumerate(kids):
        rep = None
        for j in range(i):
            a = kids[j]
            m = match(a, b)
            if m is None:
                continue
            # the EARLIEST matching earlier sibling only
            if not (isinstance(b.get("kids"), list) and b["kids"]):
                st["clone_leaf"] += 1  # v4.1: a node without kids is never cloned
            elif seg_ok(a.get("name"), kids) and isinstance(b.get("name"), str):
                node = {"t": "clone", "name": b["name"], "of": a["name"]}
                if m[0]:
                    node["set"] = m[0]
                if m[1]:
                    node["texts"] = m[1]
                if nbytes(node) <= (1.0 - MIN_SAVING) * nbytes(b):
                    rep = node
                else:
                    st["clone_too_small"] += 1
            else:
                st["clone_bad_name"] += 1
            break
        if rep is not None:
            st["clones"] += 1
            out.append(rep)
        else:
            out.append(compact_node(b, st))
    r = dict(n)
    r["kids"] = out
    return r


def short_key(i: int) -> str:
    """0 -> a, 25 -> z, 26 -> aa, 27 -> ab, ... (bijective base 26)."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


def style_obj(n: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in n.items() if k not in NO_STYLE}


def style_table(node: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """(canon(style object) -> short key, short key -> style object) for every style object that occurs at least twice
    in the tree. Keys go by frequency (the most used gets "a"), ties by first occurrence; the object kept is the first.
    """
    count: dict[str, int] = {}
    first: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def visit(n: dict[str, Any]) -> None:
        key = canon(style_obj(n))
        if key not in count:
            count[key] = 0
            first[key] = style_obj(n)
            order.append(key)
        count[key] += 1
        for k in n.get("kids", []) or []:
            visit(k)

    visit(node)
    pos = {k: i for i, k in enumerate(order)}
    keys = sorted((k for k in order if count[k] >= 2), key=lambda k: (-count[k], pos[k]))
    names = {k: short_key(i) for i, k in enumerate(keys)}
    return names, {names[k]: first[k] for k in keys}


def apply_styles(n: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """n with every node whose style object is named replaced by {"s": key} + its NO_STYLE keys (recursively)."""
    key = canon(style_obj(n))
    if key in names:
        r: dict[str, Any] = {"s": names[key]}
        r.update({k: v for k, v in n.items() if k in NO_STYLE})
    else:
        r = dict(n)
    if isinstance(r.get("kids"), list):
        r["kids"] = [apply_styles(k, names) for k in r["kids"]]
    return r


def factor_styles(node: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    names, styles = style_table(node)
    return apply_styles(node, names), styles


# ---- self-check: the inverse of the two steps above, mirroring cvsheet v4.1 (S.expand, then S.resolve) ----
def expand_styles(n: dict[str, Any], styles: dict[str, Any]) -> dict[str, Any]:
    if "s" in n:
        x = dict(styles[n["s"]])
        x.update({k: v for k, v in n.items() if k != "s"})
    else:
        x = dict(n)
    if isinstance(x.get("kids"), list):
        x["kids"] = [expand_styles(k, styles) for k in x["kids"]]
    return x


def at_unique(root: dict[str, Any], path: str) -> dict[str, Any]:
    cur = root
    for seg in [s for s in path.split("/") if s]:
        hits = [k for k in cur.get("kids", []) or [] if k.get("name") == seg]
        if len(hits) != 1:
            raise ValueError(f"path {path!r}: segment {seg!r} matches {len(hits)}")
        cur = hits[0]
    return cur


def materialize(n: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(n.get("kids"), list):
        return n
    kids: list[Any] = []
    for k in n["kids"]:
        if k.get("t") == "clone":
            srcs = [x for x in kids if x.get("name") == k["of"]]
            if len(srcs) != 1:
                raise ValueError(f"clone {k['name']!r}: source {k['of']!r} matches {len(srcs)}")
            c = copy.deepcopy(srcs[0])
            c["name"] = k["name"]
            for path, o in (k.get("set") or {}).items():
                t = at_unique(c, path)
                if t.get("t") != "text":
                    raise ValueError(f"clone {k['name']!r}: set target {path!r} is not a text")
                for f in ("chars", "color"):
                    if f in o:
                        t[f] = o[f]
            for layer, chars in (k.get("texts") or {}).items():
                if c.get("t") != "inst" or layer not in (c.get("texts") or {}):
                    raise ValueError(
                        f"clone {k['name']!r}: texts key {layer!r} is not a texts key of the source inst"
                    )
                c["texts"][layer] = chars
            for f in ("x", "y", "abs"):
                if f in k:
                    c[f] = k[f]
            kids.append(c)
        else:
            kids.append(materialize(k))
    r = dict(n)
    r["kids"] = kids
    return r


def count_nodes(n: dict[str, Any]) -> int:
    return 1 + sum(count_nodes(k) for k in n.get("kids", []) or [])


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    stdin = argv[1] == "-"
    src, dst = Path(argv[1]), Path(argv[2])
    name = "<stdin>" if stdin else src.name
    if not stdin and argv[2] != "-" and dst.resolve() == src.resolve():
        print(f"{name}: the output would overwrite the original", file=sys.stderr)
        return 2
    # the bytes are read once: the stamp below hashes exactly what was compacted
    raw = sys.stdin.buffer.read() if stdin else src.read_bytes()
    try:
        sheet = json.loads(raw.decode("utf-8"))
    except ValueError as e:
        print(f"{name}: not JSON ({e})", file=sys.stderr)
        return 2
    if (
        not isinstance(sheet, dict)
        or not isinstance(sheet.get("board"), dict)
        or not isinstance(sheet.get("sections"), list)
    ):
        print(f"{name}: not a cvsheet sheet (needs board and sections)", file=sys.stderr)
        return 2

    def compacted(n: object) -> bool:
        return isinstance(n, dict) and (
            "s" in n or n.get("t") == "clone" or any(compacted(k) for k in n.get("kids", []) or [])
        )

    if "compactOf" in sheet or any(
        "styles" in s or compacted(s.get("node")) for s in sheet["sections"]
    ):
        print(
            f"{name}: already compact (compactOf, styles, s refs or clone nodes); give the original sheet",
            file=sys.stderr,
        )
        return 2
    st = {
        "clones": 0,
        "clone_leaf": 0,
        "clone_too_small": 0,
        "clone_bad_name": 0,
        "styles": 0,
        "nodes_before": 0,
        "nodes_after": 0,
    }
    sections = []
    largest = (-1, "", 0)
    for i, sec in enumerate(sheet["sections"]):
        node = sec["node"]
        cnode = compact_node(node, st)
        snode, styles = factor_styles(cnode)
        out = {"into": sec.get("into", ""), "node": snode}
        if styles:
            out["styles"] = styles
        for k, v in sec.items():  # keep any other section key as it is
            if k not in ("into", "node"):
                out[k] = v
        back = materialize(expand_styles(snode, styles))
        if not same(back, node):
            print(
                f"{name}: SELF-CHECK FAILED in section {i} ({node.get('name')}); nothing written",
                file=sys.stderr,
            )
            return 3
        st["styles"] += len(styles)
        st["nodes_before"] += count_nodes(node)
        st["nodes_after"] += count_nodes(snode)
        sections.append(out)
        b = nbytes(out)
        if b > largest[2]:
            largest = (i, str(node.get("name")), b)
    res = {k: (sections if k == "sections" else v) for k, v in sheet.items()}
    # v4.1: name the original and hash the bytes compacted (top level: mkcall4.py checks it, calls never carry it)
    res["compactOf"] = {
        "file": None if stdin else str(src.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    text = dumps(res) + "\n"
    log = sys.stdout
    if argv[2] == "-":
        sys.stdout.write(text)
        log = sys.stderr
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, dst)
    b0, b1 = nbytes(sheet), nbytes(res)
    s0, s1 = sum(nbytes(s) for s in sheet["sections"]), sum(nbytes(s) for s in sections)
    print(
        f"{name}: sheet {b0} -> {b1} bytes ({100.0 * (b1 - b0) / b0:+.1f}%); sections {s0} -> {s1}; "
        f"nodes {st['nodes_before']} -> {st['nodes_after']}; clones {st['clones']} "
        f"(kept {st['clone_leaf']} leaves and {st['clone_too_small']} under 30%, {st['clone_bad_name']} unaddressable); "
        f"styles {st['styles']}; "
        f"largest section {largest[0]} '{largest[1]}' {largest[2]} bytes",
        file=log,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
