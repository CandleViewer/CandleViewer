"""Import the design-system token sets into a per-set Penpot file ([PENPOT-FILES-1]).

Each design set draws in its own Penpot file, and Penpot keeps tokens per file, so every new
file needs the repository's token sets recreated in it. This tool reads the token files in
`packages/ui/tokens` (`*.tokens.json` and `themes.json`, at a git ref or on disk) and prints a
Penpot plugin script that adds the sets, their tokens and the colour themes to the file open in
the plugin's tab.

    penpot_token_sets.py --check            # convert and verify every reference; writes nothing
    penpot_token_sets.py --emit-js SET      # the plugin script for one set
    penpot_token_sets.py --emit-js themes   # the themes, after every set
    penpot_token_sets.py --self-test        # the check refuses each of its mutations

(run each as `python3 -I -B docs/design/_tools/penpot_token_sets.py ...`; add `--ref origin/main`
to read the tokens at a git ref.)

Offline, stdlib only. Re-running a script is safe: a set, token or theme that already exists is
kept, not duplicated. Token types Penpot does not support (`duration`, `cubicBezier`) are skipped
and counted; motion is specified in text, not drawn. Density has no sets of its own (`themes.json`:
a density mode is a pointer between the `.compact` and `.comfortable` aliases).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS_REL = "packages/ui/tokens"
SETS = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
SUPPORTED = {
    "borderRadius",
    "shadow",
    "color",
    "dimension",
    "fontFamilies",
    "fontSizes",
    "fontWeights",
    "letterSpacing",
    "number",
    "opacity",
    "rotation",
    "sizing",
    "spacing",
    "borderWidth",
    "textCase",
    "textDecoration",
    "typography",
}
REF = re.compile(r"\{([^{}]+)\}")
TYPO_KEYS = {
    "fontFamily": "fontFamilies",
    "fontFamilies": "fontFamilies",
    "fontSize": "fontSizes",
    "fontSizes": "fontSizes",
    "fontWeight": "fontWeight",
    "fontWeights": "fontWeight",
    "lineHeight": "lineHeight",
    "letterSpacing": "letterSpacing",
    "textCase": "textCase",
    "textDecoration": "textDecoration",
}


def read(rel: str, ref: str | None) -> str:
    if ref is None:
        return (ROOT / rel).read_text(encoding="utf-8")
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", "--end-of-options", f"{ref}:{rel}"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return out.stdout.decode("utf-8")


def load(ref: str | None) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    sets = {s: json.loads(read(f"{TOKENS_REL}/{s}.tokens.json", ref)) for s in SETS}
    themes = json.loads(read(f"{TOKENS_REL}/themes.json", ref))
    return sets, themes


def convert(value: object, kind: str) -> object:
    """A token value in the form Penpot's `addToken` takes (strings, or a composite of strings)."""
    if kind == "shadow" and isinstance(value, dict):
        out = {k: str(v) for k, v in value.items()}
        out.setdefault("inset", "false")
        return out
    if kind == "typography" and isinstance(value, dict):
        typo: dict[str, object] = {}
        for k, v in value.items():
            key = TYPO_KEYS.get(k)
            if key is None:
                raise ValueError(f"typography field {k!r} has no Penpot equivalent")
            typo[key] = [str(x) for x in v] if isinstance(v, list) else str(v)
        return typo
    if isinstance(value, (dict, list)):
        raise TypeError(f"a {kind} token with a composite value")
    return str(value)


def plan(
    sets: dict[str, dict[str, object]],
) -> tuple[dict[str, list[dict[str, object]]], dict[str, int]]:
    """Every supported token per set, in file order; the skipped types counted."""
    out: dict[str, list[dict[str, object]]] = {}
    skipped: dict[str, int] = {}
    for name, body in sets.items():
        rows: list[dict[str, object]] = []
        for key, tok in body.items():
            if key.startswith("$") or not isinstance(tok, dict):
                continue
            kind = str(tok.get("$type"))
            if kind not in SUPPORTED:
                skipped[kind] = skipped.get(kind, 0) + 1
                continue
            rows.append({"type": kind, "name": key, "value": convert(tok.get("$value"), kind)})
        out[name] = rows
    return out, skipped


def refs_of(value: object) -> list[str]:
    if isinstance(value, str):
        return REF.findall(value)
    if isinstance(value, dict):
        return [r for v in value.values() for r in refs_of(v)]
    if isinstance(value, list):
        return [r for v in value for r in refs_of(v)]
    return []


def problems(rows: dict[str, list[dict[str, object]]], themes: dict[str, object]) -> list[str]:
    """Every reference resolves inside the sets a theme activates; theme sets exist."""
    bad: list[str] = []
    names = {s: {str(r["name"]) for r in rs} for s, rs in rows.items()}
    for th in theme_list(themes):
        sets_of = th.get("sets", [])
        active = [str(s) for s in sets_of] if isinstance(sets_of, list) else []
        bad += [f"theme {th['name']}: set {s} missing" for s in active if s not in rows]
        known = set().union(*(names.get(s, set()) for s in active))
        for s in active:
            for r in rows.get(s, []):
                bad += [
                    f"theme {th['name']}: {s}/{r['name']} refers to {{{ref}}}, not defined"
                    for ref in refs_of(r["value"])
                    if ref not in known
                ]
    return sorted(set(bad))


