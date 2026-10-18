#!/usr/bin/env python3
"""Append '## Agent execution brief' to every live non-Epic ticket in E36..E40.

Run: python add_briefs.py
"""
from __future__ import annotations
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
BACKLOG = os.path.dirname(HERE)
EPICS = ["E36", "E37", "E38", "E39", "E40"]

# ---------------------------------------------------------------------------
# Per-epic static context
# ---------------------------------------------------------------------------
EPIC_READ = {
    "E36": [
        "docs/plan/28-statechart-catalogue.md §1.3c (FINAL mandatory machine config)",
        "docs/plan/14-screens-catalogue.md SCR-080, SCR-081, SCR-083, SCR-088, SCR-089",
        "docs/plan/15-component-catalogue.md CMP-146, CMP-157, CMP-234",
        "docs/plan/11-user-stories.md §20 RULE (US-RULE-001..007)",
        "docs/plan/20-architecture.md (packages/rule-editor-core placement)",
        "docs/plan/05-accessibility-standard.md",
    ],
    "E37": [
        "docs/plan/14-screens-catalogue.md SCR-082",
        "docs/plan/15-component-catalogue.md CMP-146 (accessible-equivalent mandate)",
        "docs/plan/11-user-stories.md §20 RULE (US-RULE-001, US-RULE-006)",
        "docs/adr/ (ADR-0007 addendum on graph-only constructs, E37-T03)",
        "docs/plan/20-architecture.md (packages/rule-graph placement)",
        "docs/plan/06-performance-and-load-standard.md (200-node/60fps budget)",
    ],
    "E38": [
        "docs/plan/24-internal-schemas.md (environment capability matrix)",
        "docs/plan/22-api-openapi.yaml (paper/environment endpoints)",
        "docs/plan/14-screens-catalogue.md SCR-074, SCR-075, SCR-099",
        "docs/plan/28-statechart-catalogue.md §B (paper matcher machine, for E38-S03)",
        "docs/plan/04-security-program.md (demo/live isolation controls)",
        "docs/plan/20-architecture.md (services/api/paper placement)",
    ],
    "E39": [
        "docs/plan/28-statechart-catalogue.md §B20 (risk lockout), kill-switch machine",
        "docs/plan/29-statechart-adoption-plan.md §1.2, §3 (mandatory config, hot-path exclusions)",
        "docs/plan/27-adrs/ADR-0016-statechart-runtime.md",
        "docs/plan/22-api-openapi.yaml (/risk/lockouts, /killswitch)",
        "docs/plan/24-internal-schemas.md §11-§12 (risk schemas, step-up list)",
        "docs/plan/04-security-program.md SR-025",
    ],
    "E40": [
        "docs/plan/28-statechart-catalogue.md (alert evaluator machine, E40-T03)",
        "docs/plan/14-screens-catalogue.md SCR-090, SCR-091, SCR-092, SCR-014, SCR-115",
        "docs/plan/23-ws-protocol.md (alerts WS topic)",
        "docs/plan/22-api-openapi.yaml (alert CRUD, deliveries)",
        "docs/plan/24-internal-schemas.md (0009_alerts migration)",
        "docs/plan/04-security-program.md (webhook egress allow-list)",
    ],
}

EPIC_INTERFACES = {
    "E36": "IR schema/compiler/validator endpoints (owned by E35, consumed read-only); "
           "vocabulary endpoint `GET /api/v1/rules/vocabulary`; rule CRUD `/api/v1/rules`; "
           "no changes to the IR schema itself.",
    "E37": "Same IR schema/compiler/validator endpoints as E36 (owned by E35); "
           "graph<->IR adapter contract in `packages/rule-graph`; round-trip hash must match E36's form editor.",
    "E38": "`POST /api/v1/session/environment` (env switch), `/api/v1/paper/*` (paper matcher), "
           "environment capability matrix in `services/api/exchange/base/`; WS resubscription protocol.",
    "E39": "`/api/v1/risk/lockouts/{accountId}/override`, `/api/v1/killswitch/*`, "
           "`risk_lockouts`/`risk_policy`/`kill_switch_state` Postgres tables, "
           "`SystemUpdate` WS frame (`23-ws-protocol.md` §15.9), OMS cancel-all/reduce-only paths.",
    "E40": "`0009_alerts` migration tables, alert CRUD `/api/v1/alerts`, deliveries API, "
           "`alerts` WS topic, webhook egress allow-list.",
}

EPIC_BRANCH_SLUG = {
    "E36": "e36-rule-form-editor",
    "E37": "e37-rule-node-graph",
    "E38": "e38-paper-trading",
    "E39": "e39-risk-killswitch",
    "E40": "e40-alerts",
}

