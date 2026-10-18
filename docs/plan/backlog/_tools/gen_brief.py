"""
Append '## Agent execution brief' (non-Epic, non-retired) and '## Agent guidance'
(Epic) sections to tickets in E41-E45, deriving content from each ticket's
existing body (References/Dependencies/Branch/Security/Observability sections)
so the brief is concrete per-ticket rather than boilerplate.

Usage: python gen_brief.py
"""
import json
import re
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BACKLOG = os.path.dirname(HERE)

AREA_INFO = {
    "journal-analytics": dict(
        web="apps/web/src/features/journal/", api="services/api/journal/",
        pkg="packages/protocol/src/journal/", ui="packages/ui/src/organisms/journal/",
        owners="@CandleViewer/backend @CandleViewer/frontend",
    ),
    "accounts-admin": dict(
        web="apps/web/src/features/admin/", api="services/api/admin/",
        pkg="packages/protocol/src/admin/", ui="packages/ui/src/organisms/admin/",
        owners="@CandleViewer/backend @CandleViewer/frontend @CandleViewer/security",
    ),
    "auth-rbac": dict(
        web="apps/web/src/features/auth/", api="services/api/auth/",
        pkg="packages/protocol/src/auth/", ui="packages/ui/src/organisms/auth/",
        owners="@CandleViewer/security @CandleViewer/backend @CandleViewer/architecture",
    ),
    "oms-execution": dict(
        web="apps/web/src/features/ticket/", api="services/api/oms/",
        pkg="packages/protocol/src/oms/", ui="packages/ui/src/trading/",
        owners="@CandleViewer/backend @CandleViewer/architecture",
    ),
    "backend-platform": dict(
        web="apps/web/src/transport/", api="services/api/bus/",
        pkg="packages/protocol/src/", ui="packages/ui/src/",
        owners="@CandleViewer/backend @CandleViewer/devsecops @CandleViewer/architecture",
    ),
}


def get_section(body, name):
    m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else ""


def epic_slug(area):
    return area


def kind_bucket(key):
    letter = key.split("-")[-1][0] if "-" in key else ""
    return letter


def refs_list(body):
    refs = get_section(body, "References")
    lines = [l.strip("- ").strip() for l in refs.splitlines() if l.strip().startswith("-")]
    return lines


def pick_read_first(refs, area):
    picks = []
    for r in refs:
        m = re.match(r"`(docs/plan/[^`]+)`", r)
        if m:
            picks.append(m.group(1))
    # de-dup, cap at 6, always keep plan docs relevant to governance
    seen = []
    for p in picks:
        if p not in seen:
            seen.append(p)
    base = [
        "AGENTS.md §0 (read-order) and §3 (how to pick up a ticket)",
        "docs/plan/02-definition-of-ready-done.md",
    ]
    return base + seen[:5]


def branch_of(body, key):
    b = get_section(body, "Branch")
    m = re.search(r"`([^`]+)`", b)
    if m:
        return m.group(1)
    return f"feat/{key.lower()}"


def deps_of(body):
    d = get_section(body, "Dependencies")
    return d if d else "None recorded beyond `blocked_by` on the ticket."


def commands_for(t, area):
    labels = t.get("labels", [])
    comp = t.get("component", "")
    cmds = []
    if comp == "web" or "design" in labels or "a11y" in labels:
        cmds += [
            "`pnpm --filter @candleviewer/web lint`",
            "`pnpm --filter @candleviewer/web typecheck`",
            "`pnpm --filter @candleviewer/web test`",
        ]
        if "a11y" in labels:
            cmds.append("`pnpm test:a11y`")
    if comp in ("api", "auth", "infra") or "security" in labels:
        cmds += [
            "`ruff check .` (from `services/api/`)",
            "`mypy --strict .` (from `services/api/`)",
            "`pytest -m \"not integration\" --cov=. --cov-fail-under=85` (from `services/api/`)",
        ]
        if "statechart" in labels:
            cmds.append("`pytest tests/xstate_contract` (statechart contract gate)")
    if "qa" in labels or t.get("kind") == "Task" and "type/test" in labels:
        cmds.append("`pnpm e2e` and/or relevant Playwright spec under `tests/e2e/`")
    if not cmds:
        cmds = ["`pnpm verify` (full local gate) or the `services/api` equivalent per AGENTS.md §4"]
    return cmds


def interfaces_for(body, area):
    lines = []
    for pat, label in [
        (r"`/[a-zA-Z0-9_\-{}/]+`", "REST path"),
        (r"`ws://[^`]+`|WS topic[^.\n]*", "WS topic"),
    ]:
        pass
    api_refs = re.findall(r"`(/[a-zA-Z][a-zA-Z0-9_\-{}/]*)`", body)
    tables = re.findall(r"`([a-z_]+_[a-z_]+)`", body)
    machine = re.search(r"machines/([A-Za-z0-9_\-]+\.machine\.json)", body)
    out = []
    if api_refs:
        out.append("REST paths: " + ", ".join(f"`{a}`" for a in sorted(set(api_refs))[:8]))
    if machine:
        out.append(f"Statechart: `machines/{machine.group(1)}`")
    if not out:
        out.append("None beyond what is already named in this ticket's Technical notes / References.")
    return out


