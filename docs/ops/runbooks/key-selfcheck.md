# Stored API key self-check runbook (E27-T03, #836)

Status: written 2026-10-16 against the #836 slice 2a3 branch; not yet drilled on a real host. No
secret, key material, key id or host address belongs in this file.

On the real storage backend the API checks every usable stored key of its environment (`active`
or `rotating`, not revoked, account not deleted) before it serves, then at least hourly (C-12.2),
with the key-import pipeline: no withdrawal or transfer right, the trade scopes, a unified trading
account, the account's UID, a whitelist holding only the egress IP, the expiry and a signed probe.
Every call goes to the key's own environment's host (C-2.11). Code: `accounts/selfcheck.py`, wired
by `key_selfcheck_wiring.py`. `CV_EGRESS_IP` is the address the exchange sees from this host (required
once a key is stored); `CV_KEY_SELFCHECK_INTERVAL_S` is 60 to 3600. The start-up pass is bounded at 60 s:
the API serves nothing, `/healthz` included, until it ends, and a healthy pass of up to about 19 keys fits.

## Symptom: read-only with `accounts.key_selfcheck_failed`

Signals: `/readyz` reports `degraded` with a failing `accounts` check; every WS client gets the
critical `system` notice with this reason (its text is the generic read-only one until #836 slice
2c lists the `accounts.*` codes in `23-ws-protocol.md` §15.9); at start-up the log
says `starting in read-only mode (accounts.key_selfcheck_failed)`; the critical log
`key_selfcheck_failed` names the key id and the failing rules; the audit log has `account.tested`
(outcome failure, severity critical, `reason` the rule, `object_id` the key id) and, if the account
could trade, `account.disabled_by_policy`. Order entry is off for **every** account and the key's
account is disarmed (`trading_enabled` false). The key's status does not change: reads go on.

Find the key and the rule as an Owner (`GET $API/admin/audit?action=account.tested`), then fix the
key at the exchange. The whitelist is edited in the exchange's web dashboard only (ADR-0009).

| Rule                                                    | Fix at the exchange                                                                                                                              |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `key_withdraw_permission`, `key_permission_not_allowed` | Remove every right but `ContractTrade` `Order`/`Position` and `Derivatives` `DerivativesTrade`. Safer: delete the key and store a compliant one. |
| `key_missing_scopes`                                    | A trade key needs write access with `ContractTrade` `Order` and `Position`.                                                                      |
| `key_not_read_only`                                     | A key stored as read-only must be read-only at the exchange: switch it to read-only there, or replace it.                                        |
| `key_not_unified`, `key_uid_mismatch`                   | The key must belong to the account's own unified trading account; otherwise replace it.                                                          |
| `key_ip_whitelist_missing`, `key_ip_whitelist_mismatch` | Whitelist exactly `CV_EGRESS_IP`: no other entry, range or wildcard. If the egress address changed, correct the setting instead.                 |
| `key_wrong_environment`                                 | This environment's host does not know the key (a live key in a demo account, say): store a key of the account's environment.                     |
| `key_expired`, `key_probe_failed`                       | Replace the key.                                                                                                                                 |

