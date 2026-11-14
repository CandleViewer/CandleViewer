# E42-Q03 — admin chaos scenarios, server halves (#1216)

Suite: `services/api/tests/chaos/admin/` (part 2 of 5 of #1216; the plan of record is
`qa/plans/e42-perf-chaos.md`, which part 1 adds). The scenario files carry `chaos` and `harness`:
they need Docker (a loopback Postgres 16 testcontainer per module, its database named `test`), so
the PR lanes deselect them and `chaos-admin-nightly.yml` runs them every night, then runs
`promtool test rules` over the alert inputs they wrote. `test_e42_chaos_helpers.py` carries
`chaos` only: it is pure and loopback-only, so the PR `py` lane runs it too.

Run: `make admin-chaos` (Docker needed), or
`cd services/api && uv run pytest tests/chaos/admin -m "chaos and not flaky" --no-cov -rA -p no:randomly`.
Without Docker the scenario fixtures error: a run without the database fails, never passes.

## Harness

- **Faults in process** ([BQ-4]; the E27-Q03 ruling, `qa/plans/e27/chaos.md`): `_relay.Relay` is an
  asyncio TCP relay on 127.0.0.1 in front of Postgres, generalised from the relays of
  `tests/integration/oms/`. Modes `delay(ms)` (each chunk held, both ways), `blackhole()` (nothing
  forwarded; the reader's own budget ends the wait), `cut()` (the port refuses, live links reset)
  and `heal()` (links that lived through a fault are reset, the port listens again). One relay aims
  at one subsystem: scenario 6 gives the flag store a relay of its own. No `tc netem`, no proxy
  container, nothing under `infra/`.
- **Recovery is asserted.** Every scenario ends with `heal()` and `ensure_up()`, which fails unless
  a Postgres SSLRequest sent through the relay is answered by the upstream; the `relay` fixture
  repeats both at teardown, so a scenario that failed mid-fault leaves no fault behind. A relay
  refuses an upstream that is not on loopback.
- **The composition** ([BQ-4], a deviation from the plan's subprocess `create_app`): `_server.py`
  builds the routers and services `create_app` mounts (the audited admin router, the audit router
  with its limiter, budget and 4 s stop, the flag runtime, the overview, incidents and backups read
  models, the health registry and its `system` frame publisher) over the real Postgres through the
  relay, served by `httpx.ASGITransport`. Stand-ins only for ports no relay can aim at: the
  principal resolver (a fixed Owner who is a `users` row), a health source with no snapshot
  (scenario 1) and a recorder port that never answers (scenario 3). None is reachable from a
  setting.
- **Never production.** `require_test_database` refuses a DSN that is not loopback or whose
  database is not `test` or `*_test`, without echoing it; AUDIT-CORRUPT goes into scenario 4's own
  database, never beside a load set (C-5.7: audit rows are permanent).
- **Alert chain** ([BQ-6], `_alerts.py`): a scenario scrapes the text exposition, then writes the
  values as a promtool suite over `infra/prometheus/alerts/system_{page,ticket}.yml`, each case
  expecting the alert with the rule's own labels and annotations. A pure test pins that each rule
  reads a series the app exports, so a rename fails in the PR lane.

## Catalogue

| #   | Scenario                       | C-13.6 | Server half (this part)                                                                                                                                                                                                                                                                | UI half (part 3)                            |
| --- | ------------------------------ | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 1   | Health `503`, `system` up      | —      | `test_s1_health_unavailable.py`: a cut reaches the `system` `health` frame within 2 s, `postgres` down, the other components unchanged, no host or trace in it; `GET /admin/health` is `503 store_unavailable` + `Retry-After: 5` with no snapshot [BQ-5]                              | HL-11, HL-14                                |
| 2   | WS drop mid-session            | —      | `test_s2_incident_reread.py`: with the relay a blackhole between the two flaps (the away client's read of the list hangs), a failure raised twice is one incident, `occurrences` 2, the same id after the heal and on a re-read. Reconnect and resubscribe: `tests/chaos/ws` (E17-Q02) | SCR-144 IL-10, `wsTap.drop()`               |
| 3   | Postgres slow (800 ms a chunk) | #10    | `test_s3_postgres_slow.py`: overview slices `error` "timed out after 300 ms"; flag list `fail_closed` inside 1 s; the audit page answers inside 5 s, and under a 3 s delay the 4 s stop always ends it: `503 store_unavailable` with `Retry-After`                                     | stale and error states, Retry, no spinner   |
| 4   | Audit chain break              | —      | `test_s4_chain_break.py`: verify `200 {verified: false, first_bad_id}`; counter +1, gauge 0 and still 0 after a passing partial range; critical incident `open`; halt engaged; promtool suite for two pages [BQ-6]                                                                     | the D04 banner, `strip.tamper`              |
| 5   | Backup verification failed     | —      | `test_s5_backup_verify_failed.py`, **engine not wired** [BQ-5]: catalogue lists both rows, the failed one with `checksum_mismatch`; age = the verified run's; promtool suite for the `BackupLastSuccessStale` ticket                                                                   | the failed row, "last verified", Restore T2 |
| 6   | Flag store unreachable         | —      | `test_s6_flag_store_down.py`: list `200` `fail_closed`, every boolean at its fail-closed value (order-entry kill switch on, live off, maintenance on), no `default_value` / `updated_at`; `stored` again within 3 s of the heal                                                        | `flags.fail_closed` banner, Change T2       |

C-13.6 numbers are cited by number only. Scenario 3 is #10's slow form; the others are the
ticket's own and map to none, as the E17 report records its own.

## Not asserted here, and where it is

- **[BQ-5] Scenario 1's `503` under a cut alone.** The cut does not make `GET /admin/health`
  answer `503`: the area's entry record is written to the audit WAL first, so the read is `200`
  with `postgres` down (the test pins that). The `503` the UI half needs comes from a source with
  no snapshot (the stand-in) or a full WAL (part 4's refusal flood).
- **[BQ-5] Scenario 5 through the routes.** `BACKUPS_CATALOGUED` is False until #3319; the test
  asserts it still is and reads the shipped catalogue and freshness directly. Re-run through
  `GET /admin/backups` when #3319 lands. The restore refusal (`409 backup_not_usable`) waits on
  BK-14's mount.
- **Scenario 6's write.** `PUT` answering `503 store_unavailable` and changing nothing is pinned by
  `tests/unit/admin/test_flag_routes.py::test_a_store_outage_is_503_and_says_when_to_retry`; a
  write needs a step-up this composition does not run.
- **[BQ-6] The page reaching a human.** CI has no path into Alertmanager; the routing of the three
  alerts is `infra/alertmanager/tests/test_alerting_config.py`'s, and the compose drill
  (`make alert-drill`) is recorded once per release in the report (part 5).
- **Timings are recorded, not baselined.** Each scenario prints what it measured (`-rA` puts it in
  the job log); the report (part 5) quotes them.
