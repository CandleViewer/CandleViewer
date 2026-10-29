"""framediff.py OLD.json NEW.json [frame-name]: rebuild each sheet's frame trees from sections and list node diffs
(path, field: old -> new). Usage for proofs and for reading what a regenerated frame changed."""

import json
import sys
from pathlib import Path


def tree(sheet):
    roots, by = {}, {}
    for s in sheet["sections"]:
        n = json.loads(json.dumps(s["node"]))
        if s["into"] == "":
            roots[n["name"]] = n
            by[n["name"]] = n
        else:
            par = by.get(s["into"])
            if par is None:
                # into is a path a/b/c from a root
                parts = s["into"].split("/")
                par = by[parts[0]]
                for p in parts[1:]:
                    par = next(k for k in par.get("kids", []) if k["name"] == p)
            par.setdefault("kids", []).append(n)
        path = (s["into"] + "/" if s["into"] else "") + n["name"]
        by[path] = n
    return roots


def walk(n, p=""):
    path = f"{p}/{n['name']}" if p else n["name"]
    yield path, n
    for k in n.get("kids", []):
        yield from walk(k, path)


def diff(a, b, out, p=""):
    keys = sorted(set(a) | set(b) - {"kids"})
    for kk in keys:
        if kk == "kids":
            continue
        if a.get(kk) != b.get(kk):
            out.append((p, kk, a.get(kk), b.get(kk)))
    ka, kb = a.get("kids", []), b.get("kids", [])
    na, nb = [x["name"] for x in ka], [x["name"] for x in kb]
    if na != nb:
        out.append((p, "kids-order", na, nb))
    used = set()
    for x in ka:
        y = next((y for i, y in enumerate(kb) if y["name"] == x["name"] and i not in used), None)
        if y is None:
            out.append((p + "/" + x["name"], "REMOVED", None, None))
            continue
        used.add(kb.index(y))
        diff(x, y, out, p + "/" + x["name"])
    for i, y in enumerate(kb):
        if i not in used and y["name"] not in na:
            out.append((p + "/" + y["name"], "ADDED", None, None))


if __name__ == "__main__":
    A = tree(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    B = tree(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    names = sys.argv[3:] or [n for n in A if n.startswith("frame-")]
    for nm in names:
        out = []
        diff(A[nm], B[nm], out, nm)
        print(f"== {nm}: {len(out)} diffs")
        for p, kk, x, y in out:
            print(f"  {p} [{kk}] {str(x)[:160]!r} -> {str(y)[:160]!r}")
