"""E07-D01 (#166) audit: the operator content model for storage telemetry and the StorageUsage review.

Stdlib only, offline by default (`python3 -I -B`). It reads the spec, the hand-off, the pins file
and `14` from the working tree and every cited file AS TEXT at the merge-base with `origin/main`
(`git show`); it runs no repository code but the stdlib-only calendar module (`calendar_cv.sprint_range`).
Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by branch name. PR-1 mode: the spec is absent at the
merge-base; the diff may touch only the four own files and add one pointer line to `14`.
Post-merge mode: the spec ships at the merge-base; every merged table row stands unchanged.
The ruling is read from section R by content: all twenty rows `PENDING` with a `<!-- BQ-nn -->`
marker left for every question, or all twenty carrying the ruling stamp with no marker left; in
the stamped state the spec also states the text-only line (BQ-17) with the Penpot page name and
id exactly as the E16-D04 spec gives them.

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the spec or the hand-off.
- [G02-AUDIT] every `<!-- audit:kind:key=value -->` marker is a key the tool computes, equals
  the recomputed value and stands right after its visible value; independent counts agree.
- [G03-CITE] every cited endpoint resolves at the base to a non-blank line; its pin matches.
- [G04-PINS] the pins file and the cited endpoints match both ways.
- [G05-ANCHOR] every name is cited at its own definition line, in the shape of its kind; the
  field and enum sets equal the schema's; every `storage.*` key is a deck key or a section 12
  key; a key cited beside a line stands on it.
- [G06-FIELDS] the 13 fields equal the schema, the model and the report builder, in order; every
  decision names a real field or a gap row and an owner of the action from the ruled set; the
  matrix agrees with the decisions; every field answers a decision or has an accepted exception.
- [G07-STATES] every state has a label, a consequence sentence from the deck or a section 12
  string, a unit slot and an owner; the level words equal the schema's four values.
- [G08-SCRIPT] every reading-script row has a host from the region map, the region's own
  politeness, a rate from the ruled vocabulary and a quoted string standing on its cited lines;
  a row that names a level change carries the headline string of every level it names.
- [G09-FINDINGS] every F row has a severity from the scale, an owner and a target from the ruled
  sets, the `G-T2`, `Focus` and `Rate` cells and a reason; the hold sentence agrees.
- [G10-IDS] the ids of each family are unique and in order; counts exclude the separator.
- [G11-HYGIENE] no lane-private word, URL, local path, uuid, closing keyword or hex colour.
- [G12-NOPATH] no path, connection string or credential shape in any example, string or prose
  of the spec and the hand-off (code spans excluded, except in the decision, state, empty-state
  and reading-script rows).
- [G13-RULED] the ruling state is whole: pending with every marker, or stamped with none.
- [G14-SCOPE] the changed paths are the own files and `14` only.
- [G15-POINTER] `14` differs from the base by exactly the one pointer line, inside SCR-142.
- [G16-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G17-COPY] section 12 keys are unique, owned by E07-D01 and absent from the deck; every
  italic string equals a section 12 row; no deck string is restated.
- [G18-T2] section 10.4 states the T2 rule and every T2 row names its key, verb and components.
- [G19-RECON] every `exists` name stands on a cited line; every `absent` name is found nowhere.
- [G20-UNITS] every number a unit rule shows carries its unit; the rules cover the ruled set.
- [G21-HANDOFF] the hand-off's ids, matrix and gap rows equal the spec's.
- [G22-CAL] the sprint labels equal the tickets' and the dates the calendar's.
- [G23-EMPTY] every empty, error and stale row has a rate from the ruled vocabulary, a source
  cell that cites a resolvable line at the base and a words rule that names a key or a string.
- [G24-PROSE] every double-quoted string of section 7, 8 or 9 of 10 or more characters stands
  verbatim on a line cited beside it, or in the ticket's own text, or sits in a PROPOSED row.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` writes the
computed values into the slots (`--online` asks `gh` for the parent states); `--self-test`
applies one mutation per gate to an in-memory copy and passes only when each adds FAILs of its
gate's code and the base run is clean; `--repin-ruled` rewrites the pins file and is its only writer.

Usage: python3 -I -B docs/design/_tools/e07_d01_storage_model_audit.py [--check] [--json]
       [--fill] [--online] [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import dataclasses
import datetime
import functools
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E07/E07-D01.md"
HAND_REL = "docs/design/E07/E07-D01-handoff.md"
TOOL_REL = "docs/design/_tools/e07_d01_storage_model_audit.py"
PINS_REL = "docs/design/_tools/e07_d01_ruled_pins.txt"
P14_REL = "docs/plan/14-screens-catalogue.md"
OWN = {SPEC_REL, HAND_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
BQ_BASE = "2026a56ff48b4900eb2fe2c79888750202914f5e"  # where the BQ list read every cite
REPO = "CandleViewer/CandleViewer"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
POINTER_MARK = "**Content model (E07-D01):**"
POINTER_ENTRY = "SCR-142"
TICKET_REL = "docs/plan/backlog/E07.json"
TICKET_KEY = "E07-D01"
OWNER_ACTIONS = ("the Owner", "the system")
PARENTS = {
    "E07-T01": 121,
    "E07-T05": 225,
    "E16-D04": 372,
    "E16-S04": 486,
    "E07-X01": 172,
}
TICKET_SPRINTS = {
    "s02": "E07-D01",
    "s03": "E07-D02",
    "s08": "E16-S04",
    "s09": "E16-D07",
}

PLAN = {
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": P14_REL,
    "15": "docs/plan/15-component-catalogue.md",
    "20": "docs/plan/20-architecture.md",
    "21": "docs/plan/21-database-schema.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "24": "docs/plan/24-internal-schemas.md",
}
SVC = "services/api/candleviewer/"
KEYS: dict[str, str] = {
    **PLAN,
    "D04": "docs/design/E16/E16-D04.md",
    "D02E": "docs/design/E16/E16-D02.md",
    "D06E": "docs/design/E16/E16-D06.md",
    "D11": "docs/design/E12/E12-D11.md",
    "E08D12": "docs/design/E08/E08-D12.md",
    "E17-D02": "docs/design/E17/E17-D02.md",
    "MOD": SVC + "recorder/models.py",
    "BUD": SVC + "recorder/budget.py",
    "RMET": SVC + "recorder/metrics.py",
    "USG": SVC + "storage/retention/usage.py",
    "RPT": SVC + "api/recording_reports.py",
    "RPR": SVC + "storage/retention/reaper.py",
    "ERR": SVC + "storage/errors.py",
    "EXP": SVC + "storage/cold/exporter.py",
    "OBS": SVC + "storage/cold/observability.py",
    "MET": SVC + "observability/metrics_catalogue.py",
    "RUN": "docs/ops/runbooks/recorder-rolloff.md",
    "CAL": CAL_REL,
}
KEY_RE = "|".join(sorted(map(re.escape, KEYS), key=len, reverse=True))
CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`(?: (?:§[\d.]+|US-REC-\d+|SR-\d+))? ?:(?P<a>\d+)(?:[–-](?P<b>\d+))?"
    r"(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
SLOT = re.compile(r"\{\{([A-Z0-9]+):([\w.-]+)\}\}")
AUDIT = re.compile(r"<!-- audit:([\w.:-]+)=([^>]*?) -->")
BQ_MARK = re.compile(r"<!-- BQ-(\d\d) -->")
QUOTE = re.compile(r'"([^"]*)"')
ITALIC = re.compile(r'(?<![*_])[*_]"([^"]*)"[*_](?![*_])')
TICK = re.compile(r"`([^`]+)`")
TICKET_TOKEN = re.compile(
    r"\bT (?:Context|Scope|OOS|AC\d|Tech|Test|Sec|a11y|Perf|Obs|DoD|Brief|Adapt)\b"
)
LEVEL_ROW = re.compile(r"level change to (\d)(?: or (\d))?")

SEVERITIES = ("Blocking", "Major", "Minor", "Info")
RATE_UNITS = "change|sample|entry|press|episode|focus"
RATE = re.compile(
    rf"^(?:never|on demand|n/a|once per (?:{RATE_UNITS})|≤ \d+ per \d+ s per (?:{RATE_UNITS}))$"
)
G_T2 = re.compile(r"^(?:n/a|T2 · (?:2a|2b|sentence)|validity|availability)$")
FOCUS = re.compile(r"^(?:n/a|(?:kept|moves to|restored to|returns to) · \S.*)$")
AREAS = "backend-platform|recorder-replay|auth-rbac|frontend-platform"
OWNER_TOKEN = rf"`(?:E\d\d-[TDSXQ]\d\d|\d\d) · area/(?:{AREAS})`"
OWNER = re.compile(rf"^{OWNER_TOKEN}(?:, {OWNER_TOKEN})*$")
TARGET_TOKEN = r"`(?:E07-D02|E16-S04|E16-Q05|E16-D07)`(?: \(#\d+\))?"
TARGET = re.compile(rf"^{TARGET_TOKEN}(?:; {TARGET_TOKEN})*$")
# rot13 keeps the private list out of plain text; underscores stand for spaces.
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn "
    "cer-nhgu ucr-jbexre znva-bepurfgengbe"
)
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile("|".join("/" + w + "/" for w in ("home", "mnt", "tmp")))
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
HEX_COLOUR = re.compile(r"#[0-9a-fA-F]{6}\b")
COLOUR_WORD = re.compile(
    r"\b(?:red|green|amber|yellow|orange|blue|grey|gray|colou?r|tone|icon)\b",
    re.IGNORECASE,
)
UNIT = r"(?:GB/day|MB/day|GB|MB|TB|%|days?|UTC|s)\b|%"
# The no-path rules of section 9.4: the one pattern list, carried here for E07-D02 to import.
NOPATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an absolute POSIX path", re.compile(r"(?<![\w.:/-])/[\w.-]+/[\w./-]*")),
    ("a Windows drive path", re.compile(r"\b[A-Za-z]:[\\/]")),
    ("a home path", re.compile(r"(?<![\w])~/")),
    ("a parent-relative path", re.compile(r"\.\./")),
    (
        "a connection-string scheme",
        re.compile(r"\b(?:postgres|postgresql|questdb|redis)://"),
    ),
    ("a connection pair", re.compile(r"\b(?:host|user|password|dbname)=")),
    ("a user:secret@host form", re.compile(r"\b\w+:[^\s@/:]+@[\w.-]+")),
    ("a token-shaped value", re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b")),
)
Findings = list[tuple[str, str]]
RUN_ERRORS = (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError, StopIteration)


# --------------------------------------------------------------------------------------- git


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    return out.stdout if out.returncode == 0 else ""


@functools.cache
def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip()


@functools.cache
def show(rev: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    return out.stdout if out.returncode == 0 else None


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def gh_state(num: int) -> str:
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/issues/{num}", "--jq", ".state"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    word = out.stdout.strip()
    if out.returncode != 0 or word not in ("open", "closed"):
        raise ValueError(f"gh could not read #{num}")
    return word


# ----------------------------------------------------------------------------------- parsing


def heading_level(line: str) -> int:
    m = re.match(r"(#{1,6}) ", line)
    return len(m[1]) if m else 0


def section(text: str, prefix: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lvl = heading_level(line)
        if lvl and line[lvl + 1 :].startswith(prefix):
            out = []
            for nxt in lines[i + 1 :]:
                n = heading_level(nxt)
                if n and n <= lvl:
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def is_sep(line: str) -> bool:
    return bool(re.match(r"^\|\s*:?-{3,}", line))


def table_lines(block: str) -> list[list[str]]:
    """Every body row of every table in a block: header and separator lines excluded."""
    out: list[list[str]] = []
    head = True
    for ln in block.split("\n"):
        if not ln.startswith("|"):
            head = True
            continue
        if is_sep(ln):
            head = False
            continue
        if not head:
            out.append(cells(ln))
    return out


def rows(text: str, pattern: str) -> list[list[str]]:
    """Body rows whose first cell matches a pattern, in document order."""
    pat = re.compile(rf"^(?:{pattern})$")
    return [r for r in table_lines(text) if pat.match(r[0])]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def plain(s: str) -> str:
    return norm(s).replace("{", "").replace("}", "")


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cite_spans(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in CITE.finditer(text):
        a = int(m["a"])
        out.append((m["key"], a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((m["key"], x, int(mm[2]) if mm[2] else x))
    return out


def endpoints(*texts: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for text in texts:
        for key, a, b in cite_spans(text):
            out.add((key, a))
            out.add((key, b))
    return out


def parse_pins(pins: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in pins.split("\n"):
        m = re.fullmatch(rf"({KEY_RE}):(\d+) ([0-9a-f]{{16}})", ln.strip())
        if m:
            out[(m[1], int(m[2]))] = m[3]
    return out


# ------------------------------------------------------------------------------------ context


@dataclasses.dataclass
class Ctx:
    spec: str
    hand: str
    pins: str
    tool: str
    p14: str
    p14_base: str
    changed: list[str]
    merged_spec: str | None
    base: str
    base_date: datetime.date
    states: dict[str, str]

    def text(self, key: str) -> str:
        return show(self.base, KEYS[key]) or ""

    def lines(self, key: str) -> list[str]:
        return self.text(key).split("\n")

    def base_line(self, key: str, n: int) -> str | None:
        lines = self.lines(key) if key in KEYS and show(self.base, KEYS[key]) else []
        return lines[n - 1] if 0 < n <= len(lines) else None

    def span(self, key: str, a: int, b: int) -> str:
        return " ".join(self.base_line(key, n) or "" for n in range(a, b + 1))


def _states_from_markers(*texts: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for text in texts:
        for m in AUDIT.finditer(text):
            if m[1].startswith("state:"):
                out[m[1][6:]] = m[2]
    return out


def frozen_base(merged_spec: str | None, mb: str) -> str:
    """PR-1: the merge-base. Post-merge: the base the merged spec recorded in its own
    `audit:sha:base` marker (the base its pins were read at), never the merge commit or moving main.
    """
    if merged_spec is None:
        return mb
    for m in AUDIT.finditer(merged_spec):
        if m[1] == "sha:base" and re.fullmatch(r"[0-9a-f]{40}", m[2]):
            probe = subprocess.run(
                ["git", "cat-file", "-e", m[2] + "^{commit}"],
                cwd=ROOT,
                check=False,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if probe.returncode == 0:
                return m[2]
    return mb


def build_ctx(online: bool = False) -> Ctx:
    mb = merge_base()
    merged_spec = show(mb, SPEC_REL)
    base = frozen_base(merged_spec, mb)
    spec, hand = read(SPEC_REL), read(HAND_REL)
    changed = [
        ln.strip()
        for ln in (
            git("diff", "--name-only", mb).split("\n")
            + git("ls-files", "--others", "--exclude-standard").split("\n")
        )
        if ln.strip()
    ]
    date_txt = git("show", "-s", "--format=%cs", base).strip()
    states = _states_from_markers(spec, hand)
    if online:
        states = {k: gh_state(n) for k, n in PARENTS.items()}
    return Ctx(
        spec=spec,
        hand=hand,
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        p14=read(P14_REL),
        p14_base=show(base, P14_REL) or "",
        changed=sorted(set(changed)),
        merged_spec=merged_spec,
        base=base,
        base_date=datetime.date.fromisoformat(date_txt),
        states=states,
    )


# --------------------------------------------------------------------------- source parsing


def schema_fields(ctx: Ctx) -> list[tuple[str, int, str]]:
    """`StorageUsage` top-level fields of `22`: (name, line, the field's own block of text)."""
    lines = ctx.lines("22")
    start = next(i for i, ln in enumerate(lines) if ln == "    StorageUsage:")
    end = next(i for i in range(start + 1, len(lines)) if re.match(r"^    \w", lines[i]))
    tops = [i for i in range(start, end) if re.match(r"^        \w+:", lines[i])]
    out = []
    for k, i in enumerate(tops):
        stop = tops[k + 1] if k + 1 < len(tops) else end
        name = lines[i].strip().split(":")[0]
        out.append((name, i + 1, "\n".join(lines[i:stop])))
    return out


def model_fields(ctx: Ctx) -> list[tuple[str, int]]:
    lines = ctx.lines("MOD")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("class StorageUsage("))
    out = []
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("class "):
            break
        m = re.match(r"^    (\w+): ", lines[i])
        if m:
            out.append((m[1], i + 1))
    return out


