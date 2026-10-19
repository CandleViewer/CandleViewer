#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Publish the CandleViewer backlog (docs/plan/backlog/all-tickets.json) to
GitHub issues + Project #3 (the CandleViewer organisation project), resumably.

Phases (each independently resumable via the ledger file):
  1. create issues (skip label "retired")
  2. link sub-issues (parent/child) via GraphQL addSubIssue
  3. link blocked-by via GraphQL addBlockedBy
  4. add every issue to Project #3 and set fields

Ledger: docs/plan/backlog/_tools/published.json
  {key: {"number": int, "node_id": str, "item_id": str|None,
         "subissue_done": bool, "blockedby_done": [keys already linked],
         "fields_done": bool}}

Usage:
  python publish_board.py --phase 1
  python publish_board.py --phase 2
  python publish_board.py --phase 3
  python publish_board.py --phase 4
  python publish_board.py --phase all
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKLOG = os.path.dirname(HERE)
ALL_TICKETS = os.path.join(BACKLOG, "all-tickets.json")
LEDGER_PATH = os.path.join(HERE, "published.json")
FAILURES_PATH = os.path.join(HERE, "publish_failures.json")

REPO = "CandleViewer/CandleViewer"
PROJECT_NUMBER = "3"
PROJECT_OWNER = "CandleViewer"
PROJECT_ID = "PVT_kwDOFI4N5c4BnyHX"

GH = "gh"
SLEEP_BETWEEN_CREATES = 5.0
RATE_LIMIT_BACKOFF = 120

# --------------------------------------------------------------------------
def log(msg):
    print(msg, flush=True)


def load_ledger():
    if os.path.exists(LEDGER_PATH):
        with io.open(LEDGER_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_ledger(ledger):
    tmp = LEDGER_PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, LEDGER_PATH)


