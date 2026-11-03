#!/usr/bin/env python3
"""E42-Q06: the deferred ADMIN Musts are owned by E43/E44 (C1), and the record of it (C2).

E42 defers US-ADMIN-010 (the security posture panel) to E43 and US-ADMIN-012 (the live-trading
enablement gate) to E44, its attestation half in E43. A deferral holds only while its owners keep
the story to closure, so this reads the backlog offline and names every gap: an owner missing,
retired, no longer naming its story, off the R4 milestone or window (a design ticket: fewer than
DESIGN_AHEAD sprints before the story it serves), SCR-137 dropped from E43, an E42 story no longer
stating the deferral, or an owner epic not blocked by E42. `--snapshot` also requires each owner on
the board (`docs/plan/backlog/_tools/board_snapshot.py`'s file), open or closed as Done.
`--write-record` writes the record only on a pass, the same bytes for the same inputs.

Usage: python3 -I scripts/verify_deferred_must.py [--backlog DIR] [--snapshot FILE]
           [--write-record PATH --reviewer NAME --date YYYY-MM-DD] [--json]
Exit 0: every check passes; 1: a gap, each named; 2: usage, or an input that cannot be read.
Stdlib only: no network, no `gh`.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, astuple, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "docs" / "plan" / "backlog"
#: The publishing ledger under the backlog: each ticket's issue number, for the record only.
LEDGER = Path("_tools") / "published.json"


@dataclass(frozen=True)
class Deferral:
    """A Must story E42 defers: its owner epic, the tickets that own it, and the E42 story that
    states the deferral with what its body must name."""

    story: str
    epic: str
    tickets: tuple[str, ...]
    stand_in: str
    stated: tuple[str, ...]


DEFERRED: tuple[Deferral, ...] = (
    Deferral("US-ADMIN-010", "E43", ("E43-D01", "E43-S02"), "E42-S01", ("US-ADMIN-010", "E43-S02")),
    Deferral(
        "US-ADMIN-012",
        "E44",
        ("E44-T04", "E44-S01", "E43-S01"),
        "E42-S05",
        ("US-ADMIN-012", "E44-T04", "E44-S01", "E43-S01"),
    ),
)
DEFERRING_EPIC = "E42"
MILESTONE = "R4 Live enablement"
#: R4's sprints (`docs/plan/30-release-roadmap.md`).
WINDOW = (20, 22)
#: The design-ahead rule (`docs/plan/02-definition-of-ready-done.md`): a design ticket lands at
#: least this many sprints before the story it serves.
DESIGN_AHEAD = 2
CONSUMER: Mapping[str, str] = {"E43-D01": "E43-S02"}
SCREEN = "SCR-137"
SCREEN_TICKETS = ("E43-D01", "E43-S01", "E43-S02")
ESCALATION = "E42 cannot be signed off; escalate to the Owner as an R4 Must-coverage risk."
EXCEPTION = (
    "The contract's `setFeatureFlag` (`docs/plan/22-api-openapi.yaml`) sets `trading.live_enabled` "
    "to `true` only with `flags:write`, a `reason`, an `https` `evidence_url` and a fresh, "
    "single-use `live_enablement` step-up; E44-T04 owns the evidence binding. That gated path "
    "(CG-28) is an accepted residual until E44-T04 lands, as ruled on 2026-11-03. While it stands, "
    "a live order also needs the process setting `CV_TRADING_LIVE_ENABLED`, which is off by "
    "default, so the flag alone admits none. No E42 test completes a real `live_enablement` "
    "step-up; unit tests use an in-memory fake."
)
_SPRINT = re.compile(r"Sprint (\d{1,2})")
_TITLE = re.compile(r"\[(E\d{2}(?:-[A-Z]\d{2})?)\]")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

Ticket = Mapping[str, object]


class InputError(Exception):
    """An input that cannot be read: exit 2, never a pass."""


@dataclass(frozen=True, order=True)
class Gap:
    ticket: str
    check: str
    expected: str
    found: str

    def line(self) -> str:
        return f"GAP {self.ticket}: {self.check}: expected {self.expected}; found {self.found}"


@dataclass(frozen=True)
class Row:
    story: str
    epic: str
    ticket: str
    issue: str
    kind: str
    sprint: str
    milestone: str
    names_story: bool
    notes: str


def _text(item: Ticket, field: str) -> str:
    value = item.get(field)
    return value if isinstance(value, str) else ""


def _strings(item: Ticket, field: str) -> list[str]:
    value = item.get(field)
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _names(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _sprint(item: Ticket | None) -> int | None:
    found = None if item is None else _SPRINT.fullmatch(_text(item, "sprint"))
    return None if found is None else int(found.group(1))


def _owners() -> list[str]:
    return sorted({key for deferral in DEFERRED for key in deferral.tickets})


def _epics() -> list[str]:
    keys = [DEFERRING_EPIC, *(d.epic for d in DEFERRED), *_owners()]
    return sorted({key.split("-")[0] for key in keys})


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"{path.name}: {exc}") from exc


def load_backlog(backlog: Path) -> dict[str, Ticket]:
    """The tickets of each epic file the checks read, a ticket only from its own epic's file."""
    tickets: dict[str, Ticket] = {}
    for epic in _epics():
        data = _read_json(backlog / f"{epic}.json")
        if not isinstance(data, list):
            raise InputError(f"{epic}.json: not a list of tickets")
        for item in data:
            key = item.get("key") if isinstance(item, dict) else None
            if isinstance(key, str) and key.split("-")[0] == epic:
                tickets[key] = item
    return tickets


