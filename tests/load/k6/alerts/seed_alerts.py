"""E40-Q02 (#1203): seed the alert load stack with >= 1M notification-source rows, in Postgres,
server-side (`generate_series`), on the throwaway database perf-alerts-nightly.yml migrates.

    CV_PG_DSN=postgresql+asyncpg://... uv run --project services/api \
        python tests/load/k6/alerts/seed_alerts.py --users-like 'perf-abcd-%'

What it writes, for the Owners whose username matches `--users-like` (seeded per run by
`seed_fixture_user.py`):
- per Owner one disabled seed alert and `--sent-per-user` `sent`, unacknowledged in-app
  deliveries: what ws_subscribers.js acknowledges, and the newest 500 the `alerts` snapshot reads;
- `alert_deliveries`: `acked` history rows up to `--rows` x ALERT_SHARE, spread over the Owners;
- `system_events`: the rest of `--rows`, unaddressed (the Owner's stream);
- on top of `--rows`, so the total stays at least 1M: `--rule-events` `action_ok` rows under one
  disabled rule, one rule version and one run per Owner (rules -> rule_versions -> rule_runs ->
  rule_events), and `--order-events` `ack` rows under one testnet account and one order
  (exchange_accounts -> orders -> order_events), so the `GET /notifications` union reads all four
  sources (the FK chains are those of migrations 0013, 0017 and 0029).

It refuses anything but a throwaway perf stack, before and after connecting: `--users-like`
must be exactly `perf-<8 hex>-%` (the workflow's per-run pattern, never a wildcard that matches
every user), the DSN host must be loopback or the compose `postgres` service, and the database
must hold no user outside the pattern, no `live` or `demo` exchange account and no `api_keys` row
(C-2.11).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import uuid
from urllib.parse import parse_qs, urlsplit

ALERT_SHARE = 0.6
USERS_LIKE = re.compile(r"perf-[0-9a-f]{8}-%")
LOCAL_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "::1", "postgres"}
)  # postgres: compose
_STACK = (
    "SELECT (SELECT count(*) FROM users WHERE username NOT LIKE $1) AS others,"
    " (SELECT count(*) FROM exchange_accounts WHERE env IN ('live', 'demo')) AS real_accounts,"
    " (SELECT count(*) FROM api_keys) AS api_keys"
)
_IR = (
    '{"ir_version":1,"trigger":{"type":"on_price_update","debounce_ms":250},'
    '"conditions":{"node_id":"c1","op":"gt","left":{"metric":"last_price"},"right":{"const":0}}}'
)
_ALERT = (
    "INSERT INTO alerts (id, owner_user_id, name, symbol, condition_ir, condition_hash, enabled)"
    " SELECT gen_random_uuid(), u.id, 'e40-seed', 'BTCUSDT', $2::jsonb, repeat('0', 64), false"
    " FROM users u WHERE u.username LIKE $1 RETURNING id, owner_user_id"
)
_DELIVERIES = (
    "INSERT INTO alert_deliveries (alert_id, user_id, channel, status, title, body, queued_at,"
    " sent_at, acked_at, acked_by)"
    " SELECT $1, $2, 'in_app', $3::delivery_status, 'e40 seed', 'e40 seed ' || g,"
    " now() - make_interval(secs => g), now() - make_interval(secs => g),"
    " CASE WHEN $3 = 'acked' THEN now() ELSE NULL END, CASE WHEN $3 = 'acked' THEN $2 END"
    " FROM generate_series(1, $4) AS g"
)
_SYSTEM = (
    "INSERT INTO system_events (component, kind, severity, message, event_ts)"
    " SELECT 'api', 'e40_seed', 'info', 'e40 seed ' || g, now() - make_interval(secs => g)"
    " FROM generate_series(1, $1) AS g"
)
_RULE = (
    "INSERT INTO rules (id, name, owner_user_id, scope, mode)"
    " SELECT gen_random_uuid(), 'e40-seed', u.id, 'global', 'disabled'"
    " FROM users u WHERE u.username LIKE $1 RETURNING id"
)
_RULE_VERSION = (
    "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version)"
    " VALUES ($2, $1, 1, '{\"conditions\":{},\"actions\":[]}'::jsonb, repeat('0', 64), 'e40-seed')"
)
_RULE_RUN = (
    "INSERT INTO rule_runs (id, rule_id, rule_version_id, status, mode, trigger_reason,"
    " input_snapshot) VALUES ($3, $1, $2, 'ok', 'disabled', 'manual', '{}'::jsonb)"
)
_RULE_EVENTS = (
    "INSERT INTO rule_events (rule_run_id, seq, kind, event_ts)"
    " SELECT $1, g, 'action_ok', now() - make_interval(secs => g)"
    " FROM generate_series(1, $2) AS g"
)
# the testnet account matches the API's CV_ENVIRONMENT, as the route reads this environment only
_ACCOUNT = (
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label)"
    " VALUES ($1, (enum_range(NULL::exchange_code))[1], 'testnet', 'main', '900000001',"
    " 'e40-seed')"
)
_ORDER = (
    "INSERT INTO orders (id, exchange_account_id, order_link_id, symbol, side, intent,"
    " order_type, qty) VALUES ($2, $1, 'ext-' || md5('e40-seed'), 'BTCUSDT', 'Buy', 'entry',"
    " 'Market', 1)"
)
_ORDER_EVENTS = (
    "INSERT INTO order_events (order_id, seq, kind, source, event_ts)"
    " SELECT $1, g, 'ack', 'local', now() - make_interval(secs => g)"
    " FROM generate_series(1, $2) AS g"
)


def check_users_like(pattern: str) -> None:
    """Only the workflow's per-run `perf-<8 hex>-%`; a broader LIKE could match real users."""
    if not USERS_LIKE.fullmatch(pattern):
        raise SystemExit(f"refusing: --users-like {pattern!r} is not perf-<8 hex>-%")


