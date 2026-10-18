#!/usr/bin/env python3
"""
CandleViewer backlog reconciler / validator.

Loads every docs/plan/backlog/E*.json, validates the ticket schema, resolves
blocked_by references, detects cycles, enforces sprint>=blocker-sprint ordering,
enforces the design-ahead rule, level-loads sprints against capacity, and emits
_reconciliation-report.md + all-tickets.json.

Usage:
    python validate.py            # validate + report only (no writes to E*.json)
    python validate.py --fix      # resolve refs, re-sprint, level-load, rewrite files
    python validate.py --check    # CI: write nothing; fail if a twin is not what validate.py writes
"""
from __future__ import annotations

import argparse
import collections
import difflib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKLOG = os.path.dirname(HERE)
PLAN = os.path.dirname(BACKLOG)

# --------------------------------------------------------------------------
# Schema constants (from the planning brief / roadmap)
# --------------------------------------------------------------------------
REQUIRED_KEYS = [
    "key", "kind", "title", "labels", "component", "phase", "sprint",
    "priority", "perspective", "risk", "estimate", "parent", "blocked_by",
]
KINDS = {"Epic", "Story", "Task", "Spike", "Bug", "Chore"}
COMPONENTS = {
    "chart-engine", "data-feeds", "indicators", "drawing-tools", "alerts",
    "backtesting", "scripting", "web", "api", "auth", "collaboration",
    "infra", "docs", "cross-cutting",
}
PHASES = [
    "P0 Foundations", "P1 Core Charting", "P2 Data & Indicators",
    "P3 Drawing & Alerts", "P4 Backtesting & Scripting",
    "P5 Collaboration & Polish",
]
PRIORITIES = ["P0 Critical", "P1 High", "P2 Medium", "P3 Low"]
PERSPECTIVES = {
    "Product", "Architecture", "Development", "Test", "QA", "Security",
    "Compliance", "Ops",
}
RISKS = {
    "R1 Data licensing", "R2 Render performance", "R3 Real-time cost",
    "R4 Script sandbox", "R5 Scope", "R6 Feed rot", "R7 Data accuracy",
    "R8 Browser/GPU compat", "R9 Advice boundary", "R10 Key-person",
    "R11 Alert reliability", "R12 Backtest bias", "R13 Sharing abuse",
    "R14 User retention", "R15 Data lifecycle", "None",
}
FIB = {1, 2, 3, 5, 8}
KEY_RE = re.compile(r"^E\d{2}(?:-([STKDQXC])(\d{2}))?$")

# Release trains -> (first sprint, last sprint), roadmap §1.1 / §3.1
TRAINS = [
    ("R0", 1, 4, "P0 Foundations", "R0 Foundations"),
    ("R1", 5, 9, "P1 Core Charting", "R1 Charting alpha"),
    ("R2", 10, 13, "P2 Data & Indicators", "R2 Order-flow beta"),
    ("R3", 14, 19, "P3 Drawing & Alerts", "R3 Trading on demo"),
    ("R4", 20, 22, "P4 Backtesting & Scripting", "R4 Live enablement"),
    ("R5", 23, 26, "P5 Collaboration & Polish", "R5 Hardening / GA"),
]
PHASE_TO_TRAIN = {t[3]: t for t in TRAINS}
TRAIN_ALLOC = {"R0": 322, "R1": 361, "R2": 327, "R3": 486, "R4": 144, "R5": 186}

MAX_SPRINT = 26
CAPACITY = {n: 90 for n in range(1, MAX_SPRINT + 1)}
CAPACITY[7] = 45  # holiday sprint, roadmap §1.1

# Which epic belongs to which train (roadmap §3 epic register)
EPIC_TRAIN = {}
for n in range(1, 11):
    EPIC_TRAIN["E%02d" % n] = "R0"
for n in range(11, 18):
    EPIC_TRAIN["E%02d" % n] = "R1"
for n in range(18, 27):
    EPIC_TRAIN["E%02d" % n] = "R2"
for n in range(27, 43):
    EPIC_TRAIN["E%02d" % n] = "R3"
for n in range(43, 46):
    EPIC_TRAIN["E%02d" % n] = "R4"
for n in range(46, 50):
    EPIC_TRAIN["E%02d" % n] = "R5"

# Epics that deliberately span more than one train (roadmap §3.1.1). For these
# the epic-level train is only the *home* train (used for coverage/reporting);
# the legal sprint window of an individual ticket is decided by that ticket's
# own phase, not by the epic. E50 ships its gates in R0 (S02-S04) and its
# conformance/adoption half in R1 (S05-S09) because MUST-09 requires the linter
# and the contract suite to land before the first statechart.
EPIC_TRAIN["E50"] = "R0"
SPANNING_EPICS = {"E50": ("R0", "R1", "R2", "R3")}  # R3: upstream contributions C01/C02 parked in S19 headroom (§17)

# "C" = Chore (ADRs, reference docs) introduced by E08/E14/E15/E19; these are
# engineering-owned and consume engineering capacity like any other task.
ENG_SUFFIX = {"S", "T", "K", "C"}  # engineering points
DESIGN_SUFFIX = {"D"}
QA_SUFFIX = {"Q"}
SEC_SUFFIX = {"X"}

ERRORS: list[str] = []

# Owner-accepted capacity overages (docs/plan/30-release-roadmap.md §3.1 / §12, decision
# 2026-09-24): the S07 reduced sprint carries +2 eng pts, and therefore train R1 carries +2.
# Decision 2026-10-09 (#1778 item Y): E35-S03 moved S14 -> S15 for its real E32-T01 (native-SL
# choke point, C-2.6) dependency, dragging E35-S06/S07 with it; S15 carries +8 eng pts, funded
# from the R5 defect/polish reserve. These downgrade to WARN so the governance CI gate stays
# meaningful for *new* overages.
ACCEPTED_OVERAGE = {"sprint": {7: 2, 15: 8}, "train": {"R1": 2}}
WARNINGS: list[str] = []
MOVES: list[dict] = []
UNFIXABLE_SPRINTS: set[int] = set()


def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNINGS.append(msg)


# --------------------------------------------------------------------------
# Sprint helpers
# --------------------------------------------------------------------------
def sprint_num(s):
    if not isinstance(s, str):
        return None
    if s == "Backlog":
        return None
    m = re.match(r"^Sprint (\d{2})$", s)
    return int(m.group(1)) if m else None


def sprint_label(n):
    return "Sprint %02d" % n


def train_of_sprint(n):
    for name, lo, hi, _, _ in TRAINS:
        if lo <= n <= hi:
            return name
    return None


def train_window(train):
    for name, lo, hi, _, _ in TRAINS:
        if name == train:
            return lo, hi
    return 1, MAX_SPRINT


def ticket_train(t):
    """Train that governs a single ticket.

    For a normal epic this is just the epic's train. For a spanning epic
    (roadmap §3.1.1) the epic has no single train, so the ticket's own phase
    decides which train -- and therefore which sprint window -- it belongs to.
    """
    e = epic_of(t["key"])
    if e in SPANNING_EPICS:
        tr = PHASE_TO_TRAIN.get(t.get("phase"))
        if tr:
            return tr[0]
    return EPIC_TRAIN.get(e, "R5")


def ticket_window(t):
    """(first, last) sprint a ticket may legally occupy."""
    return train_window(ticket_train(t))



def epic_of(key):
    return key.split("-")[0]


