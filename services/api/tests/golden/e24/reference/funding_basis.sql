-- E24-T06 reference: funding, annualised funding, time to funding, basis and premium (24 §7.2,
-- §2.7). Written from the spec. DuckDB DECIMAL division returns DOUBLE, so both divisions are
-- exact integer arithmetic on HUGEINT scaled values, rounded half away from zero:
--   annualised_pct = rate * 100 * 525600 / interval_min   (scaled 1e18)
--   premium_pct    = (price - index) / index * 100        (scaled 1e12; prices at 1e9, so
--                    exact for at most 9 price decimals, ample for a tick of 0.1)
-- The Python side turns the scaled integers back into Decimal.
-- Ticker values come from the LAST snapshot in the bar; with no snapshot the funding rate falls
-- back to the settled row whose period [T - interval, T) contains the bar's last ms.
-- Inputs: bars(start_ms, end_ms, o, c), tickers(ts, last, mark, idx, rate, next_ms),
-- funding(ts, rate). Params: $interval_ms, $interval_min.
CREATE OR REPLACE MACRO div_ha(a, b) AS
  sign(a) * sign(b) * ((2 * abs(a) + abs(b)) // (2 * abs(b)));
WITH snap AS (
  SELECT b.start_ms, max(t.ts) AS ts, max_by(t.last, t.ts) AS last, max_by(t.mark, t.ts) AS mark,
         max_by(t.idx, t.ts) AS idx, max_by(t.rate, t.ts) AS rate, max_by(t.next_ms, t.ts) AS next_ms
  FROM bars b JOIN tickers t ON t.ts >= b.start_ms AND t.ts < b.end_ms
  GROUP BY b.start_ms
), settled AS (
  SELECT b.start_ms, min_by(f.rate, f.ts) AS rate
  FROM bars b JOIN funding f ON f.ts > b.end_ms - 1 AND f.ts - $interval_ms <= b.end_ms - 1
  GROUP BY b.start_ms
), j AS (
  SELECT b.start_ms, s.ts, s.last, s.mark, s.idx, s.next_ms,
         coalesce(s.rate, st.rate) AS rate,
         s.last - s.idx AS basis_last, s.mark - s.idx AS basis_mark
  FROM bars b LEFT JOIN snap s USING (start_ms) LEFT JOIN settled st USING (start_ms)
)
SELECT start_ms,
       rate * 100 AS funding_rate,
       div_ha(CAST(rate * 1000000000000000000 AS HUGEINT) * 100 * 525600, $interval_min)
         AS funding_annualized_e18,
       CASE WHEN ts IS NOT NULL AND next_ms IS NOT NULL THEN greatest(0, next_ms - ts) END
         AS time_to_funding_ms,
       basis_last, basis_mark,
       CASE WHEN idx IS NOT NULL AND idx <> 0 AND basis_last IS NOT NULL
            THEN div_ha(CAST(basis_last * 1000000000 AS HUGEINT) * 100000000000000,
                        CAST(idx * 1000000000 AS HUGEINT)) END AS premium_last_e12,
       CASE WHEN idx IS NOT NULL AND idx <> 0 AND basis_mark IS NOT NULL
            THEN div_ha(CAST(basis_mark * 1000000000 AS HUGEINT) * 100000000000000,
                        CAST(idx * 1000000000 AS HUGEINT)) END AS premium_mark_e12
FROM j ORDER BY start_ms