def check_dsn(dsn: str) -> None:
    """Only a loopback or compose-local Postgres; a `host` query parameter could redirect it."""
    parts = urlsplit(dsn)
    if "host" in parse_qs(parts.query):
        raise SystemExit("refusing: the DSN names a host in its query string")
    if "," in parts.netloc:
        raise SystemExit("refusing: the DSN lists more than one host")
    if parts.hostname not in LOCAL_HOSTS:
        raise SystemExit(
            f"refusing: DSN host {parts.hostname!r} is not loopback or compose"
        )


def check_stack(others: int, real_accounts: int, api_keys: int) -> None:
    """The database must look like a throwaway perf stack (C-2.11 defence in depth)."""
    if others:
        raise SystemExit(
            f"refusing: {others} user(s) outside the perf pattern; not a perf stack"
        )
    if real_accounts:
        raise SystemExit(f"refusing: {real_accounts} live or demo exchange account(s)")
    if api_keys:
        raise SystemExit(f"refusing: {api_keys} api_keys row(s); not a perf stack")


def plan(rows: int, owners: int, sent_per_user: int) -> dict[str, int]:
    """Rows per table; the alert share counts the sent rows, so the total is `rows` at least (ceil per Owner)."""
    if owners < 1:
        raise ValueError("no Owner matches --users-like: seed the users first")
    alert_rows = int(rows * ALERT_SHARE)
    acked = max(0, alert_rows - owners * sent_per_user)
    return {
        "sent_per_owner": sent_per_user,
        "acked_per_owner": -(-acked // owners),
        "system_events": rows - alert_rows,
    }


async def seed(
    dsn: str,
    users_like: str,
    rows: int,
    sent_per_user: int,
    rule_events: int = 50_000,
    order_events: int = 50_000,
) -> dict[str, int]:
    import asyncpg  # the API's driver; imported here so the plan above needs no dependency

    check_users_like(users_like)
    check_dsn(dsn)
    conn = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    try:
        stack = await conn.fetchrow(_STACK, users_like)
        check_stack(stack["others"], stack["real_accounts"], stack["api_keys"])
        async with conn.transaction():
            alerts = await conn.fetch(_ALERT, users_like, _IR)
            p = plan(rows, len(alerts), sent_per_user)
            for a in alerts:
                aid, uid = a["id"], a["owner_user_id"]
                await conn.execute(_DELIVERIES, aid, uid, "acked", p["acked_per_owner"])
                await conn.execute(_DELIVERIES, aid, uid, "sent", p["sent_per_owner"])
            await conn.execute(_SYSTEM, p["system_events"])
            rules = await conn.fetch(_RULE, users_like)
            for r in rules:
                version, run = uuid.uuid4(), uuid.uuid4()
                await conn.execute(_RULE_VERSION, r["id"], version)
                await conn.execute(_RULE_RUN, r["id"], version, run)
                await conn.execute(_RULE_EVENTS, run, -(-rule_events // len(rules)))
            account, order = uuid.uuid4(), uuid.uuid4()
            await conn.execute(_ACCOUNT, account)
            await conn.execute(_ORDER, account, order)
            await conn.execute(_ORDER_EVENTS, order, order_events)
        await conn.execute(
            "ANALYZE alert_deliveries; ANALYZE system_events; ANALYZE rule_events;"
            " ANALYZE order_events"
        )
        p["rule_events"], p["order_events"] = rule_events, order_events
        return p
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--users-like", required=True)
    ap.add_argument("--rows", type=int, default=1_000_000)
    ap.add_argument("--sent-per-user", type=int, default=5_000)
    ap.add_argument("--rule-events", type=int, default=50_000)
    ap.add_argument("--order-events", type=int, default=50_000)
    args = ap.parse_args(argv)
    if args.rows < 1_000_000:
        print(
            "note: below the ticket's 1M rows; not a measurement seed", file=sys.stderr
        )
    p = asyncio.run(
        seed(
            os.environ["CV_PG_DSN"],
            args.users_like,
            args.rows,
            args.sent_per_user,
            args.rule_events,
            args.order_events,
        )
    )
    print({k: v for k, v in p.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