def _sprint_gaps(tickets: Mapping[str, Ticket], key: str, ticket: Ticket) -> list[Gap]:
    sprint, found = _sprint(ticket), _text(ticket, "sprint") or "none"
    consumer = CONSUMER.get(key)
    if consumer is None:
        if sprint is not None and WINDOW[0] <= sprint <= WINDOW[1]:
            return []
        return [Gap(key, "R4 window", f"Sprint {WINDOW[0]} to Sprint {WINDOW[1]}", found)]
    target = _sprint(tickets.get(consumer))
    if sprint is not None and target is not None and target - sprint >= DESIGN_AHEAD:
        return []
    expected = f"at least {DESIGN_AHEAD} sprints before {consumer}" + (
        "" if target is None else f" (Sprint {target}): Sprint {target - DESIGN_AHEAD} or earlier"
    )
    return [Gap(key, "design ahead", expected, found)]


def _owner_gaps(tickets: Mapping[str, Ticket], deferral: Deferral, key: str) -> list[Gap]:
    ticket = tickets.get(key)
    if ticket is None:
        epic_file = f"{key.split('-')[0]}.json"
        return [Gap(key, f"owns {deferral.story}", f"the ticket in {epic_file}", "none")]
    gaps: list[Gap] = []
    if "retired" in _strings(ticket, "labels"):
        gaps.append(Gap(key, "not retired", "no `retired` label", "retired"))
    if not _names(_text(ticket, "body"), deferral.story):
        gaps.append(Gap(key, f"owns {deferral.story}", f"its body names {deferral.story}", "none"))
    milestone = _text(ticket, "milestone")
    if milestone != MILESTONE:
        gaps.append(Gap(key, "milestone", MILESTONE, milestone or "none"))
    return gaps + _sprint_gaps(tickets, key, ticket)


def check(tickets: Mapping[str, Ticket]) -> list[Gap]:
    """Every gap in the deferral, sorted; empty when each expectation holds."""
    gaps = [g for d in DEFERRED for key in d.tickets for g in _owner_gaps(tickets, d, key)]
    for key in SCREEN_TICKETS:
        screen = tickets.get(key)
        if screen is not None and not _names(_text(screen, "body"), SCREEN):
            gaps.append(Gap(key, "screen", f"its body names {SCREEN}", "none"))
    for deferral in DEFERRED:
        stand_in = tickets.get(deferral.stand_in)
        if stand_in is None:
            gaps.append(Gap(deferral.stand_in, "states the deferral", "the ticket", "none"))
            continue
        for word in deferral.stated:
            if not _names(_text(stand_in, "body"), word):
                check_name = f"states the deferral of {deferral.story}"
                gaps.append(Gap(deferral.stand_in, check_name, f"its body names {word}", "none"))
    for epic in sorted({d.epic for d in DEFERRED}):
        holder = tickets.get(epic)
        blocked_by = [] if holder is None else _strings(holder, "blocked_by")
        if DEFERRING_EPIC not in blocked_by:
            found = ", ".join(blocked_by) or "none"
            gaps.append(Gap(epic, "blocked by E42", f"{DEFERRING_EPIC} in blocked_by", found))
    return sorted(set(gaps))


