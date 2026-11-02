-- E24-T06 reference: open interest resampled onto the bar grid (24 §7.2 `open_interest`,
-- `open_interest_value`, `open_interest_delta`, `oi_price_quadrant`). Written from the spec, not
-- from the engine. Bars are half-open [start_ms, end_ms).
-- Spec-by-ruling (not in 24 §7.2): the open sample is the last one at or before the bar start
-- within $staleness_ms (#723 BQ-5, 600 000 ms); past it the open is absent, never carried. A flat
-- price or a flat OI delta classifies nothing (quadrant NULL).
-- Inputs: views bars(start_ms, end_ms, o, c), oi(ts, oi, oi_value), all DECIMAL(38,18).
WITH close_s AS (
  SELECT b.start_ms, max_by(x.oi, x.ts) AS oi_c, max_by(x.oi_value, x.ts) AS v_c
  FROM bars b JOIN oi x ON x.ts >= b.start_ms AND x.ts < b.end_ms
  GROUP BY b.start_ms
), open_s AS (
  SELECT b.start_ms, max_by(x.oi, x.ts) AS oi_o, max_by(x.oi_value, x.ts) AS v_o
  FROM bars b JOIN oi x ON x.ts <= b.start_ms AND b.start_ms - x.ts <= $staleness_ms
  GROUP BY b.start_ms
), j AS (
  SELECT b.start_ms, b.o, b.c, c.oi_c, c.v_c, s.oi_o, s.v_o,
         CASE WHEN c.oi_c IS NOT NULL AND s.oi_o IS NOT NULL THEN c.oi_c - s.oi_o END AS delta
  FROM bars b LEFT JOIN close_s c USING (start_ms) LEFT JOIN open_s s USING (start_ms)
)
SELECT start_ms,
       coalesce(oi_c, oi_o) AS open_interest,
       coalesce(v_c, v_o) AS open_interest_value,
       delta AS open_interest_delta,
       CASE WHEN delta IS NULL OR delta = 0 OR c = o THEN NULL
            WHEN c > o AND delta > 0 THEN 'long_buildup'
            WHEN c > o THEN 'short_covering'
            WHEN delta > 0 THEN 'short_buildup'
            ELSE 'long_unwind' END AS oi_price_quadrant
FROM j ORDER BY start_ms
