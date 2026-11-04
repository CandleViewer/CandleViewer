"""E40-Q02 (#1203): the soak's pass/fail checks (BQ-06), read from the rows after soak.js has
disarmed its alerts. Named checks, each PASS or FAIL in the JSON it writes:

- `alerts_armed`: the 200 soak alerts exist (`e40-soak-%`);
- `alerts_fired`: at least one fired (a soak whose feed never ticked proves nothing);
- `fire_count_equals_delivery_rows`: the sum of their `fire_count` equals their delivery rows
  (each alert has the one channel `in_app`, so one firing is one row: none lost, none doubled);
- `no_dead_outbox_rows`: no alert outbox row (`alert.deliver`, `webhook.post`) is dead.

`memory_envelope` is REPORT ONLY on the first runs (BQ-06): the RSS min and max soak.js sampled,
from its k6 summary, with no envelope until the owner sets one.

The verdict itself is REPORT ONLY while `CV_E40_SOAK_GATE` is not "1": every check is computed
and written, but the exit code is 0. The blocker is #5745 (E35-T15): the rules metric source has no production
producer yet (E12/E18-E25 adapters push into `PushedMetricSource`), so `alerts_fired` cannot pass
on the stack until that bridge lands. `alerts_fired` itself is never relaxed.

    CV_PG_DSN=... uv run --project services/api python tests/load/k6/alerts/soak_check.py \
        --summary k6-summary-alerts-soak.json --out soak-check.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

ARMED = 200
BLOCKER = (
    "the rules metric source has no production producer yet "
    "(E12/E18-E25 adapters push into `PushedMetricSource`); blocker #5745 (E35-T15)"
)
_COUNTS = """
SELECT (SELECT count(*) FROM alerts WHERE name LIKE 'e40-soak-%') AS armed,
       (SELECT coalesce(sum(fire_count), 0) FROM alerts WHERE name LIKE 'e40-soak-%') AS fires,
       (SELECT count(*) FROM alert_deliveries d JOIN alerts a ON a.id = d.alert_id
         WHERE a.name LIKE 'e40-soak-%') AS rows,
       (SELECT count(*) FROM outbox WHERE dead_at IS NOT NULL
         AND topic IN ('alert.deliver', 'webhook.post')) AS dead
"""


def gated(env: dict[str, str] | None = None) -> bool:
    """The workflow's one switch: only "1" lets the soak's checks fail the job."""
    return (os.environ if env is None else env).get("CV_E40_SOAK_GATE", "0") == "1"


def verdict(counts: dict[str, int], rss: dict[str, float] | None) -> dict[str, Any]:
    checks = {
        "alerts_armed": counts["armed"] == ARMED,
        "alerts_fired": counts["fires"] > 0,
        "fire_count_equals_delivery_rows": counts["fires"] == counts["rows"],
        "no_dead_outbox_rows": counts["dead"] == 0,
    }
    return {
        "counts": counts,
        "checks": {k: "PASS" if ok else "FAIL" for k, ok in checks.items()},
        "memory_envelope": {"mode": "report-only", "rss_bytes": rss},
        "status": "PASS" if all(checks.values()) else "FAIL",
    }


def rss_of(summary: Path) -> dict[str, float] | None:
    if not summary.is_file():
        return None
    values = json.loads(summary.read_text(encoding="utf-8"))["metrics"].get(
        "alerts_soak_rss_bytes"
    )
    if not values:
        return None
    v = values.get("values", values)
    return {"min": v["min"], "max": v["max"], "growth": v["max"] - v["min"]}


async def counts(dsn: str) -> dict[str, int]:
    import asyncpg  # the API's driver; imported here so `verdict` needs no dependency

    conn = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    try:
        row = await conn.fetchrow(_COUNTS)
        return {k: int(row[k]) for k in ("armed", "fires", "rows", "dead")}
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    result = verdict(asyncio.run(counts(os.environ["CV_PG_DSN"])), rss_of(args.summary))
    gate = gated()
    result["gate"] = "on" if gate else f"report-only: {BLOCKER}"
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, state in result["checks"].items():
        print(f"{state} {name}")
    print(f"REPORT memory_envelope {result['memory_envelope']['rss_bytes']}")
    if not gate:
        print(f"REPORT-ONLY soak verdict {result['status']}: {BLOCKER}")
        # The blocker explains the firing checks only; arming the alerts is independent of it.
        return 1 if result["checks"]["alerts_armed"] == "FAIL" else 0
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
