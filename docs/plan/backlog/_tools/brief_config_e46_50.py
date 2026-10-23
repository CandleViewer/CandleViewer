"""
Append '## Agent execution brief' (+ any missing required sections) to every
live (non-retired) non-Epic ticket in E46-E50. Epics get '## Agent guidance'.
"""
import json
import re

FILES = ["E46.json", "E47.json", "E48.json", "E49.json", "E50.json"]

# component -> default "read first" plan docs (always augmented per-ticket by keyword rules below)
COMPONENT_READS = {
    "chart-engine": [
        "docs/plan/26-chart-engine-design.md (relevant §, per ticket References)",
        "docs/plan/06-performance-and-load-standard.md §4.3 (frame budget)",
        "docs/plan/05-accessibility-standard.md §6 (DOM-mirror/live-region parity)",
    ],
    "web": [
        "docs/plan/14-screens-catalogue.md (this ticket's SCR-xxx entry)",
        "docs/plan/15-component-catalogue.md + 16-design-system-brief.md",
        "docs/plan/05-accessibility-standard.md (relevant §)",
    ],
    "api": [
        "docs/plan/20-architecture.md §4.2/§12 (module boundaries, metrics)",
        "docs/plan/24-internal-schemas.md (relevant §)",
        "docs/plan/28-statechart-catalogue.md (if statechart-labelled) + ADR-0016",
    ],
    "infra": [
        "docs/plan/06-performance-and-load-standard.md §7 (harness/CI gates)",
        "docs/plan/20-architecture.md §12 (observability)",
        ".github/workflows/ (existing CI jobs to extend, not replace)",
    ],
    "docs": [
        "docs/plan/07-release-and-prr.md (PRR/runbook procedures)",
        "docs/plan/30-release-roadmap.md (R5 exit criteria)",
        "docs/plan/02-definition-of-ready-done.md (DoR/DoD)",
    ],
    "cross-cutting": [
        "docs/plan/00-planning-brief.md",
        "docs/plan/02-definition-of-ready-done.md",
        "docs/plan/03-testing-strategy.md",
    ],
    "scripting": [
        "docs/plan/14-screens-catalogue.md SCR-082 (node-graph editor)",
        "docs/plan/05-accessibility-standard.md §3.2/§3.3",
    ],
}

CODEOWNER_PATHS = {
    "chart-engine": "/packages/chart-engine/",
    "web": "/apps/web/",
    "api": "/services/api/",
    "infra": "/infra/",
    "docs": "/docs/plan/",
    "cross-cutting": "/docs/plan/",
    "scripting": "/apps/web/src/features/rule-builder-graph/",
}

REVIEWERS = {
    "chart-engine": "@CandleViewer/chart-engine",
    "web": "@CandleViewer/frontend",
    "api": "@CandleViewer/backend",
    "infra": "@CandleViewer/devsecops",
    "docs": "@CandleViewer/architecture",
    "cross-cutting": "@CandleViewer/architecture",
    "scripting": "@CandleViewer/frontend",
}

COMMANDS = {
    "chart-engine": [
        "pnpm --filter @candleviewer/chart-engine test",
        "pnpm --filter @candleviewer/chart-engine bench",
        "pnpm lint && pnpm typecheck",
    ],
    "web": [
        "pnpm --filter @candleviewer/web test",
        "pnpm test:a11y",
        "pnpm e2e",
        "pnpm lint && pnpm typecheck",
    ],
    "api": [
        "cd services/api && pytest -m \"not integration\" --cov=. --cov-fail-under=85",
        "cd services/api && ruff check . && ruff format --check . && mypy --strict .",
        "cd services/api && lint-imports",
    ],
    "infra": [
        "pnpm verify",
        "k6 run tests/load/api-ws.js  # if load-relevant",
        "docker compose -f infra/docker-compose.dev.yml up -d  # local stack",
    ],
    "docs": [
        "pnpm lint  # docs-site link/markdown checks",
        "make gen && git diff --exit-code  # if generated reference docs touched",
    ],
    "cross-cutting": [
        "pnpm verify",
        "cd services/api && pytest -m \"not integration\" --cov=. --cov-fail-under=85",
    ],
    "scripting": [
        "pnpm --filter @candleviewer/web test",
        "pnpm test:a11y",
    ],
}

print("loaded config ok")
