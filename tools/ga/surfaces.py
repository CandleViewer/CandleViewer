"""E49-Q01 (#1335): why a Must story is a gap, checked against the code instead of asserted.

Each declared gap (docs/qa/ga-coverage-gaps.json) carries a ``surface`` object; its reason in the
coverage map is rendered from it, and ``findings`` fails when the code says otherwise, so a
boilerplate "not shipped" cannot be stamped on a story whose surface is in the build (QA lens
r1). The story's screens come from docs/plan/18-traceability-matrix.md (story -> SCR-nnn, SCR ->
route); a screen is **built** when a non-test source file under apps/web/src or apps/desktop/src
cites its id; a route is a **stub** when apps/web/src/routes/tree.tsx renders it with
``StubRoute``/``PlaceholderRoute``; a file is **mounted** when the app entry points import it,
transitively (relative imports).

Kinds:

* ``unbuilt`` - no source cites any of the story's screens and each routed screen's route is a
  stub. ``incidental: {SCR: why}`` lists screens a shipped file cites in passing (a comment, a
  shared region), each with its reason; an incidental screen must be one of the story's.
* ``unmounted`` with ``module`` (a path) and optional ``entry`` - the code exists but nothing
  mounts it: the module is not reachable from the entry points, or (with ``entry``) no source
  outside the module references ``entry``. Routed screens must still be stubs.
* ``partial`` with ``shipped`` (route ids or source paths) and ``note`` - part of the surface is in
  the build (each shipped route is not a stub; each shipped path is mounted); the rest is not.
* ``shipped`` with ``where`` (a route id or a source path) - the surface is in the build and no
  pack spec covers it yet; ``where`` must be a non-stub route or a mounted file.
* ``below-e2e`` with ``verified_by`` (repo paths) - no user-visible flow of its own; each path
  must exist.

Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

MATRIX = "docs/plan/18-traceability-matrix.md"
TREE = "apps/web/src/routes/tree.tsx"
SOURCES = ("apps/web/src", "apps/desktop/src")
ENTRIES = ("apps/web/src/main.tsx", "apps/desktop/src/main/index.ts")
KINDS = ("unbuilt", "unmounted", "partial", "shipped", "below-e2e")

_STORY_ROW = re.compile(r"^\| \*\*(US-[A-Z]+-\d+)\*\*[^|]*\|[^|]*\|([^|]*)\|", re.M)
_SCREEN_ROW = re.compile(r"^\| \*\*(SCR-\d{3})\*\* \|[^|]*\|([^|]*)\|", re.M)
_SCR = re.compile(r"\bSCR-\d{3}\b")
_ROUTE = re.compile(r"\bR-\d{3}\b")
_TEST_FILE = re.compile(r"\.(?:test|spec|stories)\.[cm]?tsx?$")
_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)["'](\.{1,2}/[^"']+)["']""")
_SPECIAL = re.compile(r'if \(routeId === "(R-\d{3})"\)')