def snapshot_gaps(items: Iterable[Ticket]) -> list[Gap]:
    """Each owner ticket on the board snapshot: present, not retired, open or closed as Done."""
    by_key: dict[str, list[Ticket]] = {}
    for item in items:
        found = _TITLE.match(_text(item, "title"))
        if found is not None:
            by_key.setdefault(found.group(1), []).append(item)
    gaps: list[Gap] = []
    for key in _owners():
        listed = by_key.get(key, [])
        if not listed:
            gaps.append(Gap(key, "on the board", f"an issue titled [{key}]", "none"))
        for item in listed:
            if "retired" in _strings(item, "labels"):
                gaps.append(Gap(key, "not retired on the board", "no `retired` label", "retired"))
            state, status = _text(item, "state"), _text(item, "status")
            if state != "OPEN" and status != "Done":
                found_state = f"{state or 'no state'}, status {status or 'none'}"
                gaps.append(Gap(key, "open on the board", "open, or closed as Done", found_state))
    return sorted(set(gaps))


def load_snapshot(path: Path) -> list[Ticket]:
    data = _read_json(path)
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise InputError(f"{path.name}: not a list of board items")
    return data


def _issues(backlog: Path) -> dict[str, str]:
    """`#N` per ticket from the publishing ledger; an absent or unreadable ledger gives none."""
    try:
        ledger = _read_json(backlog / LEDGER)
    except InputError:
        return {}
    if not isinstance(ledger, dict):
        return {}
    issues: dict[str, str] = {}
    for key, entry in ledger.items():
        number = entry.get("number") if isinstance(entry, dict) else None
        if isinstance(number, int):
            issues[key] = f"#{number}"
    return issues


def rows(tickets: Mapping[str, Ticket], issues: Mapping[str, str]) -> list[Row]:
    """The record's table: one row per owner ticket, in DEFERRED's order."""
    table: list[Row] = []
    for story, epic, keys in ((d.story, d.epic, d.tickets) for d in DEFERRED):
        for key in keys:
            ticket = tickets.get(key, {})
            notes: list[str] = []
            consumer = CONSUMER.get(key)
            sprint, target = _sprint(ticket), _sprint(tickets.get(consumer or ""))
            if consumer is not None and sprint is not None and target is not None:
                notes.append(f"design, {target - sprint} sprints before {consumer}")
            if key in SCREEN_TICKETS:
                notes.append(f"names {SCREEN}")
            short = f"S{sprint}" if sprint is not None else _text(ticket, "sprint") or "none"
            cells = (issues.get(key, "none"), _text(ticket, "kind") or "none", short)
            milestone, names = _text(ticket, "milestone"), _names(_text(ticket, "body"), story)
            notes_cell = "; ".join(notes) or "none"
            table.append(Row(story, epic, key, *cells, milestone or "none", names, notes_cell))
    return table


def _table(header: Sequence[str], body: Sequence[Sequence[str]]) -> list[str]:
    """A Markdown table padded as prettier pads one, so the hook leaves the record's bytes."""
    widths = [max(3, *(len(cells[i]) for cells in (header, *body))) for i in range(len(header))]

    def line(cells: Sequence[str]) -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)) + " |"

    return [line(header), line(["-" * w for w in widths]), *(line(cells) for cells in body)]


def _wrap(text: str, width: int = 100) -> list[str]:
    lines: list[str] = []
    for word in text.split(" "):
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


SCOPE = (
    "The static checks cover code that spells the key or the setting; beyond that, C7's second "
    "key is the guarantee."
)


