# Public trade-archive fixtures (E16-T10)

- `BTCUSDT2026-06-05.csv.gz` — **synthetic**, not recorded. Shape follows the exchange's public
  daily trade archive (gzip CSV, header `timestamp,symbol,side,size,price,tickDirection,
trdMatchID,grossValue,homeNotional,foreignNotional`; `timestamp` = epoch seconds with a
  fractional part). Date 2026-06-05, symbol BTCUSDT, env: public (no account data); 6 rows,
  one per hour; trade ids are placeholder UUIDs; no identifiers to redact. Built with
  `gzip.compress(..., mtime=0)` so it is byte-stable. Replace with a recorded, redacted capture
  once the recorder tool can fetch archives (C-13.5).