EPIC_REVIEWERS = {
    "E36": "@CandleViewer/frontend (apps/web, packages/rule-editor-core), @CandleViewer/design-system (packages/ui), @CandleViewer/qa for Q-tickets, @CandleViewer/security for X-tickets",
    "E37": "@CandleViewer/frontend (apps/web, packages/rule-graph), @CandleViewer/chart-engine if canvas primitives are touched, @CandleViewer/qa for Q-tickets",
    "E38": "@CandleViewer/backend (services/api/paper, exchange/base) + @CandleViewer/security (environment isolation is security-owned), @CandleViewer/frontend for web-component tickets",
    "E39": "@CandleViewer/backend + @CandleViewer/security (services/api/risk, services/api/oms are dual-owned per CODEOWNERS), @CandleViewer/frontend for D/S04/S05 web tickets",
    "E40": "@CandleViewer/backend (services/api/alerts) + @CandleViewer/security for webhook egress, @CandleViewer/frontend for S01/S02",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def repo_paths_for(epic: str, key: str, title: str, component: str, labels: list[str]) -> list[str]:
    suffix = key.split("-")[1] if "-" in key else ""
    kindletter = suffix[0] if suffix else ""
    paths: list[str] = []

    if epic == "E36":
        paths.append("apps/web/src/features/rules/form/ (editor page, condition rows, action rows)")
        if kindletter == "T":
            paths.append("packages/rule-editor-core/src/ (form model, IR adapter, vocabulary cache, diagnostics anchoring)")
        if kindletter == "D":
            paths.append("docs/design/rule-form-editor/ (specs, handoff pack) — no app code")
        if "S03" in key:
            paths.append("apps/web/src/features/rules/inspector/ (SCR-088 IR inspector, read-only summary card)")
        if "S04" in key:
            paths.append("apps/web/src/features/rules/templates/ (SCR-083 gallery)")
        if "S05" in key:
            paths.append("apps/web/src/features/rules/list/ (SCR-080 rules list)")
        if "S06" in key:
            paths.append("apps/web/src/features/rules/import-export/ (SCR-089)")
        if kindletter == "Q":
            paths.append("tests/e2e/rules/ (Playwright), apps/web/tests/ (unit/RTL), tests/fixtures/rules/")
        if kindletter == "X":
            paths.append("apps/web/src/features/rules/ (abuse-case fixes), docs/security/threat-models/rule-authoring.md")
        if kindletter == "T" and "T02" in key:
            paths = ["docs/plan/ (reconciliation only, no app code)", "CHANGELOG.md"]

    elif epic == "E37":
        paths.append("apps/web/src/features/rules/graph/ (canvas, nodes, ports, edges)")
        if kindletter == "T":
            paths.append("packages/rule-graph/src/ (graph<->IR adapter, typed ports, analysis)")
        if kindletter == "D":
            paths.append("docs/design/rule-node-graph/ (specs, handoff pack) — no app code")
        if kindletter == "K":
            paths.append("packages/rule-graph/spike/ (throwaway prototype, findings doc under docs/research/)")
        if "T02" in key:
            paths.append("apps/web/src/features/rules/graph/layout/ (auto-layout, search, minimap)")
        if "T03" in key:
            paths = ["docs/plan/28-statechart-catalogue.md (addendum only)", "docs/adr/ADR-0007-*.md"]
        if kindletter == "Q":
            paths.append("tests/e2e/rules-graph/ (Playwright web+Electron), tests/fixtures/rules/round-trip-corpus/")
        if kindletter == "X":
            paths.append("apps/web/src/features/rules/graph/ (abuse-case fixes), docs/security/threat-models/rule-graph.md")

    elif epic == "E38":
        if component == "api":
            paths.append("services/api/paper/ (matcher, environment routing)")
            if "S01" in key or "T01" in key:
                paths.append("services/api/exchange/base/ (capability matrix), services/api/exchange/bybit/ (demo host routing)")
            if "S02" in key or "T02" in key:
                paths.append("services/api/auth/ (step-up), services/api/http/middleware/ (environment isolation)")
            if "K01" in key:
                paths.append("docs/research/ (findings only, no production code)")
        elif component == "backtesting":
            paths.append("services/api/paper/matcher/ (queue, latency, fee models), machines/ (B-series matcher machine if statechart-labelled)")
            if "T03" in key:
                paths.append("services/api/paper/fidelity/ (nightly divergence job)")
        elif component == "web":
            paths.append("apps/web/src/features/paper/ (environment switcher, chrome, parity report, reset, eligibility UI)")
        elif component == "auth":
            paths.append("services/api/auth/eligibility.py, services/api/accounts/ (per-user demo/live grants)")
        elif component == "cross-cutting":
            paths.append("tests/e2e/paper/, tests/load/, tests/chaos/, docs/security/threat-models/paper-trading.md")
        if kindletter == "D":
            paths.append("docs/design/paper-trading/ (specs, handoff pack) — no app code")

    elif epic == "E39":
        if component == "api":
            paths.append("services/api/risk/ (evaluator, lockout, kill-switch)")
            if "statechart" in labels:
                paths.append("machines/B20.risk_lockout.machine.json (or kill-switch equivalent), statechart/bindings/, tests/xstate_contract/")
            if "T02" in key:
                paths.append("services/api/storage/migrations/ (risk_lockouts, risk_policy, kill_switch_state tables)")
        elif component == "web":
            paths.append("apps/web/src/features/risk/ (dashboard SCR-071, lockout notice SCR-073, kill-switch modal SCR-072, risk policy SCR-134)")
        elif component == "infra":
            paths.append("tests/load/, tests/chaos/ (risk evaluation + kill-switch propagation scenarios)")
        if kindletter == "D":
            paths.append("docs/design/risk-killswitch/ (specs, handoff pack) — no app code")
        if kindletter == "K":
            paths.append("docs/research/ (findings only: authoritative daily-PnL source)")
        if "T03" in key:
            paths = ["docs/adr/ADR-0016-*.md (risk enforcement model)", "docs/runbooks/flatten-all.md", "docs/plan/ (doc updates)"]

    elif epic == "E40":
        if component == "web":
            paths.append("apps/web/src/features/alerts/ (SCR-090 centre, SCR-091 editor, SCR-092/SCR-014 toasts, SCR-115 preferences)")
        elif component == "alerts" or component == "api":
            paths.append("services/api/alerts/ (evaluator, compiler, dispatcher, CRUD, storage/migrations/0009_alerts)")
            if "T03" in key:
                paths.append("machines/ (alert evaluator machine, statechart-labelled), statechart/bindings/, tests/xstate_contract/")
            if "S03" in key:
                paths.append("services/api/alerts/webhook.py (HMAC signing, egress allow-list)")
        if kindletter == "D":
            paths.append("docs/design/alerts/ (specs, handoff pack) — no app code")
        if kindletter == "K":
            paths.append("docs/research/ (findings only: evaluation placement, storm thresholds)")
        if "T05" in key:
            paths = ["docs/plan/ (reconciliation only)", "CHANGELOG.md"]

    if not paths:
        paths.append(f"apps/web/src/features/{('rules' if epic in ('E36','E37','E40') else 'risk')}/ or services/api/ per component={component}")
    return paths


def commands_for(component: str, epic: str) -> list[str]:
    cmds = []
    if component in ("web", "cross-cutting") or epic in ("E36", "E37"):
        cmds += [
            "`pnpm --filter @candleviewer/web test`",
            "`pnpm lint` && `pnpm typecheck`",
        ]
    if component in ("api", "backtesting", "auth", "alerts", "infra") or epic in ("E38", "E39", "E40"):
        cmds += [
            "`cd services/api && ruff check . && black --check . && mypy --strict .`",
            "`cd services/api && pytest -m \"not integration\" --cov=. --cov-fail-under=85`",
        ]
    cmds.append("`pnpm verify` (full local gate before opening the PR)")
    return cmds


def scenario_titles(body: str) -> list[str]:
    m = re.search(r"## Acceptance criteria\n```gherkin\n(.*?)```", body, re.S)
    if not m:
        return []
    return re.findall(r"Scenario(?:\s*\([^)]*\))?:\s*(.+)", m.group(1))


def done_means_for(key: str, kindletter: str, body: str) -> list[str]:
    scens = scenario_titles(body)
    bullets = []
    if scens:
        bullets.append(f"All {len(scens)} Gherkin scenarios above pass as automated tests (unit/contract/E2E as appropriate).")
    cov = re.search(r"[Cc]overage\s*[≥>=]{1,2}\s*(\d+)\s*%", body)
    if cov:
        bullets.append(f"Coverage ≥{cov.group(1)}% on the touched package(s); CI green.")
    else:
        bullets.append("Coverage meets the package's existing threshold (85% API / package-level web target); CI green.")
    if kindletter in ("S", "T"):
        bullets.append("Contract docs (OpenAPI/WS/internal-schemas) updated in the same PR if any surface changed.")
    if "statechart" in body.lower() and "machine_hash" in body:
        bullets.append("`machine_hash` committed to `machine_hashes.lock`; `tools/lint_statecharts.py` and `tests/xstate_contract/` green.")
    bullets.append("Diff ≤400 LOC (or split into the PRs named in the ticket's own Branch section); PR template fully completed.")
    bullets.append("QA/security/a11y sign-off recorded per this ticket's own Test plan / Security notes / Accessibility notes sections.")
    return bullets


def do_not_for(epic: str, key: str, kindletter: str, component: str) -> list[str]:
    items = []
    if epic in ("E39", "E40") and ("statechart" in "" or True):
        pass
    if epic == "E39":
        items.append("Do not hand-roll lockout/kill-switch state as ad-hoc booleans — the lifecycle must go through `cv.statechart.factory.build(...)`, never a direct `create_machine`/`Interpreter` call outside `statechart/`.")
        items.append("Do not accept a client-supplied `until`/expiry timestamp for a lockout or kill-switch release — it is always server-computed.")
        items.append("Do not widen who can clear a lockout or kill-switch beyond the owner with a valid step-up token.")
    if epic == "E38":
        items.append("Do not let any code path submit a live order while the session is scoped to the demo environment, or vice versa — the isolation boundary is enforced server-side, not just in the UI.")
        items.append("Do not skip the step-up re-authentication or full WS resubscription on environment switch.")
    if epic == "E40":
        items.append("Do not let the alert evaluator place or modify orders — alerts are notify-only.")
        items.append("Do not allow webhook delivery to an address outside the configured egress allow-list.")
    if epic in ("E36", "E37"):
        items.append("Do not duplicate or reimplement IR validation/compilation logic that belongs to E35 — call its endpoints.")
        items.append("Do not let the form/graph editor produce an IR that fails E35's validator; treat validator diagnostics as the single source of truth.")
        if epic == "E37":
            items.append("Do not regress the form editor's read-only rendering of graph-only constructs (SCR-081) when the graph is saved.")
    if kindletter == "D":
        items.append("Do not write application code in this ticket — deliverables are design artifacts (specs/handoff pack) only.")
    if kindletter == "K":
        items.append("Do not ship the spike's throwaway prototype code to production paths — only the findings/decision doc is a deliverable.")
    if not items:
        items.append("Do not expand scope beyond this ticket's 'Scope / Deliverables' section; anything else belongs to a sibling ticket named in 'Out of scope'.")
    return items


def brief_for(epic: str, ticket: dict) -> str:
    key = ticket["key"]
    title = ticket["title"]
    component = ticket.get("component", "")
    labels = ticket.get("labels", [])
    body = ticket.get("body", "")
    suffix = key.split("-")[1] if "-" in key else ""
    kindletter = suffix[0] if suffix else ""

    read_first = EPIC_READ[epic]
    paths = repo_paths_for(epic, key, title, component, labels)
    interfaces = EPIC_INTERFACES[epic]
    cmds = commands_for(component, epic)
    slug = EPIC_BRANCH_SLUG[epic]
    reviewers = EPIC_REVIEWERS[epic]
    done = done_means_for(key, kindletter, body)
    donot = do_not_for(epic, key, kindletter, component)

    branch = f"feat/{slug}-{suffix.lower()}" if suffix else f"feat/{slug}"
    pr_title = f'"{key}: {title}"'

    lines = []
    lines.append("## Agent execution brief")
    lines.append("")
    lines.append("**Read first**")
    for r in read_first:
        lines.append(f"1. {r}" if read_first.index(r) == 0 else f"{read_first.index(r)+1}. {r}")
    lines.append("")
    lines.append("**Repo paths to create/modify**")
    for p in paths:
        lines.append(f"- {p}")
    lines.append("")
    lines.append("**Interfaces you must not break**")
    lines.append(f"- {interfaces}")
    lines.append("")
    lines.append("**Commands**")
    for c in cmds:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("**Branch & PR**")
    lines.append(f"- Branch: `{branch}`")
    lines.append(f"- PR title: {pr_title}")
    lines.append("- Body: include `Closes #<issue>` (replace `<issue>` with this ticket's GitHub issue number)")
    lines.append(f"- Required reviewers (CODEOWNERS): {reviewers}")
    lines.append(f"- Labels: carry over this ticket's labels ({', '.join(labels)}) plus any CI-added labels")
    lines.append("")
    lines.append("**Done means**")
    for d in done:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("**Do NOT**")
    for d in donot:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("**If blocked**")
    lines.append(f"- Comment on this ticket's GitHub issue naming the exact blocking key (e.g. a dependency listed under `blocked_by` or in '## Dependencies'), move Status → Blocked, and stop. Never silently work around a failing lint/test/contract gate.")
    return "\n".join(lines)


def main():
    report = []
    for epic in EPICS:
        path = os.path.join(BACKLOG, f"{epic}.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        tickets_updated = 0
        gherkin_added = 0
        for t in data:
            if t.get("kind") == "Epic":
                continue
            if "retired" in t.get("labels", []):
                continue
            if "## Agent execution brief" in t["body"]:
                continue
            brief = brief_for(epic, t)
            t["body"] = t["body"].rstrip("\n") + "\n\n" + brief + "\n"
            tickets_updated += 1

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        report.append((epic, tickets_updated))

    for epic, n in report:
        print(f"{epic}: {n} tickets updated with Agent execution brief")


if __name__ == "__main__":
    main()
