# Runbook — incidents (E42-T05)

Owner: accounts-admin. Code: `incident_grouping.py` (the signature) and `incidents_sqlalchemy.py`
(the upsert and the purge) in `services/api/candleviewer/storage/repositories/`, and
`services/api/candleviewer/health_wiring.py` (the writer). Spec: `docs/plan/21-database-schema.md`
§3.10.2a.

## One-off: errors written before the incident write path deployed

An `error` or `critical` `system_events` row written before the write path deployed has no incident,
and nothing backfills it: the signature comes from the application's normaliser, which an
`INSERT ... SELECT` cannot repeat exactly, and a row keyed any other way would never match a later
occurrence. So `GET /api/v1/admin/incidents` and the overview's `incidents_open` count omit such rows. They
appear only when the same fault recurs: a new row creates its incident, counted from that
occurrence. A health component that has been down since before the deploy writes no new row until it
recovers and fails again, because health events are edge-triggered. Resolving the old rows is not an
option yet: no route writes `system_events.resolved_at` (E09-S12).

The raw rows stay in `system_events`. To list what the count and the list omit, and compare it with
`GET /api/v1/admin/incidents`, connect `psql` as the read-only role `cv_ro` and set `deployed_at` to
the time the write path started serving, in UTC:

```sql
-- the example time below: replace it with yours
\set deployed_at '2026-10-20 12:00:00+00'
SELECT component, kind, severity, count(*) AS events, max(event_ts) AS last_event
FROM system_events
WHERE severity IN ('error', 'critical') AND resolved_at IS NULL AND event_ts < :'deployed_at'
GROUP BY component, kind, severity
ORDER BY last_event DESC;
```