def render_record(
    table: Sequence[Row], *, date: str, reviewer: str, digests: Mapping[str, str]
) -> str:
    """The verification record: deterministic, so the same inputs give the same bytes."""
    window = f"Sprint {WINDOW[0]} to Sprint {WINDOW[1]}"
    stories = ", ".join(sorted({d.stand_in for d in DEFERRED}))
    checked = [
        f"- Each owner ticket is in its epic's backlog file, carries no `retired` label, names its "
        f"story, has the milestone `{MILESTONE}` and a sprint from {window}; a design ticket lands "
        f"at least {DESIGN_AHEAD} sprints before the story it serves.",
        f"- {', '.join(SCREEN_TICKETS)} name {SCREEN}.",
        f"- {stories} state the deferral and name the owners; "
        f"{' and '.join(sorted({d.epic for d in DEFERRED}))} are blocked by {DEFERRING_EPIC}.",
        "- `docs/plan/18-traceability-matrix.md` traces each story to screens, components and "
        "flows, not to an epic, so the story-to-epic link is read from the backlog.",
    ]
    header = ["Story", "Owner epic", "Ticket", "Issue", "Kind", "Sprint", "Milestone"]
    body = [[*astuple(r)[:7], "yes" if r.names_story else "no", r.notes] for r in table]
    lines = [
        "# E42 deferred Musts: the verification record",
        "",
        "<!-- Written by scripts/verify_deferred_must.py --write-record; rerun it, never edit. -->",
        "",
        *_wrap(
            "E42 defers two Must stories by design (E42-Q06): US-ADMIN-010 to E43 and US-ADMIN-012 "
            "to E44. This record is dated evidence that their owners still hold them, read "
            "offline from the backlog. It says when the claim was last true; the run at epic "
            "close is the one of record, and its reviewer is the E42 QA sign-off's."
        ),
        "",
        f"- **Date:** {date}",
        f"- **Reviewer:** {reviewer}",
        "- **Result:** PASS",
        "- **Inputs (sha256):**",
        *(f"  - `{name}`: `{digest}`" for name, digest in sorted(digests.items())),
        "",
        *_table([*header, "Names the story", "Notes"], body),
        "",
        "## What the run checked",
        "",
        *(wrapped for item in checked for wrapped in _wrap_item(item)),
        "",
        *_wrap(SCOPE),
        "",
        "## The one stated exception",
        "",
        *_wrap(EXCEPTION),
        "",
        "## Hand-off",
        "",
        "E42-Q04 attaches this record to the E42 QA sign-off.",
        "",
    ]
    return "\n".join(lines)


def _wrap_item(item: str) -> list[str]:
    """A list item wrapped at 100 columns, its continuation lines indented under its text."""
    first, *rest = _wrap(item[2:], 98)
    return [f"- {first}", *(f"  {line}" for line in rest)]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> tuple[str, str]:
    """`--write-record`'s reviewer (one line, no `|`) and date (a real YYYY-MM-DD), else exit 2."""
    reviewer, date = (args.reviewer or "").strip(), args.date or ""
    if args.write_record is not None and (not reviewer or "\n" in reviewer or "|" in reviewer):
        parser.error("--write-record needs --reviewer: one line, no '|'")
    try:
        real = _DATE.fullmatch(date) is not None and bool(datetime.date.fromisoformat(date))
    except ValueError:
        real = False
    if args.write_record is not None and not real:
        parser.error("--write-record needs --date YYYY-MM-DD")
    return reviewer, date


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E42-Q06: the deferred ADMIN Musts' owners")
    parser.add_argument("--backlog", type=Path, default=BACKLOG, help="the backlog directory")
    parser.add_argument("--snapshot", type=Path, help="a board_snapshot.py output to check too")
    parser.add_argument("--write-record", type=Path, help="write the record here on a pass")
    parser.add_argument("--reviewer", help="the record's reviewer")
    parser.add_argument("--date", help="the record's date, YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    reviewer, date = _record_args(parser, args)
    try:
        tickets = load_backlog(args.backlog)
        gaps = check(tickets)
        if args.snapshot is not None:
            gaps = sorted(set(gaps) | set(snapshot_gaps(load_snapshot(args.snapshot))))
    except InputError as exc:
        print(f"verify_deferred_must: cannot read {exc}", file=sys.stderr)
        return 2
    table = rows(tickets, _issues(args.backlog))
    if args.json:
        result: dict[str, object] = {"result": "FAIL" if gaps else "PASS"}
        result |= {"escalation": ESCALATION} if gaps else {}
        result |= {"gaps": [asdict(g) for g in gaps], "rows": [asdict(r) for r in table]}
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for gap in gaps:
            print(gap.line())
        print(ESCALATION if gaps else f"PASS: {len(table)} owner tickets hold the deferred Musts")
    if gaps or args.write_record is None:
        return 1 if gaps else 0
    digests = {f"{epic}.json": _digest(args.backlog / f"{epic}.json") for epic in _epics()}
    digests[Path(__file__).name] = _digest(Path(__file__))
    text = render_record(table, date=date, reviewer=reviewer, digests=digests)
    args.write_record.parent.mkdir(parents=True, exist_ok=True)
    args.write_record.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
