# Account health runbook (E27-T04, #837)

Status: written 2026-10-19 against the #837 W6 branches; not yet drilled on a real host. No secret,
key material, balance or host address belongs in this file. The alerts link to their sections in
`docs/plan/07-release-and-prr.md` section 9: [AccountDown](../../plan/07-release-and-prr.md#alert-accountdown),
[KeyRotationWarn](../../plan/07-release-and-prr.md#alert-keyrotationwarn) and
[KeyRotationOverdue](../../plan/07-release-and-prr.md#alert-keyrotationoverdue).

## What runs

`account_health_wiring.py` runs, beside the modules, a health monitor per account, the wallet
snapshot cache and its REST reconciler. Every 0.5 s a tick commits health transitions and calls the
dead-man's-switch hook for each transition into `down`; the reconciler reads a wallet over REST
after `CV_WALLET_RECONCILE_S` (60 s) without a refresh, or every `CV_ACCOUNT_HEARTBEAT_S` (10 s)
while the account is not `healthy`. On the real backend a third loop reads every 15 s the enabled
accounts of the process environment that hold a usable key, and the same read feeds the key-age
job. The windows are capped at their defaults (US-ACCT-008, US-ACCT-010) and can only be lowered.

| State      | Reason            | Meaning                                                            | New orders                   |
| ---------- | ----------------- | ------------------------------------------------------------------ | ---------------------------- |
| `healthy`  | `ws_heartbeat`    | An authenticated private-WS message in the last 10 s               | admitted                     |
| `degraded` | `rest_only`       | The WS is silent or closed, a signed REST call succeeded in 30 s   | admitted                     |
| `degraded` | `ws_silent`       | The WS lapsed less than 30 s ago, no REST success since            | admitted                     |
| `down`     | `no_success`      | Neither for 30 s after it was up: pages AccountDown, owes the hook | refused, `account_unhealthy` |
| `down`     | `never_connected` | No success since boot (or since it was tracked); never pages       | refused, `account_unhealthy` |

Health is positive evidence only and decays on silence: a rejected key, a 4xx or a 5xx is never
evidence. Cancel, flatten and stop-loss amends are never gated, and native stop-losses rest at the
exchange (C-2.6). Ages run on the boot-time clock, so a wall-clock step moves nothing. A WSL2 guest
may not see a host suspend (unverified): a resumed account can read `healthy` for at most one
heartbeat window (10 s) before its silence lapses.

**Until the private-WS client (#848) and the exchange's wallet read (E29) land**, every monitored
account reads `down`, `never_connected`, its wallet reads fail and its sizing is off: the system
fails closed. Expected lines meanwhile: a `wallet.reconcile_failed` warning per account every
10 s, and the dead-man's-switch stand-in's `account.dms_policy_unbound` error per episode (E39
binds the policy). Nothing alerts on an account that stays `never_connected`, one restarted into
an outage included: #3731 tracks that alert, for once they have landed.

## Symptom: AccountDown

Follow the 07 section. The log line `account.health_changed` (info; `account_id`, `from_state`,
`to_state`, `reason`) names the account: metrics carry the state, never the account (SR-125). The
hook's lines are `account.dms_hook_failed`, `account.dms_hook_stuck` and `account.dms_hook_dropped`
(a call that this process will not make: owed at shutdown, or replaced by a newer episode). A
restart reads every account as `never_connected`, which resolves an open page: read the account's
state (07 command 1) before treating it as recovered.

## Symptom: `/readyz` reports the `accounts` check degraded on an account-health loop

The detail names the loop: `the account-health-tick loop ended`, or `the account-health-tracking
loop fails: 4 passes in a row`. `account_health.loop_ended` (critical) and
`account_health.step_failed` (error, with the error type only) say which and why. A failing tick
or reconcile loop is a bug: restart cv-api via the launcher and file it. A failing tracking loop is
usually Postgres (`PostgresDown`): a new account stays untracked (refused) until a read works.

```bash
curl -s http://127.0.0.1:8000/readyz
docker compose -f infra/compose/docker-compose.yml --profile core --profile obs logs --since 1h api | grep -E '"event":"account_health\.' | tail -20
```

## Symptom: balances stale, or risk-based sizing unavailable

`balance_stale` turns on 10 s after the last refresh and is for display. Sizing is off only when
the snapshot is stale and the last reconciliation failed, or it is a period (60 s) old. The trading
board's "Oldest wallet snapshot" panel draws both lines; `cv_wallet_reconcile_total{result}` counts
each read (`ok`, `failed`, `rejected`). A `rejected` read is a credential the exchange refused
(`wallet.reconcile_refused`): treat the key as the key self-check runbook (`key-selfcheck.md`)
does. Each sizing decision on a snapshot a period old is logged as `wallet.sizing_on_old_snapshot`
and counted in `cv_wallet_sizing_old_snapshot_total`, and is refused.

## Key age: KeyRotationWarn and KeyRotationOverdue

`rotation_due_at` is a key's registration time plus `CV_KEY_ROTATION_POLICY_DAYS` (90), never the
exchange's expiry; `warn` starts `CV_KEY_ROTATION_WARN_DAYS` (14) before it, `overdue` after it. The
job evaluates every `active` key at each read of the stored keys (at boot, then every 15 s), sets
`cv_keys_rotation_state{state}`, and counts a notice in `cv_key_rotation_notices_total{state}`
once per key as it enters `warn` and once a day per `overdue` key, each logged as
`account.key_rotation_notice` (`key_id`, `account_id`, `state`, `rotation_due_at`). What it counted
lives in memory: a restart counts the keys already in either state again. It never disables a key
and the order-entry gate never reads it (US-ACCT-005). The policy is deployment config: a change
takes a restart, and the first read after it recomputes every key. Rotate a key through SCR-127
(Owner, step-up, audited). A read the job cannot evaluate logs `account_health.key_age_failed`
(error, the error type only) once per change, and the job counts, sets and keeps nothing of it:
its series and tickets lag until a read evaluates whole, while tracking, the key standing and
order entry carry on. That is a bug: file it.