Recovery: restart cv-api via the launcher. Only a restart clears the latch (a passing hourly
re-check never does, nothing clears it by hand), and the start-up pass checks the key again before
the app serves. Verify: no `starting in read-only mode` line for an `accounts.*` reason, and a new
`account.tested` with outcome success for the key. The disarmed account stays disarmed: re-arming
is an audited admin action that comes with the key routes (#2417, #836); never re-arm in SQL (C-2.9).

## Symptom: read-only with `accounts.key_verification_stale` or `accounts.key_selfcheck_unavailable`

No verdict was possible, so no key is blamed and nothing is disarmed. `stale`: a key has had no
passing check for the interval plus 15 minutes; the warning log `key_selfcheck_inconclusive` and
`api_keys.last_error_code` give the cause, as a `KeyProbeError` name: `auth_error` (10004, the
signature was refused), `clock_drift` (10002: the host clock is off and the ingestion clock guard has
not measured the offset), `rate_limited` (10006, 10018, or the IP-level hold after a 10018, which
makes no call), `service_unavailable` (10016, 10019 or an HTTP 5xx), `transport_error` (a reset, or
a reply that is not JSON), `timeout`, `exchange_unknown` (any other refusal or unreadable reply), or
one of the job's own: `probe_slow` (accepted later than the receive window), `probe_clock_step` (the
host clock stepped during the probe) or `check_error`. A `check_error` can also be a borrow that
the C-2.8 re-check refused (SR-E27-14): the error log `key_selfcheck_error` for that `key_id` then
has `error=WithdrawPermissionRejected` or `error=SnapshotInvalid`, and the key cannot sign
anything. Read its row in `api_keys`: `can_withdraw` and `can_transfer` must both be false, and
`permission_snapshot` must be an object whose `permissions` hold only the rights the
`key_withdraw_permission` row of the table above allows. A row that fails was edited since
`store()` accepted it (KV-T03 of the E27 threat model): never correct it in SQL (C-2.9), treat it
as a possible database tamper and replace the key (delete it, store a compliant one). Until slice
2c1 of #836 this shows up only as the stale latch; 2c1 will report it as a policy violation
(`key_withdraw_permission`, the first symptom above, with the force-disable and the critical
alert). `unavailable`: keys are stored but `CV_EGRESS_IP` is unset (`key_selfcheck_no_egress_ip`),
the key list could not be read (`key_selfcheck_targets_failed`), a key's check passed its deadline
(`key_selfcheck_unfinished`), the start-up pass passed its bound (`key_selfcheck_boot_unfinished`;
with more than about ten keys an exchange outage at start-up is enough, a rate-limit hold is not)
or the loop died
(`key_selfcheck_loop_died`). `/readyz` shows a failing `accounts` check for both. Fix the cause
(exchange reachability, the host clock, Postgres, the setting), then restart cv-api via the launcher.

## Dev deploys: the smoke test needs `/readyz` ok

`tools/ci/deploy_dev.py` (E03-T09) accepts a dev deploy only when both `/healthz` and `/readyz`
report status `ok` within `--smoke-timeout-s` (60 s by default). Otherwise it fails with
`CI-DEP-002` and, on dev, redeploys the previous known-good digest from its ledger (with none
recorded it stops and asks for manual intervention), unless it runs with `--no-auto-rollback`.
A latched self-check or a failing stored key makes `/readyz` read `degraded` (the `accounts`
check), so it fails the dev deploy and rolls it back. That is fail closed, as intended; do not
relax the smoke test for it. It applies wherever the job runs: the real storage backend with at
least one usable stored key. The fake backend wires no self-check.

The case to expect is `CV_EGRESS_IP` unset with a stored key (`key_selfcheck_no_egress_ip`,
`accounts.key_selfcheck_unavailable`), and compose cannot supply it today. It forwards neither
`CV_EGRESS_IP` nor `CV_STORAGE_BACKEND` to the `api` container: the service lists its environment
explicitly (`infra/compose/docker-compose.yml`, `environment:` of `api`) and has no `env_file`, so
a value set in the deploy environment, or in the file the deploy renders, never reaches it. A dev
deploy with a stored key on the real backend therefore fails the `/readyz` smoke test and is
rolled back, and setting `CV_EGRESS_IP` in the deploy environment does not change that until #3180
forwards both variables. Until then the container runs on the default `fake` backend, where no
self-check is wired, and the deployed lifespan cannot boot the real one yet (#2334). The deploy
adds no address itself: it renders the stack's environment file (`--env-out`) from the template
named by `--env-example`, changing only the git sha and the image digest. The address is
Confidential (E27 threat model §1.2): keep it out of committed files.
