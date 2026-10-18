import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from brief_config_e46_50 import COMPONENT_READS, CODEOWNER_PATHS, REVIEWERS, COMMANDS


def extract_section(body, name):
    m = re.search(rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else ""


def first_line(text, default=""):
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return default


def branch_name(body, key):
    sec = extract_section(body, "Branch")
    m = re.search(r"`([^`]+)`", sec)
    if m:
        return m.group(1)
    return f"feat/{key.lower()}-work"


def done_bullets(body):
    sec = extract_section(body, "Definition of Done")
    bullets = re.findall(r"^- \[ \] (.+)$", sec, re.M)
    return bullets[:6] if bullets else ["See ## Definition of Done above."]


def scope_traps(body):
    out = extract_section(body, "Out of scope")
    bullets = re.findall(r"^- (.+)$", out, re.M)
    return bullets


def statechart_hint(t):
    labels = t.get("labels") or []
    if "statechart" not in labels:
        return None
    return (
        "Scope names `machines/<B>.machine.json`, its `bindings/` module, "
        "`tests/xstate_contract/` entry, and the mandatory config block reference "
        "(docs/plan/28-statechart-catalogue.md §1.3c); do not touch other machines' files."
    )


def interfaces_not_break(t, body):
    ifaces = []
    if "api" in (t.get("component") or ""):
        ifaces.append("REST endpoints under `docs/plan/22-api-openapi.yaml` touched by this ticket (regenerate `packages/protocol`, never hand-edit)")
    if "23-ws-protocol" in body or "ws-protocol.md" in body or "fan-out" in body.lower() or "WS tick" in body:
        ifaces.append("WS topics/framing in `docs/plan/23-ws-protocol.md` (contract-first per C-6.1)")
    if statechart_hint(t):
        ifaces.append("Machine events/services named in `docs/plan/28-statechart-catalogue.md` for this ticket's Bn entry")
    if "questdb" in body.lower() or "postgres" in body.lower():
        ifaces.append("DB tables named in `docs/plan/21-database-schema.md` (no schema change without a reviewed migration)")
    if not ifaces:
        ifaces.append("Public exports of the package(s) this ticket touches (no widening of package APIs without an ADR)")
    return ifaces


def repo_paths(t):
    comp = t.get("component") or "cross-cutting"
    base = CODEOWNER_PATHS.get(comp, "/docs/plan/")
    paths = [base]
    if statechart_hint(t):
        paths.append("services/api/candleviewer/statechart/machines/<B>.machine.json")
        paths.append("services/api/candleviewer/statechart/bindings/<module>.py")
        paths.append("tests/xstate_contract/<machine>/")
    if comp == "docs":
        paths.append("docs/runbooks/ or docs/plan/ per ticket Scope")
    return paths


def read_first(t):
    comp = t.get("component") or "cross-cutting"
    reads = list(COMPONENT_READS.get(comp, COMPONENT_READS["cross-cutting"]))
    return reads[:6]


def commands_for(t):
    comp = t.get("component") or "cross-cutting"
    return COMMANDS.get(comp, COMMANDS["cross-cutting"])


def build_brief(t):
    key = t["key"]
    title = t["title"]
    body = t["body"]
    comp = t.get("component") or "cross-cutting"
    branch = branch_name(body, key)
    reviewer = REVIEWERS.get(comp, "@CandleViewer/architecture")
    codeowner_path = CODEOWNER_PATHS.get(comp, "/docs/plan/")
    reads = read_first(t)
    paths = repo_paths(t)
    ifaces = interfaces_not_break(t, body)
    cmds = commands_for(t)
    dones = done_bullets(body)
    traps = scope_traps(body)
    sc = statechart_hint(t)

    lines = []
    lines.append("## Agent execution brief")
    lines.append("")
    lines.append("**Read first**")
    for i, r in enumerate(reads, 1):
        lines.append(f"{i}. {r}")
    lines.append("")
    lines.append("**Repo paths to create/modify**")
    for p in paths:
        lines.append(f"- `{p}`" if not p.startswith("/") else f"- `{p.strip('/')}` (owner: {reviewer})")
    lines.append("")
    lines.append("**Interfaces you must not break**")
    for i in ifaces:
        lines.append(f"- {i}")
    lines.append("")
    lines.append("**Commands**")
    for c in cmds:
        lines.append(f"- `{c}`")
    lines.append("")
    lines.append("**Branch & PR**")
    lines.append(f"- Branch: `{branch}`")
    lines.append(f'- PR title: "{key}: {title}"')
    lines.append(f"- Body includes: `Closes #<issue-for-{key}>`")
    lines.append(f"- Required reviewers: CODEOWNERS for `{codeowner_path}` ({reviewer}); 2 approvals minimum (C-10.1)")
    lines.append(f"- Labels: carry over this ticket's labels: {', '.join(t.get('labels') or [])}")
    lines.append("")
    lines.append("**Done means**")
    for d in dones:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("**Do NOT**")
    if traps:
        for tr in traps:
            lines.append(f"- {tr}")
    else:
        lines.append("- Expand scope beyond this ticket's Scope/Deliverables section; file a new ticket instead.")
    lines.append("- Widen any package's public API or add a dependency without a linked ADR.")
    if sc:
        lines.append(f"- {sc}")
    lines.append("")
    lines.append("**If blocked**")
    lines.append(f"- Comment on the `{key}` GitHub issue naming the exact blocking condition (failing gate, missing decision, unmet dependency); move issue Status to `Blocked`; never silently work around a failing gate or merge with a required check disabled.")
    return "\n".join(lines)


def build_epic_guidance(t, children):
    key = t["key"]
    lines = []
    lines.append("## Agent guidance")
    lines.append("")
    lines.append(f"Multiple agents will work {key}'s children in parallel. To pick the next ticket:")
    lines.append("")
    lines.append("1. Respect `blocked_by` on each child ticket — do not start a ticket whose blockers are not yet Done.")
    lines.append("2. Prefer the epic's own dependency graph (see `## Child dependency graph` / `## Children — dependency graph` section above) over guessing from titles.")
    lines.append("3. Design (`-D0x`) and Spike (`-K0x`) tickets generally gate their dependent Story/Task tickets — pick those first if unblocked.")
    lines.append("4. QA (`-Q0x`) and Security (`-X0x`) tickets are epic-closing; they depend on most Task/Story work and should be picked last.")
    lines.append("5. Two agents must not take tickets that both modify the same non-generated file; check open PRs/branches for path overlap before starting.")
    lines.append("6. Shared interfaces to agree before parallel work starts: any WS/REST contract change, any shared machine.json under `services/api/candleviewer/statechart/machines/`, and any shared design-system token — post in the ticket comments before changing.")
    return "\n".join(lines)


def process_file(fname):
    with open(fname, encoding="utf-8") as f:
        data = json.load(f)
    updated = 0
    for t in data:
        if "retired" in (t.get("labels") or []):
            continue
        if t["kind"] == "Epic":
            if "## Agent guidance" in t["body"]:
                continue
            t["body"] = t["body"].rstrip("\n") + "\n\n" + build_epic_guidance(t, data) + "\n"
            updated += 1
        else:
            if "## Agent execution brief" in t["body"]:
                continue
            t["body"] = t["body"].rstrip("\n") + "\n\n" + build_brief(t) + "\n"
            updated += 1
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return updated


if __name__ == "__main__":
    import sys
    fname = sys.argv[1]
    n = process_file(fname)
    print(fname, "updated", n)
