# Observability contract for module authors

One page. Owner: E04. Authoritative detail: ADR-0014, `20-architecture.md` section 12, `07-release-and-prr.md` section 9.

## Register a metric

1. Add a `_s(...)` row to `services/api/candleviewer/observability/metrics_catalogue.py` (name, kind, unit, labels, help, alert, status, owner epic, `max_series`). The golden snapshot test fails on unreviewed changes: review the row it reports, then rerun it with `CV_REGEN_GOLDEN=1` to rewrite `services/api/tests/unit/observability/golden/metrics_catalogue.jsonl` (one sorted row per metric, so two PRs adding different metrics merge cleanly).
2. Add the row to the table in `20-architecture.md` section 12.1; `test_architecture_doc_sync.py` fails if you forget.
3. Pre-bind label children once outside hot loops (`metric.labels(...)` at startup); never call `.labels()` per message (ADR-0014 addendum, E04-K01).
4. Do not declare `env`; the registry injects it.

## Permitted labels

Small closed sets only (topic, stage, reason, result, symbol from the instrument list). Never emails, user names or ids, order ids, tokens, IPs, or free text: `DISALLOWED_LABEL_NAMES` in `metrics.py` rejects them. Exceeding `max_series` collapses new combinations.

## Add a probe

Register a health probe through `health_probes.py` so it appears in `/healthz` and the health screen; probes are fast, side-effect free and never log secrets.

## Get an alert approved

| Step    | Requirement                                                                                                    |
| ------- | -------------------------------------------------------------------------------------------------------------- |
| Rule    | Add to `infra/prometheus/alerts/*.yml` with `severity` of `page` or `ticket`, a `component`, and `runbook_url` |
| Runbook | Add a section to `07-release-and-prr.md` section 9 with all seven elements; no credentials                     |
| Test    | Extend `infra/prometheus/tests/system_alerts.test.yml`                                                         |
| Review  | Architect reviewer; page severity also needs the owner                                                         |

An alert without a runbook is not allowed (ADR-0014 section 6); CI enforces it.