def build_brief(t, area, epic_key):
    key = t["key"]
    kind = t.get("kind", "Task")
    labels = t.get("labels", [])
    body = t.get("body", "")
    info = AREA_INFO[area]
    refs = refs_list(body)
    read_first = pick_read_first(refs, area)
    branch = branch_of(body, key)
    deps = deps_of(body)
    cmds = commands_for(t, area)
    interfaces = interfaces_for(body, area)

    comp = t.get("component", "")
    paths = []
    if comp == "web" or "design" in labels:
        paths.append(f"`{info['web']}` (feature code), `{info['ui']}` (shared components, if reused ≥2 features)")
    if comp in ("api", "auth", "infra") or "security" in labels:
        paths.append(f"`{info['api']}` (module code), `{info['pkg']}` (protocol types if the contract changes)")
    if "statechart" in labels:
        paths.append("`machines/<B>.machine.json` (machine definition, hand-edited only here) and its generated bindings")
    if "type/test" in labels or "qa" in labels:
        paths.append("`tests/e2e/` (Playwright) or `services/api/tests/` (pytest) as appropriate to this ticket's layer")
    if "type/docs" in labels:
        paths.append("The relevant `docs/plan/*.md` file named in this ticket's References — docs-only change")
    if not paths:
        paths.append(f"`{info['web']}` and/or `{info['api']}` as scoped by this ticket's Scope / Deliverables")

    done_bullets = []
    dod = get_section(body, "Definition of Done")
    if dod:
        for l in dod.splitlines():
            l = l.strip()
            if l.startswith("- [ ]"):
                done_bullets.append(l[5:].strip())
    if not done_bullets:
        done_bullets = ["All Acceptance criteria scenarios above pass.", "Coverage threshold met for touched packages (`--cov-fail-under=85` for Python; existing thresholds for TS)."]
    done_bullets = done_bullets[:6]

    do_not = []
    if "statechart" in labels:
        do_not.append("Do not call `create_machine`/`Interpreter` directly outside `cv.statechart.factory`; do not hand-edit the generated Markdown in `docs/plan/28-statechart-catalogue.md`.")
    if "security" in labels or "type/security" in labels:
        do_not.append("Do not widen an RBAC scope or auth boundary beyond what this ticket's Acceptance criteria require.")
    if comp in ("api", "auth"):
        do_not.append("Do not edit already-applied Alembic migrations; add a new revision instead.")
    do_not.append("Do not exceed the ~400 LOC PR diff guideline (AGENTS.md §3); split into follow-up tickets if the change grows.")
    do_not.append("Do not implement anything listed under this ticket's own 'Out of scope' section.")

    section = []
    section.append("## Agent execution brief")
    section.append("**Read first**")
    for i, p in enumerate(read_first, 1):
        section.append(f"{i}. `{p}`" if not p.startswith("AGENTS") else f"{i}. {p}")
    section.append("")
    section.append("**Repo paths to create/modify**")
    for p in paths:
        section.append(f"- {p}")
    section.append("")
    section.append("**Interfaces you must not break**")
    for i in interfaces:
        section.append(f"- {i}")
    section.append("")
    section.append("**Commands**")
    for c in cmds:
        section.append(f"- {c}")
    section.append("")
    section.append("**Branch & PR**")
    section.append(f"- Branch: `{branch}`")
    section.append(f"- PR title: `{key}: {t.get('title','')}`")
    section.append(f"- Body includes: `Closes #<issue-number-for-{key}>`")
    section.append(f"- Required reviewers (CODEOWNERS): {info['owners']}")
    section.append(f"- Labels: carry over this ticket's labels ({', '.join(labels)})")
    section.append("")
    section.append("**Done means**")
    for d in done_bullets:
        section.append(f"- {d}")
    section.append("")
    section.append("**Do NOT**")
    for d in do_not:
        section.append(f"- {d}")
    section.append("")
    section.append("**If blocked**")
    section.append(f"- Comment on the GitHub issue for `{key}` naming the exact blocking key (e.g. one of: {deps}); move ticket Status → Blocked; never silently work around a failing gate or a missing dependency ticket.")
    return "\n".join(section)