def suffix_of(key):
    m = KEY_RE.match(key)
    return m.group(1) if m and m.group(1) else None


def discipline(t):
    """eng | design | qa | security, from the key suffix (with label fallback)."""
    s = suffix_of(t["key"])
    # Retired tickets (label "retired", estimate 0, sprint Backlog) never
    # consume any discipline's capacity (ADR-0016 Accepted, 2026-09-24).
    if "retired" in set(t.get("labels") or []):
        return "retired"
    # "upstream" tracking chores are coordination work owned by the Architect
    # (0-capacity discipline in the roadmap), not engineering delivery.
    if "upstream" in set(t.get("labels") or []):
        return "coordination"
    if s in DESIGN_SUFFIX:
        return "design"
    if s in QA_SUFFIX:
        return "qa"
    if s in SEC_SUFFIX:
        return "security"
    if s in ENG_SUFFIX:
        return "eng"
    labels = set(t.get("labels") or [])
    # Epics are containers, not deliverables: they aggregate every discipline's
    # labels, so the label fallback would misread an epic carrying "design" as a
    # design spec and impose a bogus 2-sprint lead time on its own children.
    if t.get("kind") == "Epic":
        return "eng"
    if "design" in labels or "type/design" in labels:
        return "design"
    if "qa" in labels:
        return "qa"
    if "security" in labels:
        return "security"
    return "eng"


def is_fe_story(t):
    """Frontend story/task that consumes a design."""
    if t["kind"] == "Epic":
        return False
    if discipline(t) != "eng":
        return False
    return t.get("component") in {"web", "chart-engine", "drawing-tools", "indicators"}


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------
# validate.py is the twins' formatter (#3362; prettier skips them): an E<nn>.json is exactly what
# json.dump(data, fh, ensure_ascii=False, indent=2) writes (AGENTS.md §3a), byte for byte except
# line endings (#3454): git commits the twins as LF (.gitattributes; pr.yml's backlog-twin-eol gate
# fails any other blob, #3495), so read_twin() reads a CRLF twin (a Windows text-mode write or
# checkout) as LF; the final newline still has to match.
TWIN_FORMAT = ("TWIN-FORMAT %s: not byte-identical to what validate.py writes; validate.py is the "
               "formatter of the backlog twins, never prettier or a hand edit: %s")


def twin_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