@dataclass
class Code:
    """What the repository builds, read once per check."""

    root: Path

    def _read(self, rel: str) -> str:
        path = self.root / rel
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    @cached_property
    def story_screens(self) -> dict[str, list[str]]:
        text = self._read(MATRIX)
        return {m.group(1): _SCR.findall(m.group(2)) for m in _STORY_ROW.finditer(text)}

    @cached_property
    def screen_routes(self) -> dict[str, list[str]]:
        text = self._read(MATRIX)
        return {m.group(1): _ROUTE.findall(m.group(2)) for m in _SCREEN_ROW.finditer(text)}

    @cached_property
    def sources(self) -> dict[str, str]:
        out = {}
        for base in SOURCES:
            for path in sorted((self.root / base).rglob("*")):
                source = path.suffix in (".ts", ".tsx") and not _TEST_FILE.search(path.name)
                if source and "__tests__" not in path.parts:
                    rel = path.relative_to(self.root).as_posix()
                    out[rel] = path.read_text(encoding="utf-8")
        return out

    def _resolve(self, importer: str, spec: str) -> str | None:
        base = (Path(importer).parent / spec).as_posix()
        parts: list[str] = []
        for part in base.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        stem = "/".join(parts)
        for cand in (stem, re.sub(r"\.[cm]?js$", "", stem)):
            for ext in ("", ".ts", ".tsx", "/index.ts", "/index.tsx"):
                if cand + ext in self.sources:
                    return cand + ext
        return None

    @cached_property
    def mounted(self) -> set[str]:
        seen: set[str] = set()
        stack = [e for e in ENTRIES if e in self.sources]
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            for m in _IMPORT.finditer(self.sources[f]):
                target = self._resolve(f, m.group(1))
                if target:
                    stack.append(target)
        return seen

    @cached_property
    def citing(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for path, text in self.sources.items():
            for scr in sorted(set(_SCR.findall(text))):
                out.setdefault(scr, []).append(path)
        return out

    @cached_property
    def real_routes(self) -> set[str]:
        """Routes tree.tsx renders with a real element (special-cased and not a stub)."""
        text = self._read(TREE)
        out = set()
        for m in _SPECIAL.finditer(text):
            end = text.find("\n  if (", m.end())
            block = text[m.end() : end if end != -1 else len(text)]
            if "StubRoute" not in block and "PlaceholderRoute" not in block:
                out.add(m.group(1))
        return out

    def routes_of(self, story: str) -> list[str]:
        return sorted(
            {r for s in self.story_screens.get(story, []) for r in self.screen_routes.get(s, [])}
        )


def _where_ok(code: Code, where: str) -> bool:
    if _ROUTE.fullmatch(where):
        return where in code.real_routes
    return where in code.mounted


def findings(gap: Mapping[str, Any], code: Code) -> list[str]:
    """Each way the gap's declared surface disagrees with the code."""
    story = str(gap.get("story", "?"))
    surface = gap.get("surface")
    if not surface:
        return []  # coverage_map reports the missing field
    if not isinstance(surface, dict) or surface.get("kind") not in KINDS:
        return [f"{story}: `surface.kind` must be one of {', '.join(KINDS)}"]
    kind = surface["kind"]
    screens = code.story_screens.get(story)
    out: list[str] = []
    if kind == "below-e2e":
        paths = surface.get("verified_by") or []
        if not paths:
            out.append(f"{story}: below-e2e names no `verified_by` test path")
        out += [
            f"{story}: verified_by {p} does not exist"
            for p in paths
            if not (code.root / p).exists()
        ]
        return out
    if screens is None:
        return [f"{story}: no row in {MATRIX}, so its screens cannot be checked"]
    incidental = surface.get("incidental") or {}
    for scr, why in sorted(incidental.items()):
        if scr not in screens:
            out.append(f"{story}: incidental {scr} is not one of its screens {screens}")
        if not str(why).strip():
            out.append(f"{story}: incidental {scr} gives no reason")
    if kind in ("shipped", "partial"):
        given = [surface.get("where")] if kind == "shipped" else list(surface.get("shipped") or [])
        wheres = [w for w in given if isinstance(w, str) and w]
        if not wheres or len(wheres) != len(given):
            return [*out, f"{story}: {kind} names no shipped route or path"]
        for w in wheres:
            if not _where_ok(code, w):
                out.append(f"{story}: {w} is not in the build (a stub route or an unmounted file)")
        if kind == "partial" and not str(surface.get("note", "")).strip():
            out.append(f"{story}: partial needs a `note` on what is and is not shipped")
        return out
    stubs_needed = [r for r in code.routes_of(story) if r in code.real_routes]
    out += [
        f"{story}: route {r} renders a real screen, so the surface is shipped" for r in stubs_needed
    ]
    module = str(surface.get("module", ""))
    for scr in screens:
        if scr in incidental:
            continue
        for path in code.citing.get(scr, []):
            inside = kind == "unmounted" and module and path.startswith(module.rstrip("/") + "/")
            if kind == "unbuilt":
                out.append(f"{story}: {path} cites {scr}, so it is built (unmounted? incidental?)")
            elif not inside and path in code.mounted:
                out.append(f"{story}: mounted {path} cites {scr}, so it may be shipped")
    if kind == "unmounted":
        files = [p for p in code.sources if p.startswith(module.rstrip("/") + "/")]
        if not files:
            out.append(f"{story}: module {module} has no source files")
        entry = surface.get("entry")
        if entry:
            ident = re.compile(rf"\b{re.escape(str(entry))}\b")
            users = [p for p, t in code.sources.items() if p not in files and ident.search(t)]
            out += [f"{story}: {p} references {entry}, so {module} is mounted" for p in users]
        else:
            out += [f"{story}: {p} is mounted by the app" for p in files if p in code.mounted]
    return out


def reason(gap: Mapping[str, Any], code: Code) -> str:
    """The coverage map's reason for a gap, rendered from its surface."""
    surface = gap.get("surface") or {}
    kind = surface.get("kind")
    owner = gap.get("owner_epic", "?")
    story = str(gap.get("story"))
    incidental = surface.get("incidental") or {}
    own = [x for x in code.story_screens.get(story, []) if x not in incidental]
    screens = ", ".join(own) or "none of its own"
    routes = code.routes_of(story)
    stub = f"; {', '.join(routes)} render{'s' if len(routes) == 1 else ''} a stub" if routes else ""
    extra = "".join(f" {scr}: {why}." for scr, why in sorted(incidental.items()))
    if kind == "below-e2e":
        tests = ", ".join(f"`{p}`" for p in surface.get("verified_by", []))
        return f"No user-visible flow of its own; verified below E2E by {tests}"
    if kind == "unbuilt":
        return (
            f"Not built: no source implements {screens}{stub}; joins when {owner} ships it.{extra}"
        )
    if kind == "unmounted":
        how = (
            f"nothing outside it calls `{surface['entry']}`"
            if surface.get("entry")
            else "no entry point imports it"
        )
        return (
            f"Built, not mounted: `{surface.get('module')}` exists but {how} ({screens}{stub});"
            f" joins when {owner} mounts it.{extra}"
        )
    if kind == "partial":
        return (
            f"Partly shipped ({', '.join(surface.get('shipped', []))}): {surface.get('note')};"
            f" spec not yet written - {owner} (a person is assigned at claim).{extra}"
        )
    if kind == "shipped":
        return (
            f"Shipped at {surface.get('where')}; spec not yet written - {owner} (a person is"
            f" assigned at claim).{extra}"
        )
    return "UNDECLARED"


def check_all(gaps: Sequence[Mapping[str, Any]], root: Path) -> list[str]:
    code = Code(root)
    return [f for g in gaps for f in findings(g, code)]