def load_failures():
    if os.path.exists(FAILURES_PATH):
        with io.open(FAILURES_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return []


def save_failures(failures):
    with io.open(FAILURES_PATH, "w", encoding="utf-8") as fh:
        json.dump(failures, fh, ensure_ascii=False, indent=2)


def load_tickets():
    with io.open(ALL_TICKETS, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run(args, retries=8, input_text=None, retry_on_empty=False):
    """Run a subprocess, retrying on rate limit / transient errors.

    GitHub's secondary rate limit on content-creation endpoints sometimes
    surfaces as a clean exit 0 with empty stdout (silently dropped mutation)
    rather than an HTTP 403 — observed with `gh issue create` under load.
    When retry_on_empty is set, treat that as retryable too.
    """
    for attempt in range(retries):
        p = subprocess.run(args, capture_output=True, text=True,
                            encoding="utf-8", input=input_text)
        if p.returncode == 0:
            if retry_on_empty and not p.stdout.strip():
                log("  empty result (likely secondary rate limit), backing "
                    "off %ss (attempt %d/%d)"
                    % (RATE_LIMIT_BACKOFF, attempt + 1, retries))
                time.sleep(RATE_LIMIT_BACKOFF)
                continue
            return p.stdout
        stderr = p.stderr or ""
        if ("403" in stderr or "rate limit" in stderr.lower()
                or "secondary rate limit" in stderr.lower()
                or "abuse detection" in stderr.lower()):
            log("  rate-limited, backing off %ss (attempt %d/%d)"
                % (RATE_LIMIT_BACKOFF, attempt + 1, retries))
            time.sleep(RATE_LIMIT_BACKOFF)
            continue
        raise RuntimeError("command failed: %s\nSTDERR:\n%s"
                            % (" ".join(args), stderr))
    raise RuntimeError("command failed after retries: %s" % " ".join(args))


# --------------------------------------------------------------------------
# Sprint calendar (roadmap §1.1): Sprint 01 starts 2026-09-28 (Mon), each
# sprint is 14 calendar days, ends the 2nd Friday (day 11 of the sprint).
# --------------------------------------------------------------------------
import datetime

SPRINT01_START = None  # calendar owned by calendar_cv.py


def sprint_num_from_label(label):
    # "Sprint 01" -> 1
    if not label:
        return None
    digits = "".join(c for c in label if c.isdigit())
    return int(digits) if digits else None


from calendar_cv import sprint_dates  # noqa: E402  (1-week AI cadence; see calendar_cv.py)


# --------------------------------------------------------------------------
def order_key(t):
    """Epics first, then children ordered by sprint then key."""
    is_epic = 0 if t.get("kind") == "Epic" else 1
    sn = sprint_num_from_label(t.get("sprint")) or 9999
    return (is_epic, sn, t["key"])


def render_body(t):
    hdr_rows = [
        ("Key", t["key"]),
        ("Kind", t.get("kind", "")),
        ("Estimate", str(t.get("estimate", ""))),
        ("Sprint", t.get("sprint", "")),
        ("Component", t.get("component", "")),
        ("Phase", t.get("phase", "")),
        ("Priority", t.get("priority", "")),
        ("Perspective", t.get("perspective", "")),
        ("Risk", t.get("risk", "")),
        ("Parent", t.get("parent") or "—"),
        ("Blocked by", ", ".join(t.get("blocked_by") or []) or "—"),
    ]
    lines = ["| Field | Value |", "|---|---|"]
    for k, v in hdr_rows:
        lines.append("| %s | %s |" % (k, v))
    header_table = "\n".join(lines)

    epic_file = "%s.json" % t["key"].split("-")[0]
    footer = ("\n\n---\n*Planned in `docs/plan/backlog/%s` — do not edit the "
              "plan JSON from this issue; propose changes via PR.*" % epic_file)

    return header_table + "\n\n" + (t.get("body") or "") + footer


def issue_title(t):
    return "[%s] %s" % (t["key"], t["title"])


# --------------------------------------------------------------------------
def phase1_create(tickets, ledger, failures):
    todo = [t for t in tickets if "retired" not in (t.get("labels") or [])]
    todo.sort(key=order_key)
    total = len(todo)
    done = 0
    for t in todo:
        key = t["key"]
        if key in ledger and ledger[key].get("number"):
            done += 1
            continue
        body = render_body(t)
        labels = ",".join(t.get("labels") or [])
        milestone = t.get("milestone") or ""
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            body_path = fh.name
        try:
            args = [GH, "issue", "create", "--repo", REPO,
                    "--title", issue_title(t), "--body-file", body_path]
            if labels:
                args += ["--label", labels]
            if milestone:
                args += ["--milestone", milestone]
            try:
                out = run(args, retry_on_empty=True)
                if not out.strip():
                    raise RuntimeError("empty stdout from gh issue create "
                                        "after retries")
                url = out.strip().splitlines()[-1].strip()
                number = int(url.rstrip("/").rsplit("/", 1)[-1])
            except (RuntimeError, ValueError, IndexError) as e:
                log("  FAILED create %s: %s" % (key, e))
                failures.append({"phase": 1, "key": key, "error": str(e)})
                save_failures(failures)
                continue
            node_id = run([GH, "issue", "view", str(number), "--repo", REPO,
                            "--json", "id", "-q", ".id"]).strip()
            ledger[key] = {"number": number, "node_id": node_id,
                            "item_id": None, "subissue_done": False,
                            "blockedby_done": [], "fields_done": False}
            save_ledger(ledger)
            done += 1
            log("  [%d/%d] created %s -> #%d" % (done, total, key, number))
        finally:
            try:
                os.remove(body_path)
            except OSError:
                pass
        time.sleep(SLEEP_BETWEEN_CREATES)
    log("phase1: %d/%d issues created" % (done, total))


# --------------------------------------------------------------------------
def graphql_batch(mutations, aliases_per_call=25):
    """mutations: list of (alias, mutation_body_str). Runs in batches."""
    results = {}
    for i in range(0, len(mutations), aliases_per_call):
        chunk = mutations[i:i + aliases_per_call]
        body = "mutation {\n" + "\n".join(
            "  %s: %s" % (alias, m) for alias, m in chunk) + "\n}"
        out = run([GH, "api", "graphql", "-f", "query=%s" % body])
        try:
            data = json.loads(out)
        except Exception:
            data = {"raw": out}
        results[i] = data
    return results


def graphql_batch_raw(mutations, aliases_per_call=15):
    """Run a batched GraphQL mutation, tolerating partial per-alias failures
    (e.g. one duplicate link) that make `gh api graphql` exit non-zero even
    though most aliases in the batch succeeded. Returns {alias: ok_bool}.
    Retries the whole batch on a true rate limit; on any other error, treats
    only the affected aliases as failed (others are inferred successful) by
    inspecting the parsed `errors[].path`.
    """
    ok = {}
    for i in range(0, len(mutations), aliases_per_call):
        chunk = mutations[i:i + aliases_per_call]
        aliases = [a for a, _ in chunk]
        body = "mutation {\n" + "\n".join(
            "  %s: %s" % (alias, m) for alias, m in chunk) + "\n}"
        for attempt in range(10):
            p = subprocess.run([GH, "api", "graphql", "-f", "query=%s" % body],
                                capture_output=True, text=True, encoding="utf-8")
            stderr = p.stderr or ""
            combined = (stderr + " " + (p.stdout or "")).lower()
            if (not p.stdout.strip() or "secondary rate limit" in combined
                    or "abuse detection" in combined
                    or ("rate_limit" in combined and '"path"' not in p.stdout)
                    or "api rate limit" in combined):
                log("  rate-limited batch, backing off %ss (attempt %d/10)"
                    % (RATE_LIMIT_BACKOFF, attempt + 1))
                time.sleep(RATE_LIMIT_BACKOFF)
                continue
            break
        try:
            data = json.loads(p.stdout)
        except Exception:
            for a in aliases:
                ok[a] = False
            continue
        # A top-level (non-per-alias) error such as a rate limit means the
        # whole batch failed with no partial data — do not mark aliases as
        # failed permanently; caller will retry via failures/re-run.
        top_level_errors = [e for e in (data.get("errors") or []) if not e.get("path")]
        if top_level_errors and not data.get("data"):
            log("  batch-level error (no per-alias data): %s"
                % top_level_errors[0].get("message"))
            for a in aliases:
                ok[a] = False
            continue
        errored = set()
        for e in (data.get("errors") or []):
            path = e.get("path") or []
            if path:
                errored.add(path[0])
        for a in aliases:
            if a in errored:
                # "duplicate sub-issue"/"already linked" errors mean the edge
                # already exists — treat as success, not failure.
                msg = next((e.get("message", "") for e in data.get("errors", [])
                            if (e.get("path") or [None])[0] == a), "")
                ok[a] = ("duplicate" in msg.lower() or "already" in msg.lower())
            else:
                ok[a] = (data.get("data", {}) or {}).get(a) is not None
        time.sleep(0.5)
    return ok


def phase2_subissues(tickets, ledger, failures):
    by_key = {t["key"]: t for t in tickets}
    children = [t for t in tickets
                if t.get("parent") and "retired" not in (t.get("labels") or [])
                and t["key"] in ledger and by_key.get(t.get("parent"))
                and t["parent"] in ledger]
    children = [t for t in children if not ledger[t["key"]].get("subissue_done")]
    total = len(children)
    log("phase2: %d sub-issue links pending" % total)
    batch = []
    batch_keys = []
    done = 0
    for idx, t in enumerate(children):
        key = t["key"]
        parent_key = t["parent"]
        parent_node = ledger[parent_key]["node_id"]
        child_node = ledger[key]["node_id"]
        alias = "m%d" % idx
        mutation = ('addSubIssue(input: {issueId: "%s", subIssueId: "%s"}) '
                    "{ issue { id } }") % (parent_node, child_node)
        batch.append((alias, mutation))
        batch_keys.append(key)
        if len(batch) >= 15:
            _flush_subissue_batch(batch, batch_keys, ledger, failures)
            done += len(batch)
            batch, batch_keys = [], []
            log("  [%d/%d] sub-issue links done" % (done, total))
    if batch:
        _flush_subissue_batch(batch, batch_keys, ledger, failures)
        done += len(batch)
        log("  [%d/%d] sub-issue links done" % (done, total))
    save_ledger(ledger)
    log("phase2: complete (%d processed)" % done)


def _flush_subissue_batch(batch, batch_keys, ledger, failures):
    ok = graphql_batch_raw(batch, aliases_per_call=15)
    failed_keys = []
    for (alias, _), key in zip(batch, batch_keys):
        if ok.get(alias):
            ledger[key]["subissue_done"] = True
        else:
            failed_keys.append(key)
    save_ledger(ledger)
    if failed_keys:
        log("  FAILED sub-issue links: %s" % failed_keys)
        failures.append({"phase": 2, "keys": failed_keys})
        save_failures(failures)


# --------------------------------------------------------------------------
def phase3_blockedby(tickets, ledger, failures):
    skipped_targets = []
    edges = []  # (child_key, blocker_key)
    for t in tickets:
        if "retired" in (t.get("labels") or []):
            continue
        key = t["key"]
        if key not in ledger:
            continue
        already = set(ledger[key].get("blockedby_done") or [])
        for blocker_key in (t.get("blocked_by") or []):
            if blocker_key in already:
                continue
            if blocker_key not in ledger:
                skipped_targets.append({"child": key, "blocker": blocker_key,
                                         "reason": "blocker not published "
                                                   "(likely retired)"})
                continue
            edges.append((key, blocker_key))
    total = len(edges)
    log("phase3: %d blocked-by links pending (%d skipped, target missing)"
        % (total, len(skipped_targets)))
    if skipped_targets:
        with io.open(os.path.join(HERE, "publish_skipped_blockedby.json"),
                     "w", encoding="utf-8") as fh:
            json.dump(skipped_targets, fh, ensure_ascii=False, indent=2)

    batch = []
    batch_pairs = []
    done = 0
    for idx, (child_key, blocker_key) in enumerate(edges):
        child_node = ledger[child_key]["node_id"]
        blocker_node = ledger[blocker_key]["node_id"]
        alias = "m%d" % idx
        mutation = ('addBlockedBy(input: {issueId: "%s", '
                    'blockingIssueId: "%s"}) { issue { id } }'
                    ) % (child_node, blocker_node)
        batch.append((alias, mutation))
        batch_pairs.append((child_key, blocker_key))
        if len(batch) >= 15:
            _flush_blockedby_batch(batch, batch_pairs, ledger, failures)
            done += len(batch)
            batch, batch_pairs = [], []
            log("  [%d/%d] blocked-by links done" % (done, total))
    if batch:
        _flush_blockedby_batch(batch, batch_pairs, ledger, failures)
        done += len(batch)
        log("  [%d/%d] blocked-by links done" % (done, total))
    save_ledger(ledger)
    log("phase3: complete (%d processed)" % done)


def _flush_blockedby_batch(batch, pairs, ledger, failures):
    ok = graphql_batch_raw(batch, aliases_per_call=15)
    failed_pairs = []
    for (alias, _), (child_key, blocker_key) in zip(batch, pairs):
        if ok.get(alias):
            ledger[child_key].setdefault("blockedby_done", []).append(blocker_key)
        else:
            failed_pairs.append((child_key, blocker_key))
    save_ledger(ledger)
    if failed_pairs:
        log("  FAILED blocked-by links: %s" % failed_pairs)
        failures.append({"phase": 3, "pairs": failed_pairs})
        save_failures(failures)


# --------------------------------------------------------------------------
# Project field ids (from `gh project field-list 3 --owner CandleViewer --format json`;
# organisation project since 2026-10-19)
FIELD_IDS = {
    "Status": "PVTSSF_lADOFI4N5c4BnyHXzhmVIC0",
    "Priority": "PVTSSF_lADOFI4N5c4BnyHXzhmVIEU",
    "Kind": "PVTSSF_lADOFI4N5c4BnyHXzhmVIEY",
    "Phase": "PVTSSF_lADOFI4N5c4BnyHXzhmVIEg",
    "Risk": "PVTSSF_lADOFI4N5c4BnyHXzhmVIEk",
    "Estimate": "PVTF_lADOFI4N5c4BnyHXzhmVIEw",
    "Rollup": "PVTF_lADOFI4N5c4BnyHXzhmVIE0",
    "Due": "PVTF_lADOFI4N5c4BnyHXzhmVIE4",
    "Start": "PVTF_lADOFI4N5c4BnyHXzhmVIE8",
    "Sprint": "PVTSSF_lADOFI4N5c4BnyHXzhmVIFI",
    "Component": "PVTSSF_lADOFI4N5c4BnyHXzhmVIFM",
    "Perspective": "PVTSSF_lADOFI4N5c4BnyHXzhmVIFQ",
}

STATUS_OPTS = {"Backlog": "0bf8b687", "Ready": "7b6bf5d3",
               "In Progress": "e43c9a29", "In Review": "c7cf0320",
               "In Test": "818581aa", "Blocked": "ed99dfd6", "Done": "50cf6528"}
PRIORITY_OPTS = {"P0 Critical": "667cd7f0", "P1 High": "2bf57a25",
                  "P2 Medium": "4776d370", "P3 Low": "8d4513cf"}
KIND_OPTS = {"Epic": "145c0c4b", "Story": "fb4fecd9", "Task": "d5a979d8",
             "Spike": "967424d9", "Bug": "37fc2d34", "Chore": "3e6c8ac4"}
PHASE_OPTS = {"P0 Foundations": "1e961888", "P1 Core Charting": "8cfde683",
              "P2 Data & Indicators": "1fe8c439", "P3 Drawing & Alerts": "de3de7b2",
              "P4 Backtesting & Scripting": "c406dee0",
              "P5 Collaboration & Polish": "126a3a81", "P6 Moat": "c5409b86"}
RISK_OPTS = {"R1 Data licensing": "e8efbf04", "R2 Render performance": "9f8e4a63",
             "R3 Real-time cost": "bd5153c3", "R4 Script sandbox": "ad90fb7e",
             "R5 Scope": "0a9edb8d", "R6 Feed rot": "7be2903d",
             "R7 Data accuracy": "cbc27898", "R8 Browser/GPU compat": "33774479",
             "R9 Advice boundary": "9975390c", "R10 Key-person": "2734ddb4",
             "R11 Alert reliability": "20a933c9", "R12 Backtest bias": "534a7bfb",
             "R13 Sharing abuse": "360a7593", "R14 User retention": "d6cf675f",
             "R15 Data lifecycle": "64af975e", "None": "bf277967"}
# NOTE: option ids were regenerated 2026-09-24 when Sprint 19-26 were added
# (tickets referenced sprints up to 26; the field previously stopped at 18).
# If this field's options are ever recreated, re-sync these ids from
# `gh api graphql` on the ProjectV2SingleSelectField before re-running publish.
SPRINT_OPTS = {"Sprint %02d" % n: oid for n, oid in zip(range(1, 27), [
    "2e8c279f", "c91e4d6a", "c57153ef", "16ad1fc8", "d58e9e42", "bb4e097a",
    "0aa84dcf", "0ba24ca1", "42db7445", "3cedcdc4", "708b1515", "a303089e",
    "aec79885", "ca2ee1b9", "11462f79", "9652c9fd", "32d21f04", "b3e723eb",
    "0cf7c765", "593bed21", "90fbe95f", "3655bbe0", "a9855e9c", "5ced7cd6",
    "15851268", "1c75f6fd"])}
SPRINT_OPTS["Backlog"] = "9f14c922"
SPRINT_OPTS["Future"] = "0fe844a0"
COMPONENT_OPTS = {"chart-engine": "aadf87be", "data-feeds": "b70f78df",
                  "indicators": "5ad44f2e", "drawing-tools": "51c543c5",
                  "alerts": "4f8fd915", "backtesting": "66c7c709",
                  "scripting": "4442ba04", "web": "798078b6", "api": "8f69e193",
                  "auth": "ca20d78f", "collaboration": "48987c4a",
                  "infra": "899dc903", "docs": "65984978",
                  "cross-cutting": "350fe5c7"}
PERSPECTIVE_OPTS = {"Product": "0a945e30", "Architecture": "e3ed3c9f",
                    "Development": "6a27c7b5", "Test": "d857fe6d", "QA": "da2f6d09",
                    "Security": "f3cd9746", "Compliance": "035119f8",
                    "Ops": "85de895d"}


import re

KEY_SUFFIX_RE = re.compile(r"^E\d{2}-([A-Z])\d{2}$")


def is_design_ticket(key):
    m = KEY_SUFFIX_RE.match(key)
    return bool(m) and m.group(1) == "D"


def compute_status(t, by_key):
    sn = sprint_num_from_label(t.get("sprint"))
    if sn not in (1, 2):
        return "Backlog"
    if is_design_ticket(t["key"]):
        return "Backlog"
    blockers = t.get("blocked_by") or []
    if not blockers:
        return "Ready"
    for bk in blockers:
        bt = by_key.get(bk)
        if bt is None:
            return "Backlog"
        if sprint_num_from_label(bt.get("sprint")) != 1:
            return "Backlog"
    return "Ready"


def compute_rollup(epic_key, by_key, tickets):
    total = 0
    for t in tickets:
        if t.get("parent") == epic_key and "retired" not in (t.get("labels") or []):
            total += t.get("estimate") or 0
    return total


# --------------------------------------------------------------------------
def phase4_project(tickets, ledger, failures):
    by_key = {t["key"]: t for t in tickets}
    live = [t for t in tickets if "retired" not in (t.get("labels") or [])
            and t["key"] in ledger]

    # 4a. add-to-project for any issue missing item_id
    missing = [t for t in live if not ledger[t["key"]].get("item_id")]
    log("phase4a: %d issues need project item-add" % len(missing))
    for idx, t in enumerate(missing):
        key = t["key"]
        number = ledger[key]["number"]
        try:
            out = run([GH, "project", "item-add", PROJECT_NUMBER,
                       "--owner", PROJECT_OWNER, "--url",
                       "https://github.com/%s/issues/%d" % (REPO, number),
                       "--format", "json"])
            item_id = json.loads(out)["id"]
            ledger[key]["item_id"] = item_id
            if (idx + 1) % 20 == 0:
                save_ledger(ledger)
                log("  [%d/%d] added to project" % (idx + 1, len(missing)))
        except RuntimeError as e:
            log("  FAILED item-add %s: %s" % (key, e))
            failures.append({"phase": "4a", "key": key, "error": str(e)})
            save_failures(failures)
    save_ledger(ledger)

    # 4b. set fields
    todo = [t for t in live if not ledger[t["key"]].get("fields_done")
            and ledger[t["key"]].get("item_id")]
    log("phase4b: %d issues need fields set" % len(todo))
    batch = []
    batch_keys = []
    done = 0
    for idx, t in enumerate(todo):
        key = t["key"]
        item_id = ledger[key]["item_id"]
        muts = _field_mutations(t, key, item_id, by_key, tickets)
        safe_key = key.replace("-", "_")
        for j, m in enumerate(muts):
            batch.append(("m%s_%d" % (safe_key, j), m))
        batch_keys.append(key)
        if len(batch) >= 15:
            _flush_field_batch(batch, batch_keys, ledger, failures)
            done += len(batch_keys)
            batch, batch_keys = [], []
            log("  [%d/%d] fields set" % (done, len(todo)))
    if batch:
        _flush_field_batch(batch, batch_keys, ledger, failures)
        done += len(batch_keys)
        log("  [%d/%d] fields set" % (done, len(todo)))
    save_ledger(ledger)
    log("phase4: complete")


def _mk_sso(item_id, field_id, opt_id):
    return ('updateProjectV2ItemFieldValue(input: {projectId: "%s", '
            'itemId: "%s", fieldId: "%s", value: {singleSelectOptionId: "%s"}}) '
            "{ projectV2Item { id } }") % (PROJECT_ID, item_id, field_id, opt_id)


def _mk_number(item_id, field_id, num):
    return ('updateProjectV2ItemFieldValue(input: {projectId: "%s", '
            'itemId: "%s", fieldId: "%s", value: {number: %s}}) '
            "{ projectV2Item { id } }") % (PROJECT_ID, item_id, field_id, num)


def _mk_date(item_id, field_id, iso_date):
    return ('updateProjectV2ItemFieldValue(input: {projectId: "%s", '
            'itemId: "%s", fieldId: "%s", value: {date: "%s"}}) '
            "{ projectV2Item { id } }") % (PROJECT_ID, item_id, field_id, iso_date)


def _field_mutations(t, key, item_id, by_key, tickets):
    muts = []
    status = compute_status(t, by_key)
    if status in STATUS_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Status"], STATUS_OPTS[status]))
    if t.get("kind") in KIND_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Kind"], KIND_OPTS[t["kind"]]))
    if t.get("phase") in PHASE_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Phase"], PHASE_OPTS[t["phase"]]))
    sprint_key = (t.get("sprint") or "").replace("Sprint ", "Sprint ")
    if sprint_key in SPRINT_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Sprint"], SPRINT_OPTS[sprint_key]))
    if t.get("component") in COMPONENT_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Component"],
                             COMPONENT_OPTS[t["component"]]))
    if t.get("priority") in PRIORITY_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Priority"],
                             PRIORITY_OPTS[t["priority"]]))
    if t.get("perspective") in PERSPECTIVE_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Perspective"],
                             PERSPECTIVE_OPTS[t["perspective"]]))
    if t.get("risk") in RISK_OPTS:
        muts.append(_mk_sso(item_id, FIELD_IDS["Risk"], RISK_OPTS[t["risk"]]))

    est = t.get("estimate")
    if t.get("kind") == "Epic":
        est = compute_rollup(key, by_key, tickets)
        muts.append(_mk_number(item_id, FIELD_IDS["Rollup"], est))
    elif est is not None:
        muts.append(_mk_number(item_id, FIELD_IDS["Estimate"], est))

    start, due = sprint_dates(t.get("sprint"))
    if start:
        muts.append(_mk_date(item_id, FIELD_IDS["Start"], start))
    if due:
        muts.append(_mk_date(item_id, FIELD_IDS["Due"], due))
    return muts