def read_twin(path):
    """A twin as git commits it: CRLF line endings read as LF, every other byte as it is. Not in
    universal-newline mode: git commits a lone CR as it is, so a lone CR has to stay and fail."""
    with io.open(path, encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def load(fix=False):
    files = sorted(
        f for f in os.listdir(BACKLOG)
        if re.match(r"^E\d{2}\.json$", f)
    )
    tickets, by_file = [], {}
    for fn in files:
        path = os.path.join(BACKLOG, fn)
        try:
            raw = read_twin(path)
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            err("INVALID-JSON %s: %s" % (fn, e))
            continue
        if not isinstance(data, list):
            err("NOT-A-LIST %s: top level must be a JSON array" % fn)
            continue
        if raw != twin_text(data) and not fix:  # --fix rewrites it in the twin layout
            err(TWIN_FORMAT % (fn, "re-save it via Python as AGENTS.md section 3a says, "
                                   "then run validate.py"))
        by_file[fn] = data
        for t in data:
            t["_file"] = fn
            tickets.append(t)
    return tickets, by_file, files


# --------------------------------------------------------------------------
# 1. Schema / enum validation
# --------------------------------------------------------------------------
def check_schema(tickets):
    for t in tickets:
        f = t.get("_file", "?")
        k = t.get("key", "<no-key>")
        for rk in REQUIRED_KEYS:
            if rk not in t:
                err("MISSING-KEY %s %s: '%s'" % (f, k, rk))
        if "key" in t and not KEY_RE.match(str(t["key"])):
            err("BAD-KEY-FORMAT %s: '%s' (want Enn or Enn-[STKDQX]nn)" % (f, k))
        if t.get("kind") not in KINDS:
            err("BAD-KIND %s: %r" % (k, t.get("kind")))
        title = t.get("title", "")
        if not isinstance(title, str) or not title:
            err("BAD-TITLE %s: empty" % k)
        elif len(title) > 80:
            warn("LONG-TITLE %s: %d chars" % (k, len(title)))
        if not isinstance(t.get("labels"), list) or not t["labels"]:
            err("BAD-LABELS %s: must be a non-empty list" % k)
        if t.get("component") not in COMPONENTS:
            err("BAD-COMPONENT %s: %r" % (k, t.get("component")))
        if t.get("phase") not in PHASES:
            err("BAD-PHASE %s: %r" % (k, t.get("phase")))
        if t.get("priority") not in PRIORITIES:
            err("BAD-PRIORITY %s: %r" % (k, t.get("priority")))
        if t.get("perspective") not in PERSPECTIVES:
            err("BAD-PERSPECTIVE %s: %r" % (k, t.get("perspective")))
        if t.get("risk") not in RISKS:
            err("BAD-RISK %s: %r" % (k, t.get("risk")))
        s = t.get("sprint")
        if s != "Backlog" and sprint_num(s) is None:
            err("BAD-SPRINT %s: %r" % (k, s))
        elif sprint_num(s) is not None and not 1 <= sprint_num(s) <= MAX_SPRINT:
            err("SPRINT-OUT-OF-RANGE %s: %r" % (k, s))
        e = t.get("estimate")
        if t.get("kind") == "Epic":
            if not isinstance(e, int) or e <= 0:
                err("BAD-EPIC-ESTIMATE %s: %r" % (k, e))
        elif "retired" in (t.get("labels") or []):
            if e != 0 or t.get("sprint") != "Backlog":
                err("BAD-RETIRED %s: retired tickets need estimate 0 and sprint Backlog" % k)
        elif e not in FIB:
            err("BAD-ESTIMATE %s: %r (want one of %s)" % (k, e, sorted(FIB)))
        p = t.get("parent")
        if t.get("kind") == "Epic":
            if p is not None:
                err("EPIC-HAS-PARENT %s: %r" % (k, p))
        elif not p:
            err("MISSING-PARENT %s" % k)
        if not isinstance(t.get("blocked_by"), list):
            err("BAD-BLOCKED-BY %s: must be a list" % k)


def check_unique(tickets):
    """Returns key -> ticket. Duplicates are reported; first occurrence wins."""
    index = {}
    for t in tickets:
        k = t.get("key")
        if k in index:
            err("DUPLICATE-KEY %s in %s and %s"
                % (k, index[k].get("_file"), t.get("_file")))
        else:
            index[k] = t
    return index


def check_epic_coverage(tickets, files):
    present = {epic_of(t["key"]) for t in tickets}
    expected = set(EPIC_TRAIN)
    for e in sorted(expected - present):
        err("MISSING-EPIC-FILE %s.json — epic in roadmap §3 has no backlog file" % e)
    for t in tickets:
        e = epic_of(t["key"])
        if t["_file"] != e + ".json":
            err("FILE-MISMATCH %s lives in %s" % (t["key"], t["_file"]))
    # epic row itself must exist in each file
    epics = {t["key"] for t in tickets if t.get("kind") == "Epic"}
    for e in sorted(present):
        if e not in epics:
            err("NO-EPIC-ROW %s.json has no kind=Epic ticket" % e)


def check_parents(tickets, index):
    for t in tickets:
        p = t.get("parent")
        if p and p not in index:
            err("BAD-PARENT %s -> %s (not a known key)" % (t["key"], p))
        if p and epic_of(p) != epic_of(t["key"]):
            err("CROSS-EPIC-PARENT %s -> %s" % (t["key"], p))


def check_phase_train(tickets):
    for t in tickets:
        e = epic_of(t["key"])
        train = EPIC_TRAIN.get(e)
        if not train:
            continue
        if e in SPANNING_EPICS:
            # A spanning epic's tickets may carry any phase belonging to one of
            # the trains it spans; the sprint window is then checked per ticket
            # against that phase's train by ticket_window().
            allowed = {x[3] for x in TRAINS if x[0] in SPANNING_EPICS[e]}
            if t.get("phase") not in allowed:
                err("PHASE-TRAIN-MISMATCH %s: phase=%r but epic %s spans %s "
                    "(want one of %r)"
                    % (t["key"], t.get("phase"), e,
                       "/".join(SPANNING_EPICS[e]), sorted(allowed)))
            continue
        want_phase = [x[3] for x in TRAINS if x[0] == train][0]
        if t.get("phase") != want_phase:
            err("PHASE-TRAIN-MISMATCH %s: phase=%r but epic %s is train %s (want %r)"
                % (t["key"], t.get("phase"), e, train, want_phase))


def check_rollup(tickets, index, fix=False):
    """Epic estimate must equal the sum of its children."""
    kids = collections.defaultdict(int)
    for t in tickets:
        if t.get("kind") != "Epic":
            e = epic_of(t["key"])
            kids[e] += t.get("estimate") or 0
    for t in tickets:
        if t.get("kind") == "Epic":
            want = kids[t["key"]]
            if t.get("estimate") != want:
                if fix:
                    MOVES.append(dict(key=t["key"], frm="%s pts" % t.get("estimate"),
                                      to="%s pts" % want,
                                      reason="epic rollup = sum of children"))
                    t["estimate"] = want
                else:
                    err("EPIC-ROLLUP %s: estimate=%s but children sum to %s"
                        % (t["key"], t.get("estimate"), want))


# --------------------------------------------------------------------------
# 2. blocked_by resolution
# --------------------------------------------------------------------------
def resolve_refs(tickets, index):
    """Resolve blocked_by entries. Epic ids are kept as-is; unknown ticket keys
    are fuzzy-matched by title inside the referenced epic, else fall back to the
    epic id."""
    by_epic = collections.defaultdict(list)
    for t in tickets:
        if t.get("kind") != "Epic":
            by_epic[epic_of(t["key"])].append(t)
    known_epics = {epic_of(k) for k in index}
    resolutions = []
    for t in tickets:
        out, seen = [], set()
        for ref in t.get("blocked_by") or []:
            if not isinstance(ref, str):
                err("BAD-REF %s: %r not a string" % (t["key"], ref))
                continue
            ref = ref.strip()
            new = ref
            if re.match(r"^E\d{2}$", ref):
                if ref not in known_epics and ref not in EPIC_TRAIN:
                    err("UNKNOWN-EPIC-REF %s -> %s" % (t["key"], ref))
                    continue
            elif ref in index:
                pass
            else:
                tgt_epic = epic_of(ref)
                cands = by_epic.get(tgt_epic, [])
                if cands:
                    best = difflib.get_close_matches(
                        t.get("title", ""), [c["title"] for c in cands], n=1, cutoff=0.45)
                    if best:
                        new = next(c["key"] for c in cands if c["title"] == best[0])
                    else:
                        new = tgt_epic
                elif tgt_epic in EPIC_TRAIN:
                    new = tgt_epic     # epic file missing -> epic-level dependency
                else:
                    err("UNRESOLVABLE-REF %s -> %s" % (t["key"], ref))
                    continue
                resolutions.append((t["key"], ref, new))
            if new == t["key"]:
                continue               # self-dependency, drop
            if new not in seen:
                seen.add(new)
                out.append(new)
        t["blocked_by"] = out
    return resolutions


def check_cycles(tickets, index):
    graph = {}
    for t in tickets:
        graph[t["key"]] = [r for r in t["blocked_by"]]
    # expand epic refs to the epic ticket node if present
    color, cycles = {}, []
    stack = []

    def visit(n):
        if color.get(n) == 2:
            return
        if color.get(n) == 1:
            i = stack.index(n)
            cycles.append(stack[i:] + [n])
            return
        color[n] = 1
        stack.append(n)
        for m in graph.get(n, []):
            if m in graph:
                visit(m)
        stack.pop()
        color[n] = 2

    for n in list(graph):
        visit(n)
    for c in cycles:
        err("DEPENDENCY-CYCLE %s" % " -> ".join(c))
    return cycles


# --------------------------------------------------------------------------
# 3. Sprint ordering vs blockers
# --------------------------------------------------------------------------
def epic_last_sprint(tickets):
    """Returns (first, last) scheduled sprint per epic."""
    lo_ = collections.defaultdict(lambda: 99)
    hi_ = collections.defaultdict(int)
    for t in tickets:
        n = sprint_num(t.get("sprint"))
        if n:
            e = epic_of(t["key"])
            lo_[e] = min(lo_[e], n)
            hi_[e] = max(hi_[e], n)
    out = {}
    for e, train in EPIC_TRAIN.items():
        w = train_window(train)
        out[e] = (lo_.get(e, w[0]) if lo_.get(e, 99) != 99 else w[0],
                  hi_.get(e) or w[1])
    for e in set(lo_) - set(out):
        out[e] = (lo_[e], hi_[e])
    return out


def blocker_sprint(ref, index, elast):
    """Sprint a dependent may start in.

    An **epic-level** reference (`Enn`) is *start ordering*: the roadmap itself
    overlaps epics that depend on each other (§11.2 — "E26 replay … Started S11"
    while E18 runs S10–S11), so a coarse epic dependency means "that epic must be
    underway", i.e. its first sprint. A **ticket-level** reference is strict:
    the blocking ticket must be in the same sprint or earlier.
    """
    if re.match(r"^E\d{2}$", ref):
        lo, _hi = elast.get(ref, (0, 0))
        return lo
    t = index.get(ref)
    return sprint_num(t.get("sprint")) if t else 0


def check_and_fix_ordering(tickets, index, fix):
    """Every ticket's sprint must be >= max(blocker sprints). Repeat to a fixed
    point because moves cascade."""
    for _ in range(40):
        elast = epic_last_sprint(tickets)
        changed = False
        for t in sorted(tickets, key=lambda x: sprint_num(x.get("sprint")) or 99):
            if t.get("kind") == "Epic":
                continue
            n = sprint_num(t.get("sprint"))
            if n is None:
                continue
            need = 0
            src = None
            for ref in t["blocked_by"]:
                b = blocker_sprint(ref, index, elast) or 0
                if b > need:
                    need, src = b, ref
            if need > n:
                lo, hi = ticket_window(t)
                target = min(max(need, lo), hi)
                if target > n:
                    if fix:
                        MOVES.append(dict(key=t["key"], frm=sprint_label(n),
                                          to=sprint_label(target),
                                          reason="blocked_by %s (sprint %s)" % (src, need)))
                        t["sprint"] = sprint_label(target)
                        changed = True
                    else:
                        err("SPRINT-ORDER %s in %s but blocker %s is in Sprint %02d"
                            % (t["key"], t["sprint"], src, need))
                elif need > hi:
                    err("SPRINT-ORDER-UNFIXABLE %s: blocker %s lands Sprint %02d, "
                        "past the end of its train window (S%02d)"
                        % (t["key"], src, need, hi))
        if not changed:
            break


def check_design_ahead(tickets, index, fix):
    """A design ticket must be Done >= 2 sprints before the FE story that
    depends on it."""
    for _ in range(20):
        changed = False
        for t in tickets:
            if not is_fe_story(t):
                continue
            n = sprint_num(t.get("sprint"))
            if n is None:
                continue
            for ref in t["blocked_by"]:
                d = index.get(ref)
                if not d or discipline(d) != "design":
                    continue
                # design-qa tickets compare the *built* screen against the spec
                # (02-definition-of-ready-done.md §70) so they necessarily run
                # after or alongside the story; the design-ahead rule applies to
                # the specs a story consumes, not to its own review pass.
                if "design-qa" in set(d.get("labels") or []):
                    continue
                dn = sprint_num(d.get("sprint"))
                if dn is None:
                    continue
                if n - dn < 2:
                    want = dn + 2
                    lo, hi = ticket_window(t)
                    if fix and want <= hi:
                        MOVES.append(dict(key=t["key"], frm=sprint_label(n),
                                          to=sprint_label(want),
                                          reason="design-ahead: design %s in %s"
                                                 % (d["key"], d["sprint"])))
                        t["sprint"] = sprint_label(want)
                        n = want
                        changed = True
                    elif fix:
                        # pull the design earlier instead, but never earlier than
                        # the design ticket's own blockers allow
                        elast = epic_last_sprint(tickets)
                        floor = min_allowed_sprint(d, index, elast)
                        want_d = n - 2
                        if want_d >= floor and want_d >= 1:
                            MOVES.append(dict(key=d["key"], frm=d["sprint"],
                                              to=sprint_label(want_d),
                                              reason="design-ahead for %s" % t["key"]))
                            d["sprint"] = sprint_label(want_d)
                            changed = True
                        else:
                            err("DESIGN-AHEAD-UNFIXABLE %s (%s) consumes design %s "
                                "(%s): the story cannot move later inside its train "
                                "window (S%02d) and the design cannot move earlier "
                                "than S%02d without breaking its own blockers"
                                % (t["key"], t["sprint"], d["key"], d["sprint"],
                                   hi, floor))
                    else:
                        err("DESIGN-AHEAD %s (%s) consumes design %s (%s): "
                            "needs >=2 sprints of lead time"
                            % (t["key"], t["sprint"], d["key"], d["sprint"]))
        if not changed:
            break


# --------------------------------------------------------------------------
# 4. Capacity / level-loading
# --------------------------------------------------------------------------
def points_by_sprint(tickets):
    eng = collections.Counter()
    other = collections.defaultdict(collections.Counter)
    for t in tickets:
        if t.get("kind") == "Epic":
            continue
        n = sprint_num(t.get("sprint"))
        if n is None:
            continue
        d = discipline(t)
        if d == "eng":
            eng[n] += t.get("estimate") or 0
        else:
            other[d][n] += t.get("estimate") or 0
    return eng, other


def min_allowed_sprint(t, index, elast):
    lo = ticket_window(t)[0]
    for ref in t["blocked_by"]:
        lo = max(lo, blocker_sprint(ref, index, elast) or 0)
    return lo


PRI_RANK = {"P3 Low": 0, "P2 Medium": 1, "P1 High": 2, "P0 Critical": 3}


def latest_allowed_sprint(t, index, hi):
    """Latest sprint a ticket may take without pushing a dependent past it."""
    latest = hi
    for other in index.values():
        if other.get("kind") == "Epic":
            continue
        if t["key"] in (other.get("blocked_by") or []):
            n = sprint_num(other.get("sprint"))
            if n:
                latest = min(latest, n)
    return max(1, latest)


# Epic dependency edges from roadmap §11.1 (source --> target means "target
# depends on source"). Used only to flag edges pointing the wrong way.
ROADMAP_EDGES = {
    ("E01", "E02"), ("E02", "E03"), ("E03", "E04"), ("E02", "E05"),
    ("E02", "E06"), ("E02", "E07"), ("E02", "E08"), ("E03", "E09"),
    ("E05", "E10"), ("E09", "E10"),
    ("E06", "E11"), ("E10", "E11"), ("E08", "E17"), ("E17", "E11"),
    ("E07", "E12"), ("E08", "E12"), ("E11", "E12"), ("E12", "E13"),
    ("E11", "E14"), ("E11", "E15"), ("E13", "E15"), ("E07", "E16"),
    ("E08", "E16"),
    ("E12", "E18"), ("E16", "E18"), ("E18", "E19"), ("E18", "E20"),
    ("E11", "E21"), ("E17", "E21"), ("E08", "E22"), ("E18", "E23"),
    ("E08", "E24"), ("E21", "E25"), ("E23", "E25"), ("E16", "E26"),
    ("E18", "E26"), ("E21", "E26"),
    ("E09", "E27"), ("E27", "E28"), ("E08", "E29"), ("E27", "E29"),
    ("E29", "E30"), ("E30", "E31"), ("E21", "E31"), ("E29", "E32"),
    ("E39", "E32"), ("E32", "E33"), ("E28", "E34"), ("E32", "E34"),
    ("E25", "E35"), ("E29", "E35"), ("E26", "E38"),
}


def check_inverted_edges(tickets, index):
    """Flag blocked_by edges that run against the roadmap §11.1 epic graph."""
    inverted = 0
    for t in tickets:
        src = epic_of(t["key"])
        for ref in list(t["blocked_by"]):
            tgt = epic_of(ref)
            # ticket in epic `src` blocked_by epic `tgt` means tgt --> src.
            # That is inverted iff the roadmap only has src --> tgt.
            if (src, tgt) in ROADMAP_EDGES and (tgt, src) not in ROADMAP_EDGES:
                err("INVERTED-DEP %s blocked_by %s, but roadmap §11.1 has "
                    "%s --> %s (edge points the other way)"
                    % (t["key"], ref, src, tgt))
                inverted += 1
    return inverted


def drain_forward(tickets, index):
    """Make room ahead of an over-capacity sprint by draining the sprints between
    it and the next one with headroom.

    S06 (101/90) can only legally reach S07 (itself over) and S08 (90/90), while
    S09 sits 43 pts under capacity but is out of reach for every S06 ticket's
    dependents. S08 however can legally shed 19 pts into S09. Working the *full*
    sprints from the back forwards opens the downstream room that lets the
    genuinely over-capacity sprints drain, which relieving only the first
    over-capacity sprint never achieves.
    """
    changed = False
    for _ in range(100):
        eng, _o = points_by_sprint(tickets)
        over = [n for n in sorted(eng) if eng[n] > CAPACITY[n]]
        if not over:
            break
        first = over[0]
        elast = epic_last_sprint(tickets)
        moved = False
        # walk sprints after the overloaded one from the back, freeing capacity
        for n in range(MAX_SPRINT, first, -1):
            if eng.get(n, 0) <= 0:
                continue
            # Only drain a sprint that is itself full or over: shedding points
            # from a sprint with headroom just churns the schedule (it produced
            # ~900 no-benefit moves) without relieving the sprint behind it.
            if eng.get(n, 0) < CAPACITY[n]:
                continue
            for t in sorted((t for t in tickets
                             if t.get("kind") != "Epic"
                             and discipline(t) == "eng"
                             and sprint_num(t.get("sprint")) == n),
                            key=lambda t: (PRI_RANK.get(t.get("priority"), 3),
                                           -(t.get("estimate") or 0))):
                lo, hi = ticket_window(t)
                latest = latest_allowed_sprint(t, index, hi)
                est = t.get("estimate") or 0
                for tgt in range(n + 1, latest + 1):
                    if eng.get(tgt, 0) + est <= CAPACITY[tgt]:
                        MOVES.append(dict(
                            key=t["key"], frm=sprint_label(n), to=sprint_label(tgt),
                            reason="drain-forward: free room in S%02d so S%02d "
                                   "(%d/%d pts) can level" % (n, first,
                                                              eng[first],
                                                              CAPACITY[first])))
                        t["sprint"] = sprint_label(tgt)
                        eng[n] -= est
                        eng[tgt] = eng.get(tgt, 0) + est
                        moved = changed = True
                        break
                if moved:
                    break
            if moved:
                break
        if not moved:
            break
    return changed


def repack(tickets, index):
    """Dependency-aware earliest-start repack.

    level_load() only ever relocates a single ticket, and never past its own
    dependents, so a chain that is packed late stays late even when an earlier
    sprint in the same train has headroom (R1 carries 399 pts against 405 of
    capacity, R3 496 against 540 — the work fits, it is only badly distributed).
    Here we walk tickets in dependency order and pull each one to the earliest
    sprint its blockers and its train window allow that still has room, which
    drains the over-capacity sprints into the slack ones.
    """
    changed = False
    eng, _o = points_by_sprint(tickets)
    movable = [t for t in tickets
               if t.get("kind") != "Epic" and discipline(t) == "eng"
               and sprint_num(t.get("sprint")) is not None]
    # dependency order: a ticket is only considered after its blockers, so the
    # earliest-start it computes already reflects any pull-in of its blockers.
    movable.sort(key=lambda t: (sprint_num(t["sprint"]), len(t["blocked_by"])))
    for t in movable:
        elast = epic_last_sprint(tickets)
        n = sprint_num(t["sprint"])
        lo, hi = ticket_window(t)
        earliest = max(lo, min_allowed_sprint(t, index, elast))
        # Pulling a story in must not break the design-ahead rule: it may not
        # land within 2 sprints of any non-design-QA spec it consumes.
        for ref in t["blocked_by"]:
            d = index.get(ref)
            if not d or discipline(d) != "design":
                continue
            if "design-qa" in set(d.get("labels") or []):
                continue
            dn = sprint_num(d.get("sprint"))
            if dn is not None:
                earliest = max(earliest, dn + 2)
        est = t.get("estimate") or 0
        for tgt in range(earliest, n):
            if eng.get(tgt, 0) + est <= CAPACITY[tgt]:
                MOVES.append(dict(key=t["key"], frm=sprint_label(n),
                                  to=sprint_label(tgt),
                                  reason="repack: pulled to earliest sprint with "
                                         "headroom (S%02d was at %d/%d pts)"
                                         % (n, eng.get(n, 0), CAPACITY[n])))
                eng[n] -= est
                eng[tgt] = eng.get(tgt, 0) + est
                t["sprint"] = sprint_label(tgt)
                changed = True
                break
    return changed


def cascade_push(tickets, index):
    """Relieve an over-capacity sprint by pushing a ticket *and its dependents*.

    level_load() refuses to move a ticket past a dependent, and repack() only
    pulls work earlier, so a sprint whose tickets all have same-sprint dependents
    stays over capacity even when a later sprint in the train has headroom (S06
    at 110/90 and the S07 holiday sprint at 72/45, against 52 pts free in S09).
    Pushing a whole dependency closure later is always safe for blocker ordering
    and for design-ahead — both only require a *minimum* lead time — so we move
    the smallest closure that fits the target sprint.
    """
    dependents = collections.defaultdict(list)
    for t in tickets:
        if t.get("kind") == "Epic":
            continue
        for ref in t["blocked_by"] or []:
            dependents[ref].append(t["key"])

    def closure(key):
        seen, stack = set(), [key]
        while stack:
            k = stack.pop()
            if k in seen:
                continue
            seen.add(k)
            stack.extend(dependents.get(k, []))
        return seen

    changed = False
    stuck = set()
    for _ in range(200):
        eng, _o = points_by_sprint(tickets)
        over = [n for n in sorted(eng)
                if eng[n] > CAPACITY[n] and n not in stuck]
        if not over:
            break
        n = over[0]
        best = None
        for t in tickets:
            if (t.get("kind") == "Epic" or discipline(t) != "eng"
                    or sprint_num(t.get("sprint")) != n):
                continue
            grp = [index[k] for k in closure(t["key"]) if k in index
                   and index[k].get("kind") != "Epic"
                   and discipline(index[k]) == "eng"
                   and sprint_num(index[k].get("sprint")) is not None]
            # only the part of the closure at or after n actually shifts
            grp = [g for g in grp if sprint_num(g["sprint"]) >= n]
            lo, hi = ticket_window(t)
            span = max(sprint_num(g["sprint"]) for g in grp) - n
            for tgt in range(n + 1, hi + 1 - span):
                delta = tgt - n
                proj = collections.Counter(eng)
                for g in grp:
                    gn = sprint_num(g["sprint"])
                    proj[gn] -= g.get("estimate") or 0
                    proj[gn + delta] += g.get("estimate") or 0
                # The source sprint is over capacity by definition, so we cannot
                # demand that every sprint fits. Require instead that the move
                # strictly relieves n and introduces no new overload elsewhere.
                ok = (proj[n] < eng[n] and
                      all(proj[s] <= max(CAPACITY[s], eng.get(s, 0))
                          for s in proj if s != n))
                if ok:
                    relief = sum(g.get("estimate") or 0
                                 for g in grp if sprint_num(g["sprint"]) == n)
                    cand = (len(grp), -relief, t["key"], grp, delta, tgt)
                    if best is None or cand[:3] < best[:3]:
                        best = cand
                    break
        if best is None:
            # Nothing relieves this sprint; park it and keep working the rest
            # rather than abandoning the whole pass.
            stuck.add(n)
            continue
        _, _, key, grp, delta, tgt = best
        for g in grp:
            gn = sprint_num(g["sprint"])
            MOVES.append(dict(key=g["key"], frm=g["sprint"],
                              to=sprint_label(gn + delta),
                              reason="cascade-push: relieve S%02d (%d/%d pts) via "
                                     "%s and its dependents"
                                     % (n, eng[n], CAPACITY[n], key)))
            g["sprint"] = sprint_label(gn + delta)
        changed = True
    return changed


def level_load(tickets, index, fix):
    """Move tickets out of over-capacity sprints, preferring an *earlier* sprint
    with headroom (dependencies permitting) before pushing work later."""
    for _ in range(400):
        eng, _o = points_by_sprint(tickets)
        over = [(n, p) for n, p in sorted(eng.items())
                if p > CAPACITY[n] and n not in UNFIXABLE_SPRINTS]
        if not over:
            break
        n, p = over[0]
        elast = epic_last_sprint(tickets)
        cands = [
            t for t in tickets
            if t.get("kind") != "Epic"
            and sprint_num(t.get("sprint")) == n
            and discipline(t) == "eng"
        ]
        # lowest priority first, then largest estimate (biggest relief per move)
        cands.sort(key=lambda t: (PRI_RANK.get(t.get("priority"), 3),
                                  -(t.get("estimate") or 0)))
        moved = False
        for t in cands:
            lo, hi = ticket_window(t)
            est = t.get("estimate") or 0
            earliest = max(lo, min_allowed_sprint(t, index, elast))
            latest_ok = latest_allowed_sprint(t, index, hi)
            # prefer pulling work earlier (keeps the train front-loaded), then later
            order = list(range(n - 1, earliest - 1, -1)) + \
                    list(range(n + 1, latest_ok + 1))
            for tgt in order:
                if eng.get(tgt, 0) + est <= CAPACITY[tgt]:
                    if fix:
                        MOVES.append(dict(
                            key=t["key"], frm=sprint_label(n), to=sprint_label(tgt),
                            reason="level-load: S%02d at %d/%d pts"
                                   % (n, p, CAPACITY[n])))
                        t["sprint"] = sprint_label(tgt)
                        moved = True
                    break
            if moved:
                break
        if not moved:
            if n not in UNFIXABLE_SPRINTS:
                over = p - CAPACITY[n]
                msg = ("OVER-CAPACITY Sprint %02d: %d eng pts vs capacity %d (+%d over) "
                       "— no movable ticket has room elsewhere in the train window; "
                       "absorb from the train buffer or descope per roadmap §12"
                       % (n, p, CAPACITY[n], over))
                if over <= ACCEPTED_OVERAGE["sprint"].get(n, 0):
                    warn(msg + " [owner-accepted overage]")
                else:
                    err(msg)
            # remember, but never mutate CAPACITY (the report reads it)
            UNFIXABLE_SPRINTS.add(n)
    # final report pass
    eng, other = points_by_sprint(tickets)
    return eng, other


def check_train_totals(tickets):
    got = collections.Counter()
    for t in tickets:
        if t.get("kind") == "Epic" or discipline(t) != "eng":
            continue
        n = sprint_num(t.get("sprint"))
        if n:
            got[train_of_sprint(n)] += t.get("estimate") or 0
    rows = []
    for name, lo, hi, _, _ in TRAINS:
        want = TRAIN_ALLOC[name]
        have = got[name]
        cap = sum(CAPACITY[i] for i in range(lo, hi + 1))
        delta = have - want
        rows.append((name, "S%02d-S%02d" % (lo, hi), cap, want, have, delta))
        if have > cap:
            msg = "TRAIN-OVER-CAPACITY %s: %d eng pts vs %d available" % (name, have, cap)
            if have - cap <= ACCEPTED_OVERAGE["train"].get(name, 0):
                warn(msg + " [owner-accepted overage]")
            else:
                err(msg)
        elif want and abs(delta) > want * 0.35:
            warn("TRAIN-BUDGET-DRIFT %s: roadmap §3.1 allocates %d pts, backlog "
                 "carries %d (%+d)" % (name, want, have, delta))
    return rows


# --------------------------------------------------------------------------
# 5. Doc cross-reference spot check
# --------------------------------------------------------------------------
def check_doc_refs(tickets, sample=120):
    docs = {}
    for fn in ("11-user-stories.md", "14-screens-catalogue.md",
               "15-component-catalogue.md", "18-traceability-matrix.md"):
        p = os.path.join(PLAN, fn)
        docs[fn] = io.open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    corpus = "\n".join(docs.values())
    found = collections.Counter()
    for t in tickets:
        for m in re.findall(r"\b(?:US-[A-Z]+-\d+|SCR-\d+|CMP-\d+)", t.get("body", "")):
            found[m] += 1
    ids = sorted(found)
    step = max(1, len(ids) // sample)
    checked = ids[::step]
    missing = [i for i in checked if i not in corpus]
    for i in missing:
        err("UNKNOWN-DOC-ID %s referenced by %d ticket(s) but not found in the "
            "plan docs" % (i, found[i]))
    return len(ids), len(checked), missing


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def write_files(by_file):
    for fn, data in by_file.items():
        clean = []
        for t in data:
            c = {k: v for k, v in t.items() if not k.startswith("_")}
            clean.append(c)
        with io.open(os.path.join(BACKLOG, fn), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(twin_text(clean))


def sort_key(t):
    n = sprint_num(t.get("sprint")) or 99
    return (n, epic_of(t["key"]), 0 if t.get("kind") == "Epic" else 1, t["key"])


def write_all_tickets(tickets, check=False):
    out = [{k: v for k, v in t.items() if not k.startswith("_")}
           for t in sorted(tickets, key=sort_key)]
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    p = os.path.join(BACKLOG, "all-tickets.json")
    if check:
        old = read_twin(p) if os.path.exists(p) else None
        if old != text:
            err(TWIN_FORMAT % ("all-tickets.json", "run validate.py and commit what it writes"))
        return "not written (--check)", len(out)
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p, len(out)


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(lines)


def write_e50_section(A, tickets, eng):
    """§14 — what E50 / ADR-0016 costs the schedule, computed from live data."""
    e50 = [t for t in tickets if epic_of(t["key"]) == "E50" and t.get("kind") != "Epic"]
    # Two different accountings: the roadmap's epic register sizes E50 across
    # every discipline (85 pts), while the capacity line only counts engineering
    # points. Keep them separate so neither number looks wrong.
    by_sprint = collections.Counter()      # eng only, for the capacity columns
    all_by_sprint = collections.Counter()  # every discipline, for the register
    for t in e50:
        n = sprint_num(t.get("sprint"))
        if not n:
            continue
        all_by_sprint[n] += t.get("estimate") or 0
        if discipline(t) == "eng":
            by_sprint[n] += t.get("estimate") or 0
    r0 = sum(v for k, v in all_by_sprint.items() if k <= 4)
    r1 = sum(v for k, v in all_by_sprint.items() if k >= 5)

    A("\n## 14. E50 / ADR-0016 impact\n")
    A("`E50` (statechart contracts & xstate-statemachine adoption readiness) is "
      "the only epic in the backlog that deliberately spans two release trains. "
      "Roadmap §3.1.1 explains why: MUST-09 of `docs/research/xstate/"
      "11-adversarial-review.md` §3 requires the machine-definition linter and "
      "the contract suite to ship **before the first statechart**, and the first "
      "statechart lands in E29 in R3. Gates delivered alongside their consumers "
      "would never have gated anything.\n")

    A("### 14.1 Where its points land\n")
    rows = [(sprint_label(n), all_by_sprint[n], by_sprint[n], train_of_sprint(n))
            for n in sorted(all_by_sprint)]
    A(md_table(["Sprint", "E50 pts (all)", "of which eng", "Train"],
               [(a, str(b), str(c), d) for a, b, c, d in rows]))
    A("")
    A("- **R0 half (S02–S04): %d pts** — dependency pin + attestation, the "
      "lint set, machine-JSON registry, `machine_hash`/envelope, the "
      "`cv.statechart.factory` + mandatory config block, persistence, plugins, "
      "gateway, all twenty committed contracts and the BLOCKING "
      "`tests/xstate_contract` gate, built directly on "
      "`xstate-statemachine==0.9.1` (ADR-0016 Accepted)." % r0)
    A("- **R1+ remainder: %d pts** — invariant/chaos suite, round-14 "
      "our-side fixes, CV-C68 re-mint wrapper, config/OC verification, "
      "upstream liaison; secondary budget/coverage gates and upstream "
      "contributions parked in S19 headroom (§17)." % r1)
    A("- **Total: %d pts** (retired shim/dual-runtime/tracking tickets carry 0)."
      % (r0 + r1))
    write_post_adoption_section(A, tickets, eng)


# Pre-adoption baseline (first validate run 2026-09-24, before E50 re-plan).
BASELINE_SPRINT = {1: 90, 2: 90, 3: 87, 4: 62, 5: 97, 6: 106, 7: 56, 8: 90, 9: 90,
                   10: 89, 11: 89, 12: 89, 13: 90, 19: 33}
BASELINE_TRAIN = {"R0": 329, "R1": 439, "R2": 357, "R3": 477, "R4": 154, "R5": 202}
BASELINE_R5_RESERVE = 129


def write_post_adoption_section(A, tickets, eng):
    """§17 — supersedes the §13–16 accepted-overage narrative."""
    A("\n## 17. Post-adoption re-plan (2026-09-24)\n")
    A("Owner decision: adopt `xstate-statemachine==0.9.1` completely (ADR-0016 "
      "Accepted). The in-house shim, dual-runtime harness, shim-retirement "
      "ladder and upstream-tracking chores are RETIRED (estimate 0, Backlog, "
      "`retired` label; `discipline()` returns `retired` so they never count "
      "toward capacity). This section supersedes the R1/R2 accepted overages "
      "previously recorded in §13–16.\n")
    A("### 17.1 Per sprint (eng pts, before → after)\n")
    rows = []
    for n in sorted(set(BASELINE_SPRINT) | {k for k in eng if k <= 13}):
        b = BASELINE_SPRINT.get(n)
        a = eng.get(n, 0)
        rows.append((sprint_label(n), str(b) if b is not None else "—", str(a),
                     str(CAPACITY[n]), "OVER +%d" % (a - CAPACITY[n])
                     if a > CAPACITY[n] else ""))
    A(md_table(["Sprint", "Before", "After", "Capacity", "Flag"], rows))
    A("\n### 17.2 Per train\n")
    rows = []
    freed = 0
    for name, lo, hi, _, _ in TRAINS:
        have = sum(eng.get(i, 0) for i in range(lo, hi + 1))
        cap = sum(CAPACITY[i] for i in range(lo, hi + 1))
        b = BASELINE_TRAIN[name]
        if name in ("R0", "R1", "R2"):
            freed += max(0, b - cap) - max(0, have - cap)
        rows.append((name, str(b), str(have), str(cap), "%+d" % (have - cap)))
    A(md_table(["Train", "Before", "After", "Capacity", "After vs cap"], rows))
    A("\n### 17.3 R5 reserve\n")
    A("Train overage funded from R5 before: R1 +34 (+ R0/R2 marginal) → "
      "reserve 129. Overage relieved by the re-plan: %d pts → **R5 "
      "defect/polish reserve restored to %d pts** (cap 140)."
      % (freed, min(140, BASELINE_R5_RESERVE + freed)))
    A("\n### 17.4 Remaining pre-accepted overages\n")
    over = sorted(n for n in eng if eng[n] > CAPACITY[n])
    for n in over:
        A("- %s: %d vs %d (+%d) — holiday sprint; baseline E11–E15 charting "
          "chain, 0 E50 pts; accepted per roadmap §12 (train buffer)."
          % (sprint_label(n), eng[n], CAPACITY[n], eng[n] - CAPACITY[n]))
    A("- R1 train: follows from the S07 item above; no E50 pts in S07 other "
      "than E50-Q01 (QA discipline, not eng).")
    A("\nE50 moves: S01/S02/T15/T31/T05→S04 then T05/T06/C01/C02→S19 "
      "(R3 headroom, non-critical secondary gates/upstream contributions); "
      "T04 nightly gate→S04. SPANNING_EPICS[E50] extended to R3.\n")


def write_report(tickets, eng, other, train_rows, resolutions, doc_stats):
    L = []
    A = L.append
    total_pts = sum(t.get("estimate") or 0 for t in tickets if t.get("kind") != "Epic")
    epics = sorted({epic_of(t["key"]) for t in tickets})
    missing = sorted(set(EPIC_TRAIN) - set(epics))

    A("# Backlog reconciliation report\n")
    A("Generated by `docs/plan/backlog/_tools/validate.py`. "
      "Scope: web app only, Bybit USDT linear perps, no Android, no separate admin app.\n")
    A("## 1. Headline\n")
    A(md_table(["Metric", "Value"], [
        ("Epic files loaded", len(epics)),
        ("Epics expected by roadmap §3", len(EPIC_TRAIN)),
        ("**Missing epic files**", ", ".join(missing) if missing else "none"),
        ("Tickets total", len(tickets)),
        ("Child tickets (non-epic)", sum(1 for t in tickets if t.get("kind") != "Epic")),
        ("Total points (children)", total_pts),
        ("Engineering points (S/T/K)", sum(eng.values())),
        ("Design points (D)", sum(other["design"].values())),
        ("QA points (Q)", sum(other["qa"].values())),
        ("Security points (X)", sum(other["security"].values())),
        ("Tickets moved", len(MOVES)),
        ("blocked_by refs rewritten", len(resolutions)),
        ("Errors remaining", len(ERRORS)),
        ("Warnings", len(WARNINGS)),
    ]))

    A("\n## 2. Tickets by kind\n")
    c = collections.Counter(t.get("kind") for t in tickets)
    A(md_table(["Kind", "Count"], sorted(c.items(), key=lambda x: -x[1])))

    A("\n## 3. Tickets by discipline\n")
    c = collections.Counter(discipline(t) for t in tickets if t.get("kind") != "Epic")
    A(md_table(["Discipline", "Count", "Points"], [
        (d, n, sum(t.get("estimate") or 0 for t in tickets
                   if t.get("kind") != "Epic" and discipline(t) == d))
        for d, n in sorted(c.items(), key=lambda x: -x[1])]))

    A("\n## 4. Tickets by train\n")
    rows = []
    for name, lo, hi, phase, ms in TRAINS:
        ts = [t for t in tickets if train_of_sprint(sprint_num(t.get("sprint")) or 0) == name]
        rows.append((name, "S%02d-S%02d" % (lo, hi), phase, len(ts),
                     sum(t.get("estimate") or 0 for t in ts if t.get("kind") != "Epic")))
    A(md_table(["Train", "Sprints", "Phase", "Tickets", "Points"], rows))

    A("\n## 5. Tickets by component\n")
    c = collections.Counter(t.get("component") for t in tickets)
    A(md_table(["Component", "Tickets", "Points"], [
        (k, n, sum(t.get("estimate") or 0 for t in tickets
                   if t.get("component") == k and t.get("kind") != "Epic"))
        for k, n in sorted(c.items(), key=lambda x: -x[1])]))

    A("\n## 6. Points per sprint vs capacity\n")
    A("Engineering = Story/Task/Spike keys (`S`/`T`/`K`). Design (`D`), QA (`Q`) and "
      "Security (`X`) points are tracked separately and do **not** consume the 90-pt "
      "engineering capacity.\n")
    rows = []
    for n in range(1, MAX_SPRINT + 1):
        e = eng.get(n, 0)
        cap = CAPACITY[n]
        flag = ("OVER +%d" % (e - cap)) if e > cap else ("" if e else "—")
        rows.append((sprint_label(n), train_of_sprint(n), e, cap,
                     "%+d" % (cap - e), other["design"].get(n, 0),
                     other["qa"].get(n, 0), other["security"].get(n, 0), flag))
    A(md_table(["Sprint", "Train", "Eng pts", "Capacity", "Headroom",
                "Design", "QA", "Sec", "Flag"], rows))
    bl = [t for t in tickets if t.get("sprint") == "Backlog"]
    A("\nUnscheduled (`Backlog`): **%d** tickets, %d pts.\n"
      % (len(bl), sum(t.get("estimate") or 0 for t in bl)))

    A("\n## 7. Per-train totals vs roadmap §3.1\n")
    A(md_table(["Train", "Sprints", "Capacity (holiday-adj.)",
                "Roadmap allocation", "Backlog eng pts", "Delta"], train_rows))
    A("\n> Roadmap §3.1 allocations are *epic-level* estimates written before the "
      "backlog was decomposed; the backlog figure is the sum of scheduled child "
      "tickets. Deltas below the train capacity line are absorbed by the named "
      "reserves and the train buffer.\n")

    A("\n## 8. Tickets by sprint and epic\n")
    rows = []
    for n in range(1, MAX_SPRINT + 1):
        ts = [t for t in tickets if sprint_num(t.get("sprint")) == n]
        if not ts:
            continue
        es = collections.Counter(epic_of(t["key"]) for t in ts)
        rows.append((sprint_label(n), len(ts),
                     ", ".join("%s×%d" % (k, v) for k, v in sorted(es.items()))))
    A(md_table(["Sprint", "Tickets", "Epics"], rows))

    A("\n## 9. Moved tickets (%d)\n" % len(MOVES))
    if MOVES:
        A(md_table(["Ticket", "From", "To", "Reason"],
                   [(m["key"], m["frm"], m["to"], m["reason"]) for m in MOVES]))
    else:
        A("No ticket needed to move: every sprint already fit capacity and every "
          "dependency and design-ahead constraint already held.\n")

    A("\n## 10. Rewritten `blocked_by` references (%d)\n" % len(resolutions))
    if resolutions:
        A(md_table(["Ticket", "Was", "Now"], resolutions[:400]))
        if len(resolutions) > 400:
            A("\n… and %d more.\n" % (len(resolutions) - 400))
    else:
        A("Every `blocked_by` reference already resolved to an existing key or an "
          "epic id.\n")

    A("\n## 11. Doc cross-reference spot check\n")
    ids, checked, miss = doc_stats
    A("- Distinct `US-`/`SCR-`/`CMP-` ids referenced across the backlog: **%d**" % ids)
    A("- Sampled and verified against `11-user-stories.md`, `14-screens-catalogue.md`, "
      "`15-component-catalogue.md`, `18-traceability-matrix.md`: **%d**" % checked)
    A("- Not found in the plan docs: **%d**%s"
      % (len(miss), (" — " + ", ".join(miss)) if miss else ""))

    A("\n## 12. Planning decisions recorded during reconciliation\n")
    A("- **E26-S07 inverted dependency (resolved by data).** The ticket carried "
      "`blocked_by: E38`, but roadmap §11.1 defines the edge as `E26 --> E38` "
      "(E26 replay feeds E38, not the reverse). The blocker was removed and the "
      "reason recorded on the ticket's `notes`.\n")
    A("- **Design-ahead pull-ins.** E18/E24/E25/E26 each had their hi-fi, "
      "accessibility-review and handoff design tickets landing in the same "
      "sprint as the stories consuming them. Because design work is not bound "
      "by the engineering capacity line, those chains were pulled 1–2 sprints "
      "earlier rather than pushing the stories later, preserving the ≥2-sprint "
      "lead time required by `02-definition-of-ready-done.md` §2.2/§48.\n")
    A("- **S06/S07 residual overload is structural — a decision for roadmap "
      "§12, not a data error.** R1 carries 399 eng pts against 405 of capacity, "
      "so the train fits only with near-perfect packing, and the S07 holiday "
      "sprint (45 pts) forces a pinch. Every S06/S07 ticket is pinned by "
      "same-train dependents: none can legally reach the ~30 free pts in S09. "
      "Relieving this needs a human call — absorb from the train buffer, "
      "descope, or raise S07 capacity — so the reconciler leaves it visible "
      "rather than forcing a move that would break dependency ordering.\n")

    A("\n## 13. Unresolved issues (%d errors, %d warnings)\n"
      % (len(ERRORS), len(WARNINGS)))
    if ERRORS:
        A("### Errors\n")
        cat = collections.Counter(e.split(" ", 1)[0] for e in ERRORS)
        A(md_table(["Category", "Count"], sorted(cat.items(), key=lambda x: -x[1])))
        A("")
        for e in ERRORS[:500]:
            A("- `%s`" % e)
        if len(ERRORS) > 500:
            A("- … and %d more." % (len(ERRORS) - 500))
    else:
        A("No errors.\n")
    if WARNINGS:
        A("\n### Warnings\n")
        for w in WARNINGS[:200]:
            A("- %s" % w)
        if len(WARNINGS) > 200:
            A("- … and %d more." % (len(WARNINGS) - 200))

    write_e50_section(A, tickets, eng)

    p = os.path.join(BACKLOG, "_reconciliation-report.md")
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return p


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fix", action="store_true",
                      help="rewrite E*.json with resolved refs and level-loaded sprints")
    mode.add_argument("--check", action="store_true",
                      help="write nothing; fail if a twin is not what validate.py writes")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    tickets, by_file, files = load(a.fix)
    check_schema(tickets)
    index = check_unique(tickets)
    check_epic_coverage(tickets, files)
    check_parents(tickets, index)
    check_phase_train(tickets)

    resolutions = resolve_refs(tickets, index)
    check_cycles(tickets, index)
    check_inverted_edges(tickets, index)

    # Ordering, design-ahead and level-loading each perturb the others, so under
    # --fix run them to a joint fixed point with errors suppressed, then do one
    # final clean reporting pass.
    if a.fix:
        for _ in range(8):
            before = [t.get("sprint") for t in tickets]
            saved = list(ERRORS)
            check_and_fix_ordering(tickets, index, True)
            check_design_ahead(tickets, index, True)
            repack(tickets, index)
            level_load(tickets, index, True)
            drain_forward(tickets, index)
            cascade_push(tickets, index)
            del ERRORS[len(saved):]
            if [t.get("sprint") for t in tickets] == before:
                break
        # The fix loop records every sprint it could not relieve in the global
        # UNFIXABLE_SPRINTS set, which level_load also uses to suppress errors.
        # Without clearing it the final reporting pass stays silent about real
        # residual overloads and --fix falsely prints "0 errors".
        UNFIXABLE_SPRINTS.clear()

    check_and_fix_ordering(tickets, index, False)
    check_design_ahead(tickets, index, False)
    eng, other = level_load(tickets, index, False)
    check_rollup(tickets, index, a.fix)
    train_rows = check_train_totals(tickets)
    doc_stats = check_doc_refs(tickets)

    if a.fix:
        write_files(by_file)
    rp = "not written (--check)"
    if not a.check:
        rp = write_report(tickets, eng, other, train_rows, resolutions, doc_stats)
    ap_, n = write_all_tickets(tickets, a.check)

    if not a.quiet:
        print("tickets=%d files=%d moves=%d refs_rewritten=%d errors=%d warnings=%d"
              % (len(tickets), len(files), len(MOVES), len(resolutions),
                 len(ERRORS), len(WARNINGS)))
        print("report: %s" % rp)
        print("merged: %s (%d)" % (ap_, n))
        for e in ERRORS[:40]:
            print("  ERR %s" % e)
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