def js_set(name: str, rows: list[dict[str, object]]) -> str:
    return (
        "const T = penpot.library.local.tokens;\n"
        f"const NAME = {json.dumps(name)};\n"
        f"const ROWS = {json.dumps(rows)};\n"
        "let set = T.sets.find(s => s.name === NAME);\n"
        "if (!set) set = T.addSet({ name: NAME });\n"
        "const have = new Set(set.tokens.map(t => t.name));\n"
        "let added = 0, kept = 0; const errs = [];\n"
        "for (const r of ROWS) {\n"
        "  if (have.has(r.name)) { kept++; continue; }\n"
        "  try { set.addToken(r); added++; } catch (e) { errs.push(r.name + ': ' + String(e.message || e).slice(0, 80)); }\n"
        "}\n"
        "return { set: NAME, added, kept, total: set.tokens.length, errors: errs.slice(0, 8), nerr: errs.length };\n"
    )


def theme_list(themes: dict[str, object]) -> list[dict[str, object]]:
    found = themes.get("themes", [])
    if not isinstance(found, list):
        raise TypeError("themes.json: `themes` is not a list")
    return [t for t in found if isinstance(t, dict)]


def js_themes(themes: dict[str, object]) -> str:
    rows = [
        {
            "group": str(t["group"]),
            "name": str(t["name"]),
            "sets": [str(s) for s in t["sets"]] if isinstance(t["sets"], list) else [],
        }
        for t in theme_list(themes)
    ]
    return (
        "const T = penpot.library.local.tokens;\n"
        f"const ROWS = {json.dumps(rows)};\n"
        "const out = [];\n"
        "for (const r of ROWS) {\n"
        "  let th = T.themes.find(t => t.group === r.group && t.name === r.name);\n"
        "  if (!th) th = T.addTheme({ group: r.group, name: r.name });\n"
        "  const have = new Set(th.activeSets.map(s => s.name));\n"
        "  for (const s of r.sets) { const set = T.sets.find(x => x.name === s); if (set && !have.has(s)) th.addSet(set); }\n"
        "  out.push(r.name + ':' + th.activeSets.map(s => s.name).join('+'));\n"
        "}\n"
        "return { themes: out };\n"
    )


def self_test(sets: dict[str, dict[str, object]], themes: dict[str, object]) -> int:
    """Each mutation of the real sets must be refused by --check (or skipped, for a type)."""
    fails = 0

    def refused(name: str, mutate: Callable[[dict[str, dict[str, object]]], None]) -> None:
        nonlocal fails
        copy = json.loads(json.dumps(sets))
        mutate(copy)
        try:
            rows, _ = plan(copy)
            bad = problems(rows, themes)
        except (TypeError, ValueError) as e:
            bad = [str(e)]
        print(f"mutation {name}: {'refused' if bad else 'ACCEPTED'}")
        fails += 0 if bad else 1

    def dangling(c: dict[str, dict[str, object]]) -> None:
        c["semantic-dark"]["color.surface.app"] = {"$type": "color", "$value": "{palette.gone}"}

    def light_only(c: dict[str, dict[str, object]]) -> None:
        # the token exists, but only in semantic-hc: the light theme does not activate that set
        c["semantic-hc"]["color.only.hc"] = {"$type": "color", "$value": "#000000"}
        c["semantic-light"]["color.only.light"] = {"$type": "color", "$value": "{color.only.hc}"}

    def bad_typo(c: dict[str, dict[str, object]]) -> None:
        c["semantic-dark"]["type.bad"] = {"$type": "typography", "$value": {"fontStretch": "1"}}

    def composite(c: dict[str, dict[str, object]]) -> None:
        c["primitives"]["space.bad"] = {"$type": "spacing", "$value": ["1", "2"]}

    refused("a reference to a token no set defines", dangling)
    refused("a light reference that only high-contrast defines", light_only)
    refused("a typography field Penpot has no field for", bad_typo)
    refused("a list value on a plain token", composite)
    copy = json.loads(json.dumps(sets))
    copy["primitives"]["motion.extra"] = {"$type": "duration", "$value": "1ms"}
    rows, skipped = plan(copy)
    ok = skipped.get("duration", 0) == 1 + sum(
        1
        for t in sets["primitives"].values()
        if isinstance(t, dict) and t.get("$type") == "duration"
    ) and all(r["name"] != "motion.extra" for r in rows["primitives"])
    print(f"mutation an unsupported type: {'skipped' if ok else 'IMPORTED'}")
    fails += 0 if ok else 1
    base_bad = problems(plan(sets)[0], themes)
    print(f"--self-test: {'ok' if not fails and not base_bad else 'FAILED'}")
    return 1 if fails or base_bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", help="read the tokens at this git ref (default: the working tree)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--emit-js", metavar="SET")
    a = ap.parse_args()
    sets, themes = load(a.ref)
    if a.self_test:
        return self_test(sets, themes)
    rows, skipped = plan(sets)
    if a.check:
        bad = problems(rows, themes)
        for b in bad:
            print("FAIL", b)
        counts = ", ".join(f"{s} {len(r)}" for s, r in rows.items())
        print(f"sets: {counts}; skipped (unsupported in Penpot): {skipped or 'none'}")
        print(f"summary: {len(bad)} FAIL")
        return 1 if bad else 0
    if a.emit_js == "themes":
        sys.stdout.write(js_themes(themes))
    elif a.emit_js in rows:
        sys.stdout.write(js_set(a.emit_js, rows[a.emit_js]))
    else:
        print(f"unknown set {a.emit_js!r}; one of {', '.join(SETS)} or themes", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
