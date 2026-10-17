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
the API serves nothing, `/healthz` included, until it ends, and a healthy pass of about 20 keys fits.

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
| `key_withdraw_permission`                               | Remove every right but `ContractTrade` `Order`/`Position` and `Derivatives` `DerivativesTrade`. Safer: delete the key and store a compliant one. |
| `key_missing_scopes`                                    | A trade key needs write access with `ContractTrade` `Order` and `Position`; a read-only key must be read-only.                                   |
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
`api_keys.last_error_code` give the cause: a venue code (10004 signature refused, 10002 clock drift:
the host clock is off and the ingestion clock guard has not measured the offset, 10006 or 10018 rate
limit), `rate_limited` (an IP-level hold after a 10018 is in force, so the key was not called),
`transport_error`, `timeout`, `unknown_state`, `probe_slow` or
`check_error`. `unavailable`: keys are stored but `CV_EGRESS_IP` is unset (`key_selfcheck_no_egress_ip`),
the key list could not be read (`key_selfcheck_targets_failed`), a key's check passed its deadline
(`key_selfcheck_unfinished`), the start-up pass passed its bound (`key_selfcheck_boot_unfinished`;
with more than about ten keys an exchange outage at start-up is enough, a rate-limit hold is not)
or the loop died
(`key_selfcheck_loop_died`). `/readyz` shows a failing `accounts` check for both. Fix the cause
(exchange reachability, the host clock, Postgres, the setting), then restart cv-api via the launcher.
