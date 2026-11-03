"""E49-Q01 (#1335): read the GA regression pack's tags out of the Playwright specs, statically.

A test joins the pack with the tag ``@ga-regression``; it names its report area with exactly one
``@ga-area-<area>`` and the user stories it covers with ``@story-US-<GROUP>-<nnn>``. A quarantined
pack test also carries ``@flaky``, ``@owner-<handle>`` and ``@until-YYYY-MM-DD`` (health.py).
Tags are read from the test's head (its title and options, up to its body) and from a file-level
``const NAME = { tag: [...] }`` that the head names, so

    const GA = { tag: ["@ga-regression", "@ga-area-primary", "@story-US-ONB-001"] };
    test("E09-TC-A01 password step ...", GA, async ({ page }) => { ... });

is one pack test. Playwright's ``grep`` matches the same tags at run time, so the configs' project
(``grep: /@ga-regression/``) and this reader select the same tests. Playwright also greps a
``test.describe`` title, which this reader does not read, so pack tags (``@ga-*``, ``@story-*``)
on a describe title are forbidden (``describe_tags``, a health finding): tag each test. Stdlib
only.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GA_TAG = "@ga-regression"
#: The report areas (BQ-02). `state-matrix` is reserved for E49-Q04's subset (BQ-11).
AREAS = (
    "primary",
    "multi",
    "rules",
    "alerts-journal",
    "replay",
    "admin",
    "state-matrix",
    "shell",
)
#: The two lanes and the package each one's specs live in (BQ-03).
APPS = {"web-chromium": "apps/web", "electron": "apps/desktop"}
STORY_RE = re.compile(r"^#### (US-[A-Z]+-\d+) — (.+?) · (Must(?:/Should)?|Should|Could)\b", re.M)

_TOKEN = re.compile(r"(?<![\w@/])@[A-Za-z][\w.-]*")
_CALL = re.compile(r"(?<![.\w$])test(?:\.(fixme|skip|fail|slow|only))?\s*\(\s*([\"'`])")
_DESCRIBE = re.compile(r"(?<![.\w$])test\.describe(?:\.\w+)?\s*\(\s*([\"'`])")
#: Tags that select or attribute pack tests; Playwright would read them from a describe title.
PACK_TAG = re.compile(r"^@(?:ga-|story-)")
_HEAD_END = re.compile(r"\basync\b|=>|;")
_TAG_CONST = re.compile(r"\bconst\s+([A-Z_][A-Z0-9_]*)\s*=\s*\{\s*tag\s*:\s*\[([^\]]*)\]", re.S)
_IDENT = re.compile(r"\b[A-Z_][A-Z0-9_]*\b")
_IMPORT = re.compile(r"\bimport\s+(?:type\s+)?([^;]*?)\s+from\s+[\"']([^\"']+)[\"']", re.S)


@dataclass(frozen=True)
class SpecTest:
    """One `test(...)` call site and the tags it carries."""

    lane: str
    path: str  # repo-relative, POSIX
    line: int
    tags: tuple[str, ...]
    modifier: str | None  # fixme | skip | fail | slow | only | None

    @property
    def in_pack(self) -> bool:
        return GA_TAG in self.tags

    @property
    def stub(self) -> bool:
        """A `test.fixme` stub runs nothing, so it covers no story."""
        return self.modifier == "fixme"

    @property
    def areas(self) -> tuple[str, ...]:
        return tuple(t.removeprefix("@ga-area-") for t in self.tags if t.startswith("@ga-area-"))

    @property
    def stories(self) -> tuple[str, ...]:
        return tuple(t.removeprefix("@story-") for t in self.tags if t.startswith("@story-"))

    @property
    def flaky(self) -> bool:
        return "@flaky" in self.tags

    def tag_value(self, prefix: str) -> str | None:
        found = [t.removeprefix(prefix) for t in self.tags if t.startswith(prefix)]
        return found[0] if len(found) == 1 else None

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


def tokens(text: str) -> list[str]:
    return [t.rstrip(".-") for t in _TOKEN.findall(text)]


def tag_consts(source: str) -> dict[str, tuple[str, ...]]:
    return {m.group(1): tuple(tokens(m.group(2))) for m in _TAG_CONST.finditer(source)}


def _literal_end(source: str, start: int, quote: str) -> int:
    """Index just past the string or template literal opening at `start` (escapes, `${...}`)."""
    i = start + 1
    while i < len(source):
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if quote == "`" and source.startswith("${", i):
            depth, i = 1, i + 2
            while i < len(source) and depth:
                depth += {"{": 1, "}": -1}.get(source[i], 0)
                i += 1
            continue
        if c == quote:
            return i + 1
        i += 1
    return len(source)


def scan_source(source: str, path: str, lane: str) -> list[SpecTest]:
    consts = tag_consts(source)
    found: list[SpecTest] = []
    for m in _CALL.finditer(source):
        title_end = _literal_end(source, m.end() - 1, m.group(2))
        end = _HEAD_END.search(source, title_end)
        head = source[m.start() : end.start() if end else len(source)]
        tags = set(tokens(head))
        for ident in _IDENT.findall(head):
            tags.update(consts.get(ident, ()))
        line = source.count("\n", 0, m.start()) + 1
        found.append(SpecTest(lane, path, line, tuple(sorted(tags)), m.group(1)))
    return found


def describe_tags(source: str) -> list[tuple[int, list[str]]]:
    """`(line, pack tags)` for each `test.describe` title carrying a pack tag."""
    out = []
    for m in _DESCRIBE.finditer(source):
        title = source[m.end() - 1 : _literal_end(source, m.end() - 1, m.group(1))]
        found = [t for t in tokens(title) if PACK_TAG.match(t)]
        if found:
            out.append((source.count("\n", 0, m.start()) + 1, found))
    return out


def imports(source: str) -> list[tuple[str, str]]:
    """`(imported clause, module specifier)` for each static import of a file."""
    return [(m.group(1), m.group(2)) for m in _IMPORT.finditer(source)]


def spec_files(root: Path, lane: str) -> Iterator[Path]:
    e2e = root / APPS[lane] / "e2e"
    yield from sorted(e2e.rglob("*.spec.ts"))


def scan(root: Path = REPO_ROOT) -> list[SpecTest]:
    found: list[SpecTest] = []
    for lane in APPS:
        for file in spec_files(root, lane):
            rel = file.relative_to(root).as_posix()
            found += scan_source(file.read_text(encoding="utf-8"), rel, lane)
    return found


def pack_files(tests: list[SpecTest], lane: str) -> list[str]:
    """The lane's spec files holding at least one runnable pack test, relative to its package."""
    prefix = APPS[lane] + "/"
    return sorted(
        {t.path.removeprefix(prefix) for t in tests if t.lane == lane and t.in_pack and not t.stub}
    )


def stories(root: Path = REPO_ROOT) -> dict[str, tuple[str, str]]:
    """Every story heading in docs/plan/11-user-stories.md: id -> (title, priority)."""
    text = (root / "docs/plan/11-user-stories.md").read_text(encoding="utf-8")
    return {m.group(1): (m.group(2), m.group(3)) for m in STORY_RE.finditer(text)}


def must_stories(root: Path = REPO_ROOT) -> dict[str, str]:
    """The Must stories (a `Must/Should` heading counts as Must): id -> title."""
    return {k: title for k, (title, prio) in stories(root).items() if prio.startswith("Must")}