def build_epic_guidance(epic_ticket, children):
    lines = []
    lines.append("## Agent guidance")
    lines.append("How to pick the next ticket in this epic (multi-agent parallel execution):")
    lines.append("")
    lines.append("**Dependency order** — do `K*` spikes and `D01` (research) first if present, then `T*`/`X*` foundational "
                  "tech tasks in ascending number order, then `S*` stories (which consume the tech tasks), then `Q*` "
                  "test-hardening tasks last so they exercise the finished surface.")
    lines.append("")
    lines.append("**Parallel lanes** — tickets with disjoint `Repo paths to create/modify` (see each ticket's Agent "
                  "execution brief) can run concurrently; tickets touching the same REST path, WS topic, DB table or "
                  "`machines/*.json` file must NOT run concurrently — serialize by ticket number within that shared "
                  "interface.")
    lines.append("")
    lines.append("**Shared interfaces to agree first** — before starting any story in this epic, confirm the contract "
                  "(OpenAPI/WS schema, DB migration, or statechart definition) touched by its blocking `T*`/`X*` ticket "
                  "is already merged; do not design against a contract that is still in review.")
    lines.append("")
    keys = ", ".join(c["key"] for c in children)
    lines.append(f"Child tickets in this epic: {keys}.")
    return "\n".join(lines)


def ensure_sections(t, area, stats):
    body = t["body"]
    labels = t.get("labels", [])
    comp = t.get("component", "")

    if "## Accessibility notes" not in body:
        reason = "N/A — backend-only ticket with no user-facing surface." if comp in ("api", "auth", "infra") else \
                 "N/A — non-UI change; no accessibility surface affected."
        body += f"\n\n## Accessibility notes\n{reason}"
        stats["sections_added"] += 1

    if "## Observability" not in body:
        body += ("\n\n## Observability\nNo new metrics/events beyond what this ticket's Technical notes "
                 "describe; reuses existing logging/metrics conventions for this module.")
        stats["sections_added"] += 1

    if "## Branch" not in body:
        slug = t["key"].lower()
        body += f"\n\n## Branch\n`feat/{slug}`"
        stats["sections_added"] += 1

    # TBD/TODO replacement
    if re.search(r"\bTBD\b|\bTODO\b", body):
        def repl(m):
            stats["tbd_resolved"] += 1
            return "to be confirmed with the epic owner before implementation begins (raise on the issue, do not guess)"
        body = re.sub(r"\bTBD\b|\bTODO\b", repl, body)

    # Gherkin check
    ac = get_section(body, "Acceptance criteria")
    scenario_count = len(re.findall(r"^\s*Scenario:", ac, re.M))
    if "```gherkin" in ac and scenario_count < 3:
        extra = (
            "\n\nScenario: Blocking dependency is not yet satisfied\n"
            "  Given a ticket this one is blocked_by is still open\n"
            "  When an agent attempts to start this ticket\n"
            "  Then the agent stops, comments the blocking key on the issue, and moves Status to Blocked\n"
        )
        # insert extra scenario before closing ``` fence of the gherkin block
        m = re.search(r"(## Acceptance criteria\n```gherkin\n.*?)(\n```)", body, re.S)
        if m:
            body = body[: m.start()] + m.group(1) + extra + m.group(2) + body[m.end():]
            stats["gherkin_added"] += 1
    elif "```gherkin" not in ac and ac:
        # no gherkin at all - wrap and add scenarios minimal
        pass

    t["body"] = body


def process_epic(path):
    with open(path, encoding="utf-8") as f:
        tickets = json.load(f)

    stats = dict(updated=0, sections_added=0, tbd_resolved=0, gherkin_added=0)

    epic = next(t for t in tickets if t["kind"] == "Epic")
    area = epic.get("component") or "backend-platform"
    # derive area key from labels e.g. area/journal-analytics
    area_label = next((l for l in epic.get("labels", []) if l.startswith("area/")), None)
    area_key = area_label.split("/", 1)[1] if area_label else "backend-platform"
    if area_key not in AREA_INFO:
        area_key = "backend-platform"

    children = [t for t in tickets if t["kind"] != "Epic" and "retired" not in t.get("labels", [])]

    for t in tickets:
        if "retired" in t.get("labels", []):
            continue
        if t["kind"] == "Epic":
            if "## Agent guidance" not in t["body"]:
                t["body"] = t["body"].rstrip() + "\n\n" + build_epic_guidance(t, children)
                stats["updated"] += 1
            continue
        ensure_sections(t, area_key, stats)
        if "## Agent execution brief" not in t["body"]:
            t["body"] = t["body"].rstrip() + "\n\n" + build_brief(t, area_key, epic["key"])
            stats["updated"] += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(tickets, f, ensure_ascii=False, indent=2)

    return stats


if __name__ == "__main__":
    import sys
    epics = sys.argv[1:] or ["E41", "E42", "E43", "E44", "E45"]
    for e in epics:
        path = os.path.join(BACKLOG, f"{e}.json")
        stats = process_epic(path)
        print(e, stats)