def _flush_field_batch(batch, keys, ledger, failures):
    """batch aliases are "m{safe_key}_{j}" — group by ticket key so a
    per-mutation failure only fails that ticket, not the whole flush."""
    ok = graphql_batch_raw(batch, aliases_per_call=15)
    by_key_alias = {}
    for alias, _ in batch:
        safe_key = alias.rsplit("_", 1)[0][1:]
        by_key_alias.setdefault(safe_key, []).append(alias)
    failed_keys = []
    for key in keys:
        safe_key = key.replace("-", "_")
        aliases = by_key_alias.get(safe_key, [])
        if aliases and all(ok.get(a) for a in aliases):
            ledger[key]["fields_done"] = True
        else:
            failed_keys.append(key)
    save_ledger(ledger)
    if failed_keys:
        log("  FAILED field sets: %s" % failed_keys)
        failures.append({"phase": "4b", "keys": failed_keys})
        save_failures(failures)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2", "3", "4", "all"],
                     default="all")
    args = ap.parse_args()

    tickets = load_tickets()
    ledger = load_ledger()
    failures = load_failures()

    phases = {"1": phase1_create, "2": phase2_subissues,
              "3": phase3_blockedby, "4": phase4_project}
    if args.phase == "all":
        for p in ("1", "2", "3", "4"):
            phases[p](tickets, ledger, failures)
    else:
        phases[args.phase](tickets, ledger, failures)

    created = sum(1 for v in ledger.values() if v.get("number"))
    subissues = sum(1 for v in ledger.values() if v.get("subissue_done"))
    fields = sum(1 for v in ledger.values() if v.get("fields_done"))
    blockedby_edges = sum(len(v.get("blockedby_done") or [])
                           for v in ledger.values())
    log("\n=== SUMMARY ===")
    log("issues created: %d" % created)
    log("sub-issue links: %d tickets marked done" % subissues)
    log("blocked-by edges linked: %d" % blockedby_edges)
    log("items with fields set: %d" % fields)
    log("failures: %d (see %s)" % (len(failures), FAILURES_PATH))
    log("ledger: %s" % LEDGER_PATH)


if __name__ == "__main__":
    main()
