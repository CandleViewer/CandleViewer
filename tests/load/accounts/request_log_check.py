"""E27-Q03 (#892): judge the stub's request log after a health-poll or burst run (E27-L1/L2).

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

    python request_log_check.py cache   requests.jsonl --window-s 60 --boot-allowance 2
    python request_log_check.py burst   requests.jsonl --t0 <iso> --t1 <iso> --per-key-max N

`requests.jsonl` is the file the fixture transport writes (cvdev/account_fixture/requestlog.py);
copy it out of the stack with `docker compose ... cp`, never read it from a mounted host path. Line
fields read: `ts`, `transport`, `method`, `path`, `outcome`, `signing_key_id`. UNVERIFIED: the exact
JSON key names beyond the module docstring's `signing_key_id`/`method`; the first run confirms them
and a missing key is a refusal here, never a pass (`_need`).

`cache`: for each signing key, the signed wallet-balance reads in any `window_s` window stay at or
below 1 once the boot allowance is spent (the 60 s cache policy of 22 listExchangeAccounts).
`burst`: in [t0, t1) no key makes more than `per-key-max` calls, no call but a GET is made, and no
call reaches an order or fund path (`/v5/order/`, `/v5/asset/`), whatever its method: the probe is
read-only (BQ-08) and neither it nor the key self-check reads orders, so even a GET of
`/v5/order/realtime` inside the window fails the run (a policy choice: a run that finds a legitimate
order read there records it and moves this rule by a reviewed change, never by a flag).
Nothing to judge is never a pass: an empty log exits 2, and a log with no signed wallet read
(`cache`) or no row inside the window (`burst`) fails. Exit 0 = pass, 1 = fail, 2 = unusable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WALLET = "/v5/account/wallet-balance"
#: Paths no call may reach during the burst, GET included: the order and the fund paths.
NEVER_IN_BURST = ("/v5/order/", "/v5/asset/")
FIELDS = ("ts", "method", "path", "outcome", "signing_key_id")


def _need(line: dict[str, object], n: int) -> None:
    missing = [f for f in FIELDS if f not in line]
    if missing:
        print(f"line {n}: missing {missing}; the log shape is not what this check was written for")
        raise SystemExit(2)


def load(path: Path) -> list[dict[str, object]]:
    rows = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        if raw.strip():
            row = json.loads(raw)
            _need(row, n)
            rows.append(row)
    return rows


def _t(row: dict[str, object]) -> float:
    return datetime.fromisoformat(str(row["ts"])).timestamp()


def _worst(times: list[float], window_s: float) -> int:
    return max((sum(1 for u in times if t <= u < t + window_s) for t in times), default=0)


def check_cache(rows: list[dict[str, object]], window_s: float, boot_allowance: int) -> list[str]:
    by_key: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["path"] == WALLET and r["outcome"] == "served" and r["signing_key_id"] is not None:
            by_key[str(r["signing_key_id"])].append(_t(r))
    if not by_key:
        return ["no signed wallet-balance read in the log: nothing to judge, never a pass"]
    bad = []
    for key, times in by_key.items():
        times.sort()
        head = [t for t in times if t < times[0] + window_s]  # the boot allowance: start-up check
        tail = [t for t in times if t >= times[0] + window_s]  # then at most 1 per window
        if len(head) > boot_allowance or _worst(tail, window_s) > 1:
            bad.append(
                f"{key}: {len(head)} reads at boot (allowance {boot_allowance}), "
                f"{_worst(tail, window_s)} in the worst {window_s:g} s window after (cap 1)"
            )
    return bad


def check_burst(rows: list[dict[str, object]], t0: float, t1: float, per_key_max: int) -> list[str]:
    inside = [r for r in rows if t0 <= _t(r) < t1 and r.get("transport", "rest") == "rest"]
    if not inside:
        return ["no request inside the burst window: nothing to judge, never a pass"]
    bad = []
    count: dict[str, int] = defaultdict(int)
    for r in inside:
        count[str(r["signing_key_id"])] += 1
        path = str(r["path"])
        if r["method"] != "GET":
            bad.append(
                f"a non-GET call reached the exchange during the burst: {r['method']} {path}"
            )
        elif path.startswith(NEVER_IN_BURST):
            bad.append(f"an order or fund path was called during the burst: GET {path}")
    bad += [
        f"{k}: {c} calls in the burst window (max {per_key_max})"
        for k, c in count.items()
        if c > per_key_max
    ]
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("cache")
    c.add_argument("log", type=Path)
    c.add_argument("--window-s", type=float, default=60.0)
    # Not ruled: the start-up check's reads; the results file records the allowance used.
    c.add_argument("--boot-allowance", type=int, default=2)
    b = sub.add_parser("burst")
    b.add_argument("log", type=Path)
    b.add_argument("--t0", required=True)
    b.add_argument("--t1", required=True)
    # Not ruled: 06 has no per-key number; the run sets the cap and the results file records it.
    b.add_argument("--per-key-max", type=int, required=True)
    a = ap.parse_args(argv)
    rows = load(a.log)
    if not rows:
        print(f"UNUSABLE {a.mode}: the request log is empty; nothing to judge, never a pass")
        return 2
    if a.mode == "cache":
        bad = check_cache(rows, a.window_s, a.boot_allowance)
    else:
        bad = check_burst(
            rows,
            datetime.fromisoformat(a.t0).timestamp(),
            datetime.fromisoformat(a.t1).timestamp(),
            a.per_key_max,
        )
    print("\n".join(bad) if bad else f"PASS {a.mode} ({len(rows)} log lines)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