def builder_fields(ctx: Ctx) -> list[tuple[str, int]]:
    lines = ctx.lines("BUD")
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "return StorageUsage(")
    out = []
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == ")" and not lines[i].startswith(" " * 13):
            break
        m = re.match(r"^            (\w+)=", lines[i])
        if m:
            out.append((m[1], i + 1))
    return out


def enum_values(block: str) -> list[str]:
    m = re.search(r"enum: \[([^\]]*)\]", block)
    return [v.strip() for v in m[1].split(",")] if m else []


def enums(ctx: Ctx) -> dict[str, str]:
    blocks = {n: b for n, _, b in schema_fields(ctx)}
    tier = re.search(r"tier: \{[^}]*enum: \[([^\]]*)\]", blocks["tiers"])
    out = {n: enum_values(blocks[n]) for n in ("level", "write_gate", "write_gate_reason")}
    out["tier"] = [v.strip() for v in tier[1].split(",")] if tier else []
    return {k: " · ".join(v) for k, v in out.items()}


def fixture(ctx: Ctx) -> dict[str, Any]:
    txt = ctx.text("22")
    i = txt.index("operationId: getStorageUsage")
    block = txt[i : txt.index('"401"', i)]
    flat = re.sub(r"\s+", " ", block[block.index("value:") :])
    out: dict[str, Any] = {}
    for name in (
        "disk_total_bytes",
        "disk_used_bytes",
        "disk_free_bytes",
        "projected_full_at",
        "daily_growth_bytes",
        "cap_bytes",
        "level",
        "write_gate",
        "write_gate_reason",
        "accelerate_retention",
        "generated_at",
    ):
        m = re.search(rf"\b{name}: (\"[^\"]*\"|[\w.:-]+)", flat)
        if not m:
            raise ValueError(f"the example holds no {name}")
        out[name] = m[1].strip('"')
    out["tiers"] = re.findall(r"tier: (\w+), used_bytes: (\d+), retention_days: (\w+)", flat)
    out["symbols"] = re.findall(
        r"symbol: (\w+), used_bytes: (\d+), daily_growth_bytes: (\d+), pinned: (\w+)",
        flat,
    )
    return out


def gb(n: float) -> str:
    return f"{n / 1e9:,.1f}"


def fmt_values(ctx: Ctx) -> dict[str, str]:
    fx = fixture(ctx)
    cap, total, used_all = int(fx["cap_bytes"]), int(fx["disk_total_bytes"]), 0
    for tier, used, _ in fx["tiers"]:
        if tier in ("questdb", "parquet"):
            used_all += int(used)
    full = datetime.datetime.fromisoformat(fx["projected_full_at"])
    sample = datetime.datetime.fromisoformat(fx["generated_at"])
    top = max(fx["symbols"], key=lambda s: int(s[1]))
    return {
        "used_gb": gb(used_all),
        "budget_used_gb": gb(used_all),
        "cap_gb": gb(cap),
        "budget_pct": f"{100 * used_all / cap:.1f}",
        "volume_pct": f"{100 * int(fx['disk_used_bytes']) / total:.1f}",
        "growth_gb_day": f"{int(fx['daily_growth_bytes']) / 1e9:.2f}",
        "sym_mb_day": f"{int(top[2]) / 1e6:.0f}",
        "runway_days": str((full - sample).days),
        "full_date": full.date().isoformat(),
        "sample_time": sample.strftime("%H:%M:%S"),
        "symbols_sum_gb": gb(sum(int(s[1]) for s in fx["symbols"])),
    }


def obs_values(ctx: Ctx) -> dict[str, str]:
    fx = fixture(ctx)
    out = {
        "disk_total_bytes": f"{fx['disk_total_bytes']} bytes",
        "disk_used_bytes": f"{fx['disk_used_bytes']} bytes",
        "disk_free_bytes": f"{fx['disk_free_bytes']} bytes",
        "projected_full_at": fx["projected_full_at"],
        "daily_growth_bytes": f"{fx['daily_growth_bytes']} bytes per day",
        "cap_bytes": f"{fx['cap_bytes']} bytes",
        "level": fx["level"],
        "write_gate": fx["write_gate"],
        "write_gate_reason": fx["write_gate_reason"],
        "accelerate_retention": fx["accelerate_retention"],
        "generated_at": fx["generated_at"],
    }
    out["tiers"] = f"{len(fx['tiers'])} rows: " + ", ".join(
        f"{t} {u} bytes" for t, u, _ in fx["tiers"]
    )
    out["symbols"] = f"{len(fx['symbols'])} rows: " + ", ".join(
        f"{s} {u} bytes" for s, u, _, _ in fx["symbols"]
    )
    return out


@functools.cache
def calendar() -> Any:
    path = ROOT / CAL_REL
    spec = importlib.util.spec_from_file_location("calendar_cv", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import calendar_cv")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ticket_sprint(ctx: Ctx, key: str) -> int:
    epic = key.split("-")[0]
    data = json.loads(show(ctx.base, f"docs/plan/backlog/{epic}.json") or "[]")
    items = data if isinstance(data, list) else data.get("tickets", [])
    for it in items:
        if it.get("key") == key:
            m = re.search(r"(\d+)", str(it.get("sprint", "")))
            if m:
                return int(m[1])
    raise ValueError(f"no sprint for {key}")


def sha12(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------------------- the numbers


def spec_rows(spec: str, head: str, family: str) -> list[list[str]]:
    return rows(section(spec, head), family)


def added_14(ctx: Ctx) -> list[str]:
    base = set(ctx.p14_base.split("\n"))
    new = [ln for ln in ctx.p14.split("\n") if ln not in base]
    if ctx.merged_spec is not None:  # later tickets add their own lines to `14` after the base
        new = [ln for ln in new if POINTER_MARK in ln]
    return new


def cited_files(ctx: Ctx) -> list[str]:
    keys = {k for k, _, _ in cite_spans(ctx.spec)} | {k for k, _, _ in cite_spans(ctx.hand)}
    return sorted(KEYS[k] for k in keys)


def compute(ctx: Ctx) -> dict[str, str]:
    spec, v = ctx.spec, {}
    v["sha:base"] = ctx.base
    dl = spec_rows(spec, "3. ", r"DL-\d\d")
    st = spec_rows(spec, "7. ", r"ST-\d\d")
    f_rows = spec_rows(spec, "14. ", r"F-\d\d")
    names = table_lines(section(spec, "11. "))
    gaps = spec_rows(spec, "15. ", r"D0[14]-G\d+")
    v["count:fields"] = str(len(schema_fields(ctx)))
    v["count:dl"] = str(len(dl))
    v["count:dl.no-field"] = str(sum(1 for r in dl if re.match(r"(?:none|not in)\b", norm(r[2]))))
    v["count:st"] = str(len(st))
    v["count:st.no-field"] = str(sum(1 for r in st if norm(r[3]).startswith("none")))
    v["count:em"] = str(len(spec_rows(spec, "9. ", r"EM-\d\d")))
    rs = spec_rows(spec, "13. ", r"RS-\d\d")
    v["count:rs"] = str(len(rs))
    v["count:rs.proposed"] = str(sum(1 for r in rs if "PROPOSED" in r[2]))
    v["count:f"] = str(len(f_rows))
    for sev in SEVERITIES:
        v[f"count:f.{sev.lower()}"] = str(sum(1 for r in f_rows if r[1] == sev))
    v["count:c"] = str(len(spec_rows(spec, "15. ", r"C-[a-z]")))
    v["count:g"] = str(len(gaps))
    v["count:g.d01"] = str(sum(1 for r in gaps if r[0].startswith("D01-")))
    v["count:hr"] = str(len(re.findall(r"(?m)^- \*\*HR-\d+\*\*", spec)))
    v["count:names"] = str(sum(len(TICK.findall(r[0])) for r in names if TICK.search(r[0])))
    v["count:names.absent"] = str(
        sum(len(TICK.findall(r[0])) for r in names if norm(r[2]).startswith("absent"))
    )
    v["count:pointer-lines"] = str(len(added_14(ctx)))
    v["count:an"] = str(len(spec_rows(spec, "1. ", r"AN-\d\d")))
    v["count:t2"] = str(len(spec_rows(spec, "10. ", r"T2-\d\d")))
    v["count:cold"] = str(sum(1 for r in st if int(r[0][3:]) <= 8))
    v["count:gates"] = str(len(GATES))
    moved = git("diff", "--name-only", BQ_BASE, ctx.base, "--", *cited_files(ctx)).split()
    v["count:bq-moved"] = str(len(moved))
    v["date:base"] = ctx.base_date.isoformat()
    cal = calendar()
    for tag in TICKET_SPRINTS:
        start, end = cal.sprint_range(int(tag[1:]))
        v[f"cal:{tag}.start"], v[f"cal:{tag}.end"] = start.isoformat(), end.isoformat()
    s02_end = cal.sprint_range(2)[1]
    v["count:days-late"] = str((ctx.base_date - s02_end).days)
    v["hash:d04-ladder"] = sha12(section(ctx.text("D04"), "1.4 "))
    v["hash:24-ladder"] = sha12(ctx.span("24", 4228, 4232))
    for name, val in enums(ctx).items():
        v[f"enum:{name}"] = val
    for name, val in fmt_values(ctx).items():
        v[f"fmt:{name}"] = val
    for name, val in obs_values(ctx).items():
        v[f"obs:{name}"] = val
    for name, val in ctx.states.items():
        v[f"state:{name}"] = val
    return v


# ------------------------------------------------------------------------------------ gates


def g_filled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for name, text in (("spec", ctx.spec), ("hand-off", ctx.hand)):
        for m in SLOT.finditer(text):
            f.append(("G01-FILLED", f"{name}: slot {m[0]} is not filled"))


def g_audit(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for name, text in (("spec", ctx.spec), ("hand-off", ctx.hand)):
        for m in AUDIT.finditer(text):
            key, val = m[1], m[2]
            if key not in vals:
                f.append(
                    (
                        "G02-AUDIT",
                        f"{name}: marker {key!r} is not a key the tool computes",
                    )
                )
                continue
            if vals[key] != val:
                f.append(
                    (
                        "G02-AUDIT",
                        f"{name}: {key}: the marker says {val!r}, the tool {vals[key]!r}",
                    )
                )
            if not text[: m.start()].rstrip().rstrip("`").endswith(val):
                f.append(
                    (
                        "G02-AUDIT",
                        f"{name}: {key}: the visible value before it is not {val!r}",
                    )
                )
    for key, val in ctx.states.items():
        if key in PARENTS and val not in ("open", "closed"):
            f.append(("G02-AUDIT", f"state {key}: {val!r} is not open or closed"))
    # two independent counts, not the helpers `compute` uses: one regex over the whole text
    for fam, key in (
        ("DL", "dl"),
        ("ST", "st"),
        ("EM", "em"),
        ("RS", "rs"),
        ("F", "f"),
    ):
        n = len(re.findall(rf"(?m)^\| {fam}-\d\d\s*\|", ctx.spec))
        shown = re.search(rf"audit:count:{re.escape(key)}=(\d+)", ctx.spec)
        if shown and int(shown[1]) != n:
            f.append(("G02-AUDIT", f"{key}: the file holds {n} rows, the marker {shown[1]}"))


def g_cite(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = parse_pins(ctx.pins)
    for key, n in sorted(endpoints(ctx.spec, ctx.hand)):
        line = ctx.base_line(key, n)
        if line is None or not line.strip():
            f.append(
                (
                    "G03-CITE",
                    f"{key}:{n} does not resolve to a non-blank line at the base",
                )
            )
        elif (key, n) in pins and pins[(key, n)] != line_hash(line):
            f.append(
                (
                    "G03-CITE",
                    f"{key}:{n} moved: its pin no longer matches the base line",
                )
            )


def g_pins(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = set(parse_pins(ctx.pins))
    ends = endpoints(ctx.spec, ctx.hand)
    for k, n in sorted(ends - pins):
        f.append(("G04-PINS", f"{k}:{n} is cited but not pinned"))
    for k, n in sorted(pins - ends):
        f.append(("G04-PINS", f"{k}:{n} is pinned but no longer cited"))


def deck(ctx: Ctx) -> dict[str, tuple[int, str]]:
    """The E16-D04 copy deck: key -> (line, the string cell)."""
    out: dict[str, tuple[int, str]] = {}
    on = False
    for i, ln in enumerate(ctx.lines("D04"), 1):
        if ln.startswith("## "):
            on = ln.startswith("## 14.")
        m = re.match(r"^\| `([\w.]+)` +\| (.*?) *\|?$", ln)
        if on and m:
            out.setdefault(m[1], (i, m[2]))
    return out


def ctx_deck(ctx: Ctx) -> dict[str, tuple[int, str]]:
    return deck(ctx)


def s12_rows(ctx: Ctx) -> list[list[str]]:
    return spec_rows(ctx.spec, "12. ", r"`storage\.[\w.]+`")


def field_of(token: str) -> str:
    return re.split(r"[\[.]", token)[0]


AN_SHAPES: dict[str, Callable[[str, str], str]] = {
    "22": lambda n, k: rf"^\s+{n}:",
    "MOD": lambda n, k: rf"^\s+{n}:" if k != "enum" else "TierName",
    "BUD": lambda n, k: rf"\b{n}=" if k.startswith("field") else rf"^\s+{n}\b",
}


def an_pattern(kind: str, key: str, n: str) -> str:
    if kind in ("field", "field and enum", "enum") and key in AN_SHAPES:
        return AN_SHAPES[key](n, kind)
    if kind == "code":
        return rf'code = "{n}"'
    if kind == "metric":
        return rf'^\s+"{n}",\s*$' if key == "MET" else rf"^{n} = (?:Counter|Gauge|Histogram)\("
    if kind == "constant":
        return rf"^{n} = " if key == "RPR" else rf"^\s+{n}\b"
    if kind == "setting":
        return rf"\| `{n}` +\|"
    if kind == "event name":
        return rf"`{n}`"
    if kind == "copy key":
        return rf"^\| `{n}` +\|"
    return "(?!)"


def g_anchor(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    an = spec_rows(ctx.spec, "1. ", r"AN-\d\d")
    en = enums(ctx)
    seen_fields: list[str] = []
    for r in an:
        name = r[1].strip("`")
        kind, values = r[2], re.sub(r"\s*<!--.*?-->", "", r[3], flags=re.DOTALL).strip()
        spans = cite_spans(r[4])
        if not spans:
            f.append(("G05-ANCHOR", f"{r[0]}: no definition cite"))
        for key, a, b in spans:
            for n in {a, b}:
                line = ctx.base_line(key, n) or ""
                if not re.search(an_pattern(kind, key, re.escape(name)), line):
                    f.append(
                        (
                            "G05-ANCHOR",
                            f"{r[0]}: {key}:{n} is not the definition line of {name}",
                        )
                    )
        if kind.startswith("field"):
            seen_fields.append(name)
            if {k for k, _, _ in spans} != {"22", "MOD", "BUD"}:
                f.append(("G05-ANCHOR", f"{r[0]}: a field needs its 22, MOD and BUD lines"))
        if name in en and values != en[name]:
            f.append(
                (
                    "G05-ANCHOR",
                    f"{r[0]}: the values read {values!r}, the schema {en[name]!r}",
                )
            )
    schema = [n for n, _, _ in schema_fields(ctx)]
    if seen_fields != schema:
        f.append(
            (
                "G05-ANCHOR",
                f"the field rows {seen_fields} differ from the schema {schema}",
            )
        )
    dk = deck(ctx)
    s12 = {r[0].strip("`") for r in s12_rows(ctx)}
    events = {r[1].strip("`") for r in an if r[2] == "event name"}
    for text in (ctx.spec, ctx.hand):
        for tok in TICK.findall(text):
            if re.fullmatch(r"storage\.[\w]+(?:\.[\w]+)*", tok) and tok not in {
                *dk,
                *s12,
                *events,
            }:
                f.append(
                    (
                        "G05-ANCHOR",
                        f"`{tok}` is neither a deck key nor a section 12 key",
                    )
                )
        for m in re.finditer(r"`(storage\.[\w.]+)`(?: \(|, )`D04`:(\d+)(?:[–-](\d+))?", text):
            lo, hi = int(m[2]), int(m[3] or m[2])
            if m[1] not in ctx.span("D04", lo, hi).replace("`", ""):
                f.append(("G05-ANCHOR", f"`{m[1]}` does not stand on D04:{lo}–{hi}"))
    for key, a, b in cite_spans(ctx.spec) + cite_spans(ctx.hand):
        if key == "ERR":
            for n in {a, b}:
                if not re.match(
                    r'^(?:class Storage\w+\(|    code = "STORAGE_[A-Z_]+")',
                    ctx.base_line(key, n) or "",
                ):
                    f.append(("G05-ANCHOR", f"ERR:{n} is neither a class nor a code line"))


def header_of(block: str) -> list[str]:
    """The header cells of the first table in a block whose first two cells are Id and Field."""
    for ln in block.split("\n"):
        if ln.startswith("|") and cells(ln)[:2] == ["Id", "Field"]:
            return cells(ln)
    raise ValueError("no Id | Field header")


def matrix(ctx: Ctx) -> tuple[list[str], list[list[str]]]:
    block = section(ctx.spec, "4. ")
    head = header_of(block)
    return head, rows(block, r"CK-\d\d")


def g_fields(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    schema = [n for n, _, _ in schema_fields(ctx)]
    head, mat = matrix(ctx)
    names = [field_of(TICK.findall(r[1])[0]) for r in mat]
    if names != schema:
        f.append(("G06-FIELDS", f"the matrix lists {names}, the schema {schema}"))
    if [n for n, _ in model_fields(ctx)] != schema:
        f.append(("G06-FIELDS", "the model's fields differ from the schema's"))
    if [n for n, _ in builder_fields(ctx)] != schema:
        f.append(("G06-FIELDS", "the report builder's fields differ from the schema's"))
    dl_cols = [i for i, h in enumerate(head) if re.fullmatch(r"DL-\d\d", h)]
    dls = {r[0]: r for r in spec_rows(ctx.spec, "3. ", r"DL-\d\d")}
    marked: set[str] = set()
    for i in dl_cols:
        dl = head[i]
        ticked = {names[k] for k, r in enumerate(mat) if r[i] == "✓"}
        marked |= ticked
        named = (
            {field_of(t) for t in TICK.findall(dls[dl][2]) if field_of(t) in schema}
            if dl in dls
            else set()
        )
        if ticked != named:
            f.append(
                (
                    "G06-FIELDS",
                    f"{dl}: the matrix marks {sorted(ticked)}, the row names {sorted(named)}",
                )
            )
    for dl, r in dls.items():
        if dl in [head[i] for i in dl_cols]:
            continue
        named = {field_of(t) for t in TICK.findall(r[2]) if field_of(t) in schema}
        if named or not re.search(r"D0[14]-C?G\d+", " ".join(r[2:])):
            f.append(
                (
                    "G06-FIELDS",
                    f"{dl}: a row with no matrix column must name a gap row and no field",
                )
            )
    for dl, r in dls.items():
        if r[5] not in OWNER_ACTIONS:
            f.append(("G06-FIELDS", f"{dl}: owner of the action {r[5]!r} is outside the ruled set"))
    exc = {field_of(TICK.findall(r[1])[0]) for r in spec_rows(ctx.spec, "4. ", r"X-\d")}
    for n in schema:
        if n not in marked and n not in exc:
            f.append(("G06-FIELDS", f"{n} answers no decision and has no accepted exception"))


def g_states(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    dk = deck(ctx)
    s12 = {r[0].strip("`") for r in s12_rows(ctx)}
    st = spec_rows(ctx.spec, "7. ", r"ST-\d\d")
    for r in st:
        label, consequence, unit, owner = r[1], r[4], r[5], r[6]
        keys = [k for k in TICK.findall(consequence) if k.startswith("storage.")]
        if not label.strip() or not unit.strip() or not any(k in dk or k in s12 for k in keys):
            f.append(
                (
                    "G07-STATES",
                    f"{r[0]}: a state needs a label, a deck or section 12 sentence, a unit slot",
                )
            )
        if not OWNER.match(owner):
            f.append(("G07-STATES", f"{r[0]}: owner {owner!r} is outside the ruled set"))
        if COLOUR_WORD.search(f"{label} {consequence} {unit}"):
            f.append(("G07-STATES", f"{r[0]}: a colour or tone word in a state cell"))
    levels = set(enums(ctx)["level"].split(" · "))
    got: set[str] = set()
    for r in [x for x in st if int(x[0][3:]) <= 4]:
        m = re.search(r"`level` (\d)", r[2])
        if m:
            got.add(m[1])
            if f"storage.headline.{m[1]}" not in r[4]:
                f.append(
                    (
                        "G07-STATES",
                        f"{r[0]}: the level {m[1]} row does not carry its headline key",
                    )
                )
    if got != levels:
        f.append(
            (
                "G07-STATES",
                f"the level words {sorted(got)} differ from the schema's {sorted(levels)}",
            )
        )


def region_map(ctx: Ctx) -> dict[str, str]:
    return {r[0]: r[2] for r in spec_rows(ctx.spec, "13. ", r"RG-\d\d")}


def g_script(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    rg = region_map(ctx)
    s12 = {norm(q) for r in s12_rows(ctx) for q in ITALIC.findall(r[1])}
    for r in spec_rows(ctx.spec, "13. ", r"RS-\d\d"):
        if len(r) != 7:
            f.append(("G08-SCRIPT", f"{r[0]}: {len(r)} cells, not 7"))
            continue
        _, _, spoken, source, host, polite, rate = r
        if host not in rg or rg[host] != polite:
            f.append(
                (
                    "G08-SCRIPT",
                    f"{r[0]}: host {host!r} with {polite!r} is not a region of the map",
                )
            )
        if not RATE.match(rate):
            f.append(("G08-SCRIPT", f"{r[0]}: rate {rate!r} is outside the ruled vocabulary"))
        italics = ITALIC.findall(spoken)
        quotes = QUOTE.findall(ITALIC.sub("", spoken))
        if not quotes and not italics and not spoken.startswith("nothing is announced"):
            f.append(
                (
                    "G08-SCRIPT",
                    f"{r[0]}: no quoted string and no 'nothing is announced'",
                )
            )
        hay = plain(" ".join(ctx.span(k, a, b) for k, a, b in cite_spans(source)))
        for q in quotes:
            pq = plain(q)
            ok = (
                pq in hay
                if len(pq) >= 10
                else bool(re.search(rf"(?<!\w){re.escape(pq)}(?!\w)", hay))
            )
            if not ok:
                f.append(
                    (
                        "G08-SCRIPT",
                        f"{r[0]}: {q[:40]!r} stands on no line the row cites",
                    )
                )
        for q in italics:
            if norm(q) not in s12:
                f.append(("G08-SCRIPT", f"{r[0]}: an italic string equals no section 12 row"))
        for q in [*quotes, *italics]:
            bare = re.sub(r"\{[^}]*\}", "", q)
            for m in re.finditer(r"\d+(?:\.\d+)?", bare):
                if not re.match(
                    r"\s?(?:%|GB|MB|TB|s\b|days?\b|rows\b|msg/s|min\b)", bare[m.end() :]
                ):
                    f.append(("G08-SCRIPT", f"{r[0]}: the number {m[0]} has no unit"))
            if COLOUR_WORD.search(q):
                f.append(("G08-SCRIPT", f"{r[0]}: a colour word in a spoken string"))
        if (polite == "none") != (host == "RG-03"):
            f.append(("G08-SCRIPT", f"{r[0]}: politeness none and host RG-03 go together"))
        lv = LEVEL_ROW.search(r[1])
        for n in [x for x in (lv[1], lv[2]) if x] if lv else []:
            line, cell = ctx_deck(ctx).get(f"storage.headline.{n}", (0, ""))
            head = QUOTE.findall(cell)[:1]
            if not head or plain(head[0]) not in plain(" ".join(quotes)):
                f.append(("G08-SCRIPT", f"{r[0]}: the level {n} headline string is not spoken"))
            if not any(k == "D04" and a <= line <= b for k, a, b in cite_spans(source)):
                f.append(
                    ("G08-SCRIPT", f"{r[0]}: the level {n} headline line :{line} is not cited")
                )


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "14. ")
    fr = rows(sec, r"F-\d\d")
    for r in fr:
        if len(r) != 10:
            f.append(("G09-FINDINGS", f"{r[0]}: {len(r)} cells, not 10"))
            continue
        checks = (
            (r[1] in SEVERITIES, f"severity {r[1]!r}"),
            (bool(OWNER.match(r[4])), f"owner {r[4]!r}"),
            (bool(TARGET.match(r[5])), f"target {r[5]!r}"),
            (bool(G_T2.match(r[6])), f"G-T2 {r[6]!r}"),
            (bool(FOCUS.match(r[7])), f"Focus {r[7]!r}"),
            (bool(RATE.match(r[8])), f"Rate {r[8]!r}"),
            (len(r[9]) > 8 and r[9] not in ("—", "-"), "a reason"),
        )
        for ok, what in checks:
            if not ok:
                f.append(("G09-FINDINGS", f"{r[0]}: {what} is outside the ruled set"))
    blocking = sum(1 for r in fr if r[1] == "Blocking")
    if blocking and "not armed" in sec:
        f.append(
            (
                "G09-FINDINGS",
                "a Blocking row stands while the hold sentence says not armed",
            )
        )
    if not blocking and "not armed" not in sec:
        f.append(("G09-FINDINGS", "no Blocking row stands but the hold sentence is missing"))
    for fam, head, owner_i, target_i in (
        (r"C-[a-z]", "15. ", 3, None),
        (r"D0[14]-G\d+", "15. ", 2, 3),
        (r"Q-\d\d", "15. ", 3, None),
        (r"A-\d", "15. ", 4, None),
    ):
        for r in spec_rows(ctx.spec, head, fam):
            if not OWNER.match(r[owner_i]):
                f.append(
                    (
                        "G09-FINDINGS",
                        f"{r[0]}: owner {r[owner_i]!r} is outside the ruled set",
                    )
                )
            if target_i and not TARGET.match(r[target_i]):
                f.append(
                    (
                        "G09-FINDINGS",
                        f"{r[0]}: target {r[target_i]!r} is outside the ruled set",
                    )
                )


FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("3. ", r"DL-(\d\d)", "DL"),
    ("4. ", r"CK-(\d\d)", "CK"),
    ("4. ", r"X-(\d)", "X"),
    ("7. ", r"ST-(\d\d)", "ST"),
    ("8. ", r"U-(\d\d)", "U"),
    ("9. ", r"EM-(\d\d)", "EM"),
    ("10. ", r"T2-(\d\d)", "T2"),
    ("13. ", r"RG-(\d\d)", "RG"),
    ("13. ", r"RS-(\d\d)", "RS"),
    ("14. ", r"F-(\d\d)", "F"),
    ("15. ", r"Q-(\d\d)", "Q"),
    ("15. ", r"A-(\d)", "A"),
    ("1. ", r"AN-(\d\d)", "AN"),
    ("R. ", r"BQ-(\d\d)", "BQ"),
)


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for head, pat, fam in FAMILIES:
        nums = []
        for r in spec_rows(ctx.spec, head, pat):
            m = re.fullmatch(pat, r[0])
            if m:
                nums.append(int(m[1]))
        if nums != list(range(1, len(nums) + 1)) or not nums:
            f.append(("G10-IDS", f"{fam}: the ids {nums} are not 1..{len(nums)} in order"))
    letters = [r[0][2:] for r in spec_rows(ctx.spec, "15. ", r"C-[a-z]")]
    if letters != [chr(97 + i) for i in range(len(letters))]:
        f.append(("G10-IDS", f"C: the ids {letters} are not a.. in order"))
    gaps = [r[0] for r in spec_rows(ctx.spec, "15. ", r"D0[14]-G\d+")]
    if len(gaps) != len(set(gaps)):
        f.append(("G10-IDS", "a gap id is repeated"))
    hr = [int(n) for n in re.findall(r"(?m)^- \*\*HR-(\d+)\*\*", ctx.spec)]
    if hr != list(range(1, len(hr) + 1)):
        f.append(("G10-IDS", f"HR: the ids {hr} are not 1..{len(hr)} in order"))
    m = re.search(r"DL-01\.\.DL-(\d\d)", ctx.spec)
    if not m or int(m[1]) != len(spec_rows(ctx.spec, "3. ", r"DL-\d\d")):
        f.append(("G10-IDS", "the range DL-01..DL-nn does not equal the decision rows"))
    sep = [r[0] for r in table_lines(ctx.spec) if set(r[0]) <= set("-: ")]
    if sep:
        f.append(("G10-IDS", "a separator row is read as data"))


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for name, text in (
        ("spec", ctx.spec),
        ("hand-off", ctx.hand),
        ("tool", ctx.tool),
        ("pins", ctx.pins),
    ):
        if name == "spec" and page_ref(ctx)[1]:
            text = text.replace(page_ref(ctx)[1], "")
        low = text.lower()
        for word in BANNED:
            if word in low:
                f.append(("G11-HYGIENE", f"{name}: a word from the private list"))
        for pat, what in (
            (URL, "a URL"),
            (UUID, "a uuid"),
            (LOCAL_PATH, "a local path"),
        ):
            m = pat.search(text)
            if m:
                f.append(("G11-HYGIENE", f"{name}: {what} {m[0][:24]!r}"))
    for name, text in (("spec", ctx.spec), ("hand-off", ctx.hand)):
        if CLOSING.search(text):
            f.append(("G11-HYGIENE", f"{name}: a closing keyword before an issue number"))
        if HEX_COLOUR.search(text):
            f.append(
                (
                    "G11-HYGIENE",
                    f"{name}: a hex colour stands where a token name is due",
                )
            )


def nopath_hits(s: str) -> list[str]:
    return [what for what, pat in NOPATH_PATTERNS if pat.search(s)]


def g_nopath(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    strings: list[tuple[str, str]] = []
    for r in s12_rows(ctx):
        strings += [(r[0], q) for q in ITALIC.findall(r[1]) + QUOTE.findall(r[1])]
    for r in spec_rows(ctx.spec, "13. ", r"RS-\d\d"):
        strings += [(r[0], q) for q in ITALIC.findall(r[2]) + QUOTE.findall(r[2])]
    fx = fixture(ctx)
    strings += [("fixture", str(s[0])) for s in fx["symbols"]]
    strings += [("fixture", str(t[0])) for t in fx["tiers"]]
    strings += [("fixture", str(fx["write_gate_reason"]))]
    strings += [("example", v) for k, v in vals.items() if k.startswith(("obs:", "fmt:"))]
    for where, s in strings:
        for what in nopath_hits(s):
            f.append(("G12-NOPATH", f"{where}: {what} in {s[:40]!r}"))
    for name, text in (("spec", ctx.spec), ("hand-off", ctx.hand)):
        prose = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        for sha in (ctx.base, BQ_BASE):
            prose = prose.replace(sha, "")
        prose = re.sub(r"`[^`\n]*`", "", prose)
        for i, ln in enumerate(prose.split("\n"), 1):
            for what in nopath_hits(ln):
                f.append(("G12-NOPATH", f"{name} line {i}: {what} in prose {ln.strip()[:40]!r}"))
    for head in ("3. ", "7. ", "9.1 ", "13.1 "):
        for r in table_lines(section(ctx.spec, head)):
            for what in nopath_hits(re.sub(r"<!--.*?-->", "", " ".join(r), flags=re.DOTALL)):
                f.append(("G12-NOPATH", f"{r[0]}: {what} in a table cell"))


@functools.cache
def ticket_text(base: str) -> str:
    """Every string of the E07-D01 ticket twin at the base, normalised and lower-cased."""
    raw = show(base, TICKET_REL)
    if raw is None:
        return ""
    out: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            out.append(o)

    for t in json.loads(raw):
        if isinstance(t, dict) and t.get("key") == TICKET_KEY:
            walk(t)
    return plain(" ".join(out)).lower()


def g_empty(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in spec_rows(ctx.spec, "9. ", r"EM-\d\d"):
        if len(r) != 5:
            f.append(("G23-EMPTY", f"{r[0]}: {len(r)} cells, not 5"))
            continue
        _, state, source, words, rate = r
        if not state.strip():
            f.append(("G23-EMPTY", f"{r[0]}: the state cell is empty"))
        if not RATE.match(rate):
            f.append(("G23-EMPTY", f"{r[0]}: rate {rate!r} is outside the ruled vocabulary"))
        spans = cite_spans(source)
        if not spans:
            f.append(("G23-EMPTY", f"{r[0]}: the source cell cites no shipped line"))
        for k, a, b in spans:
            if any(not (ctx.base_line(k, n) or "").strip() for n in (a, b)):
                f.append(("G23-EMPTY", f"{r[0]}: {k}:{a} does not resolve to a non-blank line"))
        if not (
            re.search(r"`storage\.[\w.]+`", words)
            or QUOTE.search(words)
            or ITALIC.search(words)
            or "sentence" in words
        ):
            f.append(("G23-EMPTY", f"{r[0]}: the words rule names no key and no string"))


def g_prose(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    ticket = ticket_text(ctx.base)
    for head in ("7. ", "8. ", "9. "):
        for ln in section(ctx.spec, head).split("\n"):
            line = ITALIC.sub("", ln)
            hay = plain(" ".join(ctx.span(k, a, b) for k, a, b in cite_spans(ln))).lower()
            for q in QUOTE.findall(line):
                pq = plain(q).lower()
                if len(pq) < 10 or pq in hay or "PROPOSED" in ln:
                    continue
                if TICKET_TOKEN.search(norm(ln)) and pq in ticket:
                    continue
                f.append(
                    ("G24-PROSE", f"section {head.strip()}: {q[:40]!r} stands on no cited line")
                )


RULED_STATUS = re.compile(
    r"^RULED \(orchestrator, \d{4}-\d\d-\d\d, #166 ruling of record \d{10}\)$"
)


def page_ref(ctx: Ctx) -> tuple[str, str]:
    """The E16-D04 Penpot page name and id, read from the page line of its spec at the base."""
    ln = ctx.base_line("D04", 5) or ""
    m = re.search(r"`([^`]+)` · id `(" + UUID.pattern + r")`", ln)
    return (m[1], m[2]) if m else ("", "")


def text_only_line(ctx: Ctx) -> str:
    name, pid = page_ref(ctx)
    if not name:
        return ""
    return (
        "text-only by the orchestrator's ruling of 2026-11-01 (#166 comment 6551871804): an operator "
        "content model and a review of StorageUsage's built surface; the E16-D04 page "
        f"(name + id only, `D04`:5: `{name}`, id `{pid}`) is the drawn reference it reviews; "
        "no new frames."
    )


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R. ")
    br = rows(sec, r"BQ-\d\d")
    listed = [r[0] for r in br]
    if listed != [f"BQ-{n:02d}" for n in range(1, 21)]:
        f.append(("G13-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-20"))
    pending = [r[-1] == "PENDING" for r in br]
    stamped = [bool(RULED_STATUS.match(r[-1])) for r in br]
    marks = {m[1] for m in BQ_MARK.finditer(ctx.spec)}
    hand_marks = {m[1] for m in BQ_MARK.finditer(ctx.hand)}
    if all(pending):
        for n in range(1, 21):
            if f"{n:02d}" not in marks:
                f.append(("G13-RULED", f"BQ-{n:02d}: no marker is left in the spec"))
        if "**Ruling status: PENDING.**" not in ctx.spec:
            f.append(("G13-RULED", "the pending status line is missing"))
    elif all(stamped):
        want = text_only_line(ctx)
        if not want or ctx.spec.replace("**", "").lower().count(want.lower()) < 3:
            f.append(("G13-RULED", "the BQ-17 text-only line is not stated in full three times"))
        if marks or hand_marks:
            f.append(("G13-RULED", "a BQ marker is left after the ruling"))
        if "PENDING" in ctx.spec:
            f.append(("G13-RULED", "the word PENDING is left after the ruling"))
    else:
        f.append(("G13-RULED", "section R is neither all pending nor all stamped"))
    for m in re.finditer(r"RULED (BQ-\d\d)((?:, BQ-\d\d)*)", ctx.spec):
        for bq in [m[1], *re.findall(r"BQ-\d\d", m[2])]:
            if bq not in listed:
                f.append(("G13-RULED", f"a stamp names {bq}, which section R does not list"))


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for p in ctx.changed:
        if p not in OWN and p != P14_REL:
            f.append(("G14-SCOPE", f"{p} is outside the edit set"))


def g_pointer(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    wt, base = ctx.p14.split("\n"), ctx.p14_base.split("\n")
    added = added_14(ctx)
    # post-merge, later tickets tick and reword `14`; only the pointer line is this pack's
    if ctx.merged_spec is None and [ln for ln in base if ln not in set(wt)]:
        f.append(("G15-POINTER", "a line of `14` was removed or changed"))
    if ctx.merged_spec is None and len(added) != 1:
        f.append(("G15-POINTER", f"{len(added)} line(s) added to `14`, not one"))
    form = f"- {POINTER_MARK} [E07-D01.md](../design/E07/E07-D01.md) (E07-D01; "
    for ln in added:
        if not ln.startswith(form) or not ln.endswith("owner approval pending)."):
            f.append(
                (
                    "G15-POINTER",
                    f"an added `14` line is not the pointer line: {ln[:40]!r}",
                )
            )
    entry, last, found = "", "", []
    for ln in wt + ["## end"]:
        if ln.startswith(("### ", "## ")):
            if entry == POINTER_ENTRY and last:
                found.append(last)
            m = re.match(r"### (SCR-\d+) ", ln)
            entry, last = (m[1] if m else ""), ""
        elif ln.strip() and entry == POINTER_ENTRY:
            last = ln
    marks = [ln for ln in wt if POINTER_MARK in ln]
    if len(marks) != 1 or not found or POINTER_MARK not in found[0]:
        f.append(("G15-POINTER", f"{POINTER_ENTRY} must end with exactly one pointer line"))


# The only edits a merged row may carry: #5265 (E16-S01) merged after this pack did, so the two
# rows that said "open PR" now say it landed. Each pair is exact; nothing else may move.
_BQ10_OLD = (
    "open PR #5265 (E16-S01) is the PR that lands the alignment; no C row about the Manager "
    "seed; the cites are re-pinned by content after it merges;"
)
_BQ10_NEW = (
    "#5265 (E16-S01) landed the alignment; no C row about the Manager seed; "
    "the cites to the aligned files are by content;"
)
AMENDMENTS = (
    (_BQ10_OLD, _BQ10_NEW),
    (
        "open PR #5265 (E16-S01) lands the alignment in `22`, `04`, `21` and the seed",
        "#5265 (E16-S01) landed the alignment in `22`, `04`, `21` and the seed",
    ),
    ("cites re-pinned after #5265 merges", "cites to those files are by content"),
)


def squash(row: str) -> str:
    return re.sub(r"\s+", " ", row).strip()


def amended(row: str) -> str:
    for old, new in AMENDMENTS:
        row = row.replace(old, new)
    return row


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    squashed = {squash(ln) for ln in now}  # prettier re-pads the table cells of an amended row
    for ln in ctx.merged_spec.split("\n"):
        if (
            ln.startswith("|")
            and not is_sep(ln)
            and ln not in now
            and squash(amended(ln)) not in squashed
        ):
            f.append(("G16-FREEZE", f"a merged row changed: {ln[:48]!r}"))


def g_copy(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    dk = deck(ctx)
    rws = s12_rows(ctx)
    keys = [r[0].strip("`") for r in rws]
    if len(keys) != len(set(keys)) or not keys:
        f.append(("G17-COPY", "a section 12 key is repeated or the table is empty"))
    strings = set()
    for r in rws:
        key = r[0].strip("`")
        if key in dk:
            f.append(("G17-COPY", f"`{key}` is a deck key: it is cited, never restated"))
        if "PROPOSED, owner E07-D01" not in r[2]:
            f.append(("G17-COPY", f"`{key}`: a PROPOSED string needs its owner E07-D01"))
        if not ITALIC.search(r[1]):
            f.append(("G17-COPY", f"`{key}`: the string is not italic and quoted"))
        strings |= {norm(q) for q in ITALIC.findall(r[1])}
    for m in ITALIC.finditer(ctx.spec + "\n" + ctx.hand):
        if norm(m[1]) not in strings:
            f.append(
                (
                    "G17-COPY",
                    f"an italic string equals no section 12 row: {m[1][:36]!r}",
                )
            )
    sec = "\n".join(" ".join(r) for r in rws)
    for key, (_, cell) in dk.items():
        for q in QUOTE.findall(cell):
            if len(q) >= 20 and norm(q) in norm(sec):
                f.append(
                    (
                        "G17-COPY",
                        f"a section 12 row restates the deck string of `{key}`",
                    )
                )


def g_t2(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "10.4 ")
    for need in (
        'aria-disabled="true"',
        "aria-describedby",
        "CMP-079",
        "CMP-019",
        "`lock`",
        "decorative={false}",
        '"Not available"',
        "at mount",
    ):
        if need not in sec:
            f.append(("G18-T2", f"section 10.4 does not state {need}"))
    left = sec.replace('aria-disabled="true"', "").replace("(never `disabled`)", "")
    if re.search(r"\bdisabled\b", left):
        f.append(
            (
                "G18-T2",
                "section 10.4 uses the word disabled outside the never-`disabled` rule",
            )
        )
    dk = deck(ctx)
    for r in spec_rows(ctx.spec, "10. ", r"T2-\d\d"):
        key = (TICK.findall(r[3]) or [""])[0]
        if key not in dk:
            f.append(("G18-T2", f"{r[0]}: key {key!r} is not a deck key"))
        if r[4] != '"change recording"' or '"change recording"' not in ctx.span("D04", 168, 168):
            f.append(("G18-T2", f"{r[0]}: the §3.2 verb is not the one D04 quotes"))
        if "CMP-079" not in r[5] or "CMP-019" not in r[5]:
            f.append(("G18-T2", f"{r[0]}: the components must name CMP-079 and CMP-019"))
    for cmp_id, n in (("CMP-079", 887), ("CMP-019", 238), ("CMP-044", 516)):
        if cmp_id not in (ctx.base_line("15", n) or ""):
            f.append(("G18-T2", f"{cmp_id} is not the heading at 15:{n}"))


def git_grep(base: str, name: str, *paths: str) -> list[str]:
    out = subprocess.run(
        ["git", "grep", "-l", "-F", "-e", name, base, "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    return out.stdout.split() if out.returncode == 0 else []


def g_recon(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in table_lines(section(ctx.spec, "11. ")):
        if len(r) != 4:
            f.append(("G19-RECON", f"a name row has {len(r)} cells, not 4"))
            continue
        names, state = TICK.findall(r[0]), norm(r[2])
        if not OWNER.match(r[3]):
            f.append(("G19-RECON", f"{names}: owner {r[3]!r} is outside the ruled set"))
        spans = cite_spans(r[1])
        if state.startswith("exists"):
            hay = " ".join(ctx.span(k, a, b) for k, a, b in spans)
            for n in names:
                if n not in hay:
                    f.append(("G19-RECON", f"`{n}` stands on no line its row cites"))
        elif state.startswith("absent"):
            for n in names:
                hits = git_grep(ctx.base, n, "services", KEYS["22"])
                if n == "pg_migration_pending":
                    hits += git_grep(ctx.base, n, "docs/plan", ":!docs/plan/backlog")
                if hits:
                    f.append(
                        (
                            "G19-RECON",
                            f"`{n}` is called absent but stands in {hits[0][-40:]}",
                        )
                    )
        else:
            f.append(("G19-RECON", f"{names}: state {state!r} is outside the vocabulary"))
    for code in (
        "STORAGE_TIER_UNAVAILABLE",
        "STORAGE_EXPORT_VERIFY_FAILED",
        "STORAGE_SCHEMA_DRIFT",
    ):
        for key in ("20", "22", "24"):
            if code in ctx.text(key):
                f.append(
                    (
                        "G19-RECON",
                        f"{code} stands in {key}: the claim that it does not is false",
                    )
                )


def g_units(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    urows = spec_rows(ctx.spec, "8. ", r"U-\d\d")
    for r in urows:
        ex = re.sub(r"\s*<!--.*?-->", "", r[3], flags=re.DOTALL)
        ex = re.sub(r"\d{4}-\d\d-\d\d|\d\d:\d\d:\d\d", "", ex)
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", ex):
            if not re.match(r"\s?(?:%|GB/day|MB/day|GB|MB|TB|days?\b|UTC|s\b|\))", ex[m.end() :]):
                f.append(("G20-UNITS", f"{r[0]}: the number {m[0]} carries no unit"))
    text = " ".join(" ".join(r) for r in urows)
    for need in (
        "GB/day",
        "MB/day",
        "No projection yet",
        "No limit",
        "UTC",
        "60 s",
    ):
        if need not in text:
            f.append(("G20-UNITS", f"the unit rules do not state {need!r}"))


def _marks(head: list[str], r: list[str]) -> dict[str, str]:
    return {h: r[i] for i, h in enumerate(head) if re.fullmatch(r"DL-\d\d", h)}


def g_handoff(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    head, mat = matrix(ctx)
    hblock = section(ctx.hand, "§A ")
    hhead = header_of(hblock)
    hmat = {r[0]: r for r in rows(hblock, r"CK-\d\d")}
    if sorted(hmat) != sorted(r[0] for r in mat):
        f.append(("G21-HANDOFF", "the hand-off checklist rows differ from the matrix"))
    for r in mat:
        if r[0] in hmat:
            a, b = _marks(head, r), _marks(hhead, hmat[r[0]])
            if {k: v for k, v in a.items() if k in b} != b or set(a) != set(b):
                f.append(
                    (
                        "G21-HANDOFF",
                        f"{r[0]}: the hand-off marks differ from the matrix",
                    )
                )
    ids: set[str] = set()
    for m in re.finditer(r"ST-(\d\d)(?:\.\.ST-(\d\d))?", ctx.hand):
        lo, hi = int(m[1]), int(m[2] or m[1])
        ids |= {f"ST-{n:02d}" for n in range(lo, hi + 1)}
    for r in spec_rows(ctx.spec, "7. ", r"ST-\d\d"):
        if r[0] not in ids:
            f.append(("G21-HANDOFF", f"the hand-off does not carry {r[0]}"))
    hg = {r[0]: r for r in rows(section(ctx.hand, "§D "), r"D0[14]-G\d+")}
    sg = {r[0]: r for r in spec_rows(ctx.spec, "15. ", r"D0[14]-G\d+")}
    if set(hg) != set(sg):
        f.append(("G21-HANDOFF", "the hand-off's gap rows differ from the spec's"))
    for k in set(hg) & set(sg):
        if hg[k][2] != sg[k][2] or hg[k][3] != sg[k][3]:
            f.append(("G21-HANDOFF", f"{k}: the owner or the target differs from the spec's"))
    pend = "Status: `PENDING`" in ctx.hand
    ruled = "Status: `RULED`" in ctx.hand
    if pend == ruled or pend != ("**Ruling status: PENDING.**" in ctx.spec):
        f.append(("G21-HANDOFF", "the hand-off's ruling status differs from the spec's"))


def g_cal(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for tag, key in TICKET_SPRINTS.items():
        if ticket_sprint(ctx, key) != int(tag[1:]):
            f.append(("G22-CAL", f"{key} is in sprint {ticket_sprint(ctx, key)}, not {tag}"))
    cal = calendar()
    if cal.sprint_range(2)[1] >= cal.sprint_range(3)[0]:
        f.append(("G22-CAL", "sprint 02 does not end before sprint 03 starts"))
    if ctx.base_date <= cal.sprint_range(3)[1] and "(past)" in ctx.spec:
        f.append(
            (
                "G22-CAL",
                "the spec calls sprint 03 past while the base date is inside it",
            )
        )
    if (
        "Sprint 01 = Friday 2026-09-25" not in ctx.spec
        or cal.SPRINT01_START.isoformat() != "2026-09-25"
    ):
        f.append(("G22-CAL", "the spec's sprint-01 date differs from the calendar's"))


GATES: list[tuple[str, Callable[[Ctx, dict[str, str], Findings], None]]] = [
    ("G01-FILLED", g_filled),
    ("G02-AUDIT", g_audit),
    ("G03-CITE", g_cite),
    ("G04-PINS", g_pins),
    ("G05-ANCHOR", g_anchor),
    ("G06-FIELDS", g_fields),
    ("G07-STATES", g_states),
    ("G08-SCRIPT", g_script),
    ("G09-FINDINGS", g_findings),
    ("G10-IDS", g_ids),
    ("G11-HYGIENE", g_hygiene),
    ("G12-NOPATH", g_nopath),
    ("G13-RULED", g_ruled),
    ("G14-SCOPE", g_scope),
    ("G15-POINTER", g_pointer),
    ("G16-FREEZE", g_freeze),
    ("G17-COPY", g_copy),
    ("G18-T2", g_t2),
    ("G19-RECON", g_recon),
    ("G20-UNITS", g_units),
    ("G21-HANDOFF", g_handoff),
    ("G22-CAL", g_cal),
    ("G23-EMPTY", g_empty),
    ("G24-PROSE", g_prose),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    f: Findings = []
    try:
        vals = compute(ctx)
    except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL
        return {}, [("G02-AUDIT", f"the numbers could not be computed: {type(e).__name__}: {e}")]
    for code, gate in GATES:
        try:
            gate(ctx, vals, f)
        except RUN_ERRORS as e:
            f.append((code, f"the gate could not run: {type(e).__name__}: {e}"))
    return vals, f


# ---------------------------------------------------------------------------------- writers


def fill(ctx: Ctx) -> tuple[str, str]:
    """The spec and the hand-off with every slot filled and every stale marker refreshed."""
    vals = compute(ctx)

    def slot(m: re.Match[str]) -> str:
        key = f"{m[1].lower()}:{m[2]}"
        return f"{vals[key]} <!-- audit:{key}={vals[key]} -->" if key in vals else m[0]

    def refresh(text: str) -> str:
        text = SLOT.sub(slot, text)
        for m in list(AUDIT.finditer(text)):
            key, old = m[1], m[2]
            if key in vals and old != vals[key]:
                text = text.replace(
                    f"{old} <!-- audit:{key}={old} -->",
                    f"{vals[key]} <!-- audit:{key}={vals[key]} -->",
                )
        return text

    return refresh(ctx.spec), refresh(ctx.hand)


def repin(ctx: Ctx) -> str:
    lines = [
        "# E07-D01 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e07_d01_storage_model_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec, ctx.hand), key=lambda x: (x[0], x[1])):
        lines.append(f"{key}:{n} {line_hash(ctx.base_line(key, n) or '')}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------- self-test


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"mutation anchor missing: {old[:48]!r}")
    return text.replace(old, new, 1)


def set_cell(text: str, row_id: str, index: int, value: str) -> str:
    out, done = [], False
    for ln in text.split("\n"):
        if not done and re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln):
            parts = re.split(r"(?<!\\)\|", ln)
            parts[index + 1] = f" {value} "
            ln, done = "|".join(parts), True
        out.append(ln)
    if not done:
        raise ValueError(f"mutation anchor missing: row {row_id}")
    return "\n".join(out)


def drop_row(text: str, row_id: str) -> str:
    lines = text.split("\n")
    keep = [ln for ln in lines if not re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln)]
    if len(keep) == len(lines):
        raise ValueError(f"mutation anchor missing: row {row_id}")
    return "\n".join(keep)


def on_spec(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    return lambda c: dataclasses.replace(c, spec=fn(c.spec))


def on_hand(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    return lambda c: dataclasses.replace(c, hand=fn(c.hand))


def zero_pin(prefix: str) -> Callable[[Ctx], Ctx]:
    def mutate(c: Ctx) -> Ctx:
        pins = re.sub(
            rf"^({prefix}:\d+) [0-9a-f]{{16}}$",
            r"\1 0000000000000000",
            c.pins,
            count=1,
            flags=re.MULTILINE,
        )
        return dataclasses.replace(c, pins=pins)

    return mutate


MUTATIONS: list[tuple[str, Callable[[Ctx], Ctx]]] = [
    ("G01-FILLED", on_spec(lambda t: t + "\n{{COUNT:dl}}\n")),
    ("G02-AUDIT", on_spec(lambda t: _swap(t, "audit:count:dl=10", "audit:count:dl=99"))),
    ("G02-AUDIT", on_spec(lambda t: drop_row(t, "DL-10"))),
    ("G02-AUDIT", on_spec(lambda t: _swap(t, "state:E16-S04=open", "state:E16-S04=merged"))),
    ("G03-CITE", zero_pin("22")),
    ("G03-CITE", on_spec(lambda t: _swap(t, "`D02E`:449,", "`D02E`:445,"))),
    ("G04-PINS", on_spec(lambda t: t + "\nSee `22` :1.\n")),
    (
        "G05-ANCHOR",
        on_spec(lambda t: set_cell(t, "AN-01", 4, "`22` :20109 · `MOD`:138 · `BUD`:536")),
    ),
    ("G05-ANCHOR", on_spec(lambda t: set_cell(t, "AN-45", 4, "`D04`:514"))),
    ("G05-ANCHOR", on_spec(lambda t: t + "\nSee `storage.invented_key`.\n")),
    ("G05-ANCHOR", on_spec(lambda t: drop_row(t, "AN-07"))),
    ("G06-FIELDS", on_spec(lambda t: drop_row(t, "CK-13"))),
    (
        "G06-FIELDS",
        on_spec(lambda t: set_cell(t, "DL-02", 2, "`level`, `write_gate`, `write_gate_reason`")),
    ),
    ("G07-STATES", on_spec(lambda t: set_cell(t, "ST-04", 1, ""))),
    ("G07-STATES", on_spec(lambda t: set_cell(t, "ST-02", 1, "Near limit (amber)"))),
    ("G07-STATES", on_spec(lambda t: set_cell(t, "ST-03", 2, "`level` 3; `accelerate_retention`"))),
    ("G08-SCRIPT", on_spec(lambda t: set_cell(t, "RS-05", 6, "whenever"))),
    ("G08-SCRIPT", on_spec(lambda t: set_cell(t, "RS-01", 4, "RG-09"))),
    (
        "G08-SCRIPT",
        on_spec(lambda t: _swap(t, '"Storage figures are stale"', '"Storage figures are old"')),
    ),
    ("G08-SCRIPT", on_spec(lambda t: set_cell(t, "RS-04", 2, "a tone"))),
    (
        "G08-SCRIPT",
        on_spec(
            lambda t: set_cell(
                t,
                "RS-01",
                2,
                '"Near limit · auto-record pauses in about {d} days · clears below {warn − 5} %"'
                ' and "Recording pauses before trading is affected."',
            )
        ),
    ),
    ("G08-SCRIPT", on_spec(lambda t: set_cell(t, "RS-01", 3, "`D04`:507, :513"))),
    ("G06-FIELDS", on_spec(lambda t: set_cell(t, "DL-01", 5, "the Intern"))),
    ("G09-FINDINGS", on_spec(lambda t: set_cell(t, "F-02", 1, "Severe"))),
    ("G09-FINDINGS", on_spec(lambda t: set_cell(t, "F-03", 4, "`an agent`"))),
    ("G09-FINDINGS", on_spec(lambda t: set_cell(t, "F-12", 9, "—"))),
    ("G09-FINDINGS", on_spec(lambda t: set_cell(t, "F-04", 8, "sometimes"))),
    ("G09-FINDINGS", on_spec(lambda t: set_cell(t, "F-11", 1, "Blocking"))),
    ("G10-IDS", on_spec(lambda t: set_cell(t, "ST-03", 0, "ST-02"))),
    ("G11-HYGIENE", on_spec(lambda t: t + "\n" + BANNED[8].upper() + "\n")),
    ("G11-HYGIENE", on_spec(lambda t: t + "\n#1a2b3c\n")),
    (
        "G12-NOPATH",
        on_spec(
            lambda t: _swap(
                t, "Choose a symbol to start", "Choose a symbol under /var/lib/data to start"
            )
        ),
    ),
    (
        "G12-NOPATH",
        on_spec(
            lambda t: _swap(
                t, "the next 60 s cycle", "the next 60 s cycle of postgres://db.internal/x"
            )
        ),
    ),
    (
        "G12-NOPATH",
        on_spec(lambda t: set_cell(t, "DL-03", 4, "read `/var/lib/data` in the report")),
    ),
    ("G23-EMPTY", on_spec(lambda t: set_cell(t, "EM-06", 4, "hourly"))),
    ("G23-EMPTY", on_spec(lambda t: set_cell(t, "EM-01", 4, "whenever"))),
    ("G23-EMPTY", on_spec(lambda t: set_cell(t, "EM-07", 2, "`symbols[]` is empty"))),
    ("G23-EMPTY", on_spec(lambda t: set_cell(t, "EM-02", 2, "the same 503"))),
    ("G23-EMPTY", on_spec(lambda t: set_cell(t, "EM-03", 3, "show it"))),
    (
        "G24-PROSE",
        on_spec(
            lambda t: _swap(
                t,
                'before trading is affected." (`storage.degradation`',
                'before trading is impacted." (`storage.degradation`',
            )
        ),
    ),
    (
        "G24-PROSE",
        on_spec(lambda t: _swap(t, 'is "that day is not dropped"', 'is "that day is skipped"')),
    ),
    (
        "G24-PROSE",
        on_spec(
            lambda t: _swap(t, "exempt from accelerated retention", "exempt from all retention")
        ),
    ),
    ("G13-RULED", on_spec(lambda t: t.replace("## R. ", "<!-- BQ-03 -->\n## R. ", 1))),
    ("G13-RULED", on_spec(lambda t: t.replace("f5d056cd", "f5d056ce"))),
    ("G13-RULED", on_spec(lambda t: t.replace("no new frames.", "new frames drawn.", 1))),
    (
        "G13-RULED",
        on_spec(
            lambda t: set_cell(
                t, "BQ-07", 3, "RULED (orchestrator, 2026-11-01, #166 ruling of record 1)"
            )
        ),
    ),
    ("G14-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/15-x.md"])),
    (
        "G15-POINTER",
        lambda c: dataclasses.replace(
            c, p14="\n".join(ln for ln in c.p14.split("\n") if POINTER_MARK not in ln)
        ),
    ),
    (
        "G16-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| KB-99 | a merged row since changed |\n"),
    ),
    (
        "G17-COPY",
        on_spec(lambda t: set_cell(t, "`storage.not_ready`", 0, "`storage.degradation`")),
    ),
    (
        "G17-COPY",
        on_spec(lambda t: _swap(t, "PROPOSED, owner E07-D01 (AC3)", "PROPOSED (AC3)")),
    ),
    ("G18-T2", on_spec(lambda t: set_cell(t, "T2-02", 5, "CMP-019 `lock`"))),
    (
        "G18-T2",
        on_spec(lambda t: _swap(t, "(never `disabled`)", "(never `disabled`), not disabled")),
    ),
    ("G19-RECON", on_spec(lambda t: set_cell(t, "`pg_migration_pending`", 2, "exists"))),
    (
        "G20-UNITS",
        on_spec(
            lambda t: _swap(
                t, "audit:fmt:volume_pct=30.1 --> % of", "audit:fmt:volume_pct=30.1 --> of"
            )
        ),
    ),
    ("G21-HANDOFF", on_hand(lambda t: set_cell(t, "CK-01", 2, ""))),
    ("G21-HANDOFF", on_hand(lambda t: drop_row(t, "D01-G3"))),
    (
        "G22-CAL",
        on_spec(
            lambda t: _swap(t, "Sprint 01 = Friday 2026-09-25", "Sprint 01 = Friday 2026-09-26")
        ),
    ),
]


def frozen_base_problems(ctx: Ctx) -> list[str]:
    """Post-merge cites freeze at the recorded base: a moved merge-base must not move them."""
    out: list[str] = []
    moved = "f" * 40  # stands for a main that has moved on since the pack merged
    if frozen_base(None, moved) != moved:
        out.append("PR-1 mode must read at the merge-base")
    if ctx.merged_spec is not None:
        want = ctx.base
        if frozen_base(ctx.merged_spec, moved) != want:
            out.append("post-merge mode follows the merge-base, not the recorded base")
        no_marker = ctx.merged_spec.replace("audit:sha:base=", "audit:sha:unused=")
        if frozen_base(no_marker, moved) != moved:
            out.append("post-merge mode with no recorded base must fall back, which G02 then fails")
        stale = re.sub(r"(audit:sha:base=)[0-9a-f]{40}", r"\g<1>" + "0" * 40, ctx.merged_spec)
        if frozen_base(stale, moved) != moved:
            out.append("an unresolvable recorded base was accepted")
    return out


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _, base = run(ctx)
    problems: list[str] = []
    if base:
        problems.append(f"the base run is not clean: {len(base)} FAIL(s)")
    before = {code for code, _ in base}
    passed = 0
    for code, mutate in MUTATIONS:
        try:
            _, got = run(mutate(ctx))
        except RUN_ERRORS as e:
            problems.append(f"{code}: the mutation could not apply: {e}")
            continue
        if any(c == code for c, _ in got) and code not in before:
            passed += 1
        else:
            problems.append(f"{code}: the mutation added no FAIL of its gate")
    if {code for code, _ in GATES} - {code for code, _ in MUTATIONS}:
        problems.append("a gate has no mutation")
    problems += frozen_base_problems(ctx)
    return passed, len(MUTATIONS), problems


# ------------------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL (a bare run does too)")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="write the computed values into the slots")
    ap.add_argument("--online", action="store_true", help="read the parent states with gh")
    ap.add_argument("--self-test", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    args = ap.parse_args(argv)
    ctx = build_ctx(online=args.online)
    mode = "post-merge" if ctx.merged_spec is not None else "PR-1"
    if args.repin_ruled:
        (ROOT / PINS_REL).write_text(repin(ctx), encoding="utf-8")
        print(f"pins rewritten: {len(endpoints(ctx.spec, ctx.hand))} cited endpoints")
        return 0
    if args.fill:
        spec, hand = fill(ctx)
        (ROOT / SPEC_REL).write_text(spec, encoding="utf-8")
        (ROOT / HAND_REL).write_text(hand, encoding="utf-8")
        print("spec and hand-off filled")
        return 0
    if args.self_test:
        passed, total, problems = self_test(ctx)
        for p in problems:
            print(f"SELF-TEST FAIL {p}")
        print(f"self-test: {passed}/{total} mutations caught; {len(GATES)} gates; mode {mode}")
        return 0 if passed == total and not problems else 1
    vals, f = run(ctx)
    if args.json:
        print(
            json.dumps(
                {"mode": mode, "base": ctx.base, "numbers": vals, "findings": f},
                indent=2,
            )
        )
    else:
        for code, msg in f:
            print(f"FAIL [{code}] {msg}")
        print(f"mode {mode}; base {ctx.base[:12]}; {len(GATES)} gates; FAIL {len(f)} / WARN 0")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
