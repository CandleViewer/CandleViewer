/**
 * SCR-142's copy (E16-S04), verbatim: E16-D04 §14 as `docs/design/E16/E16-D06-copy.json` keys it,
 * by `retention/retentionCopy.ts`'s convention (a row is its parent's quoted strings in order, a
 * template before its example; a test holds every row to the deck). The purge dialog's and the
 * compaction's rows (`storage.purge.*`, `storage.compact.*`) are not here: SCR-142 reuses SCR-140's
 * dialogs whole (E16-D04 §6, §7), so they are E16-S01's copy; `rbac.view_as` is
 * `@candleviewer/ui`'s.
 */
import type { ArchiveImportResult } from "../recorderApi";

export const STORAGE_DECK = {
  "storage.title": ["Storage and database"],
  "storage.stamp": ["Sampled {HH:MM:SS} UTC (every {every})", "Sampled 10:31:03 UTC (every 60 s)"],
  "storage.stamp.stale": [
    "Sampled {HH:MM:SS} UTC, stale ({age} old)",
    "Sampled 10:31:03 UTC, stale (3 min old)",
  ],
  "storage.stamp.sampling": ["Sampling…"],
  "storage.meter.budget": [
    "Recording budget: {used} of {cap} ({pct})",
    "Recording budget: 1,188.0 GB of 2,000.0 GB (59.4 %)",
  ],
  "storage.meter.volume": [
    "Disk volume: {used} of {total} ({pct}), {free} free",
    "Disk volume: 1.2 TB of 4.0 TB (30.1 %), 2.8 TB free",
  ],
  "storage.projection": [
    "Full in about {d} days ({date}) at {growth}: the {wall} is the nearer wall",
    "Full in about 560 days (2028-03-27) at 1.45 GB/day: the budget is the nearer wall (the volume about 1,928 days)",
  ],
  "storage.headline.0": [
    "Growing · auto-record pauses in about {d} days",
    "Growing · auto-record pauses in about 422 days",
  ],
  "storage.headline.1": [
    "Near limit · auto-record pauses in about {d} days · clears below {warn − 5} %",
    "… about 131 days · clears below 75 %",
  ],
  "storage.headline.2": [
    "Auto-record paused · resumes below {autostop − 5} % of the budget with 20 % of the volume free",
  ],
  "storage.headline.3": [
    "Recording stopped · resumes below {halt − 5} % with 10 % of the volume free",
    "… below 90 % …",
  ],
  "storage.level3.fact": [
    "Open positions keep recording; other symbols' data is dropped and recorded as gaps.",
  ],
  "storage.formula": [
    "({autostop} % × {cap} − {used}) ÷ {growth} ≈ {d} days",
    "(90 % × 2,000.0 GB − 1,188.0 GB) ÷ 1.45 GB/day ≈ 422 days",
  ],
  "storage.scale": [
    "80 % warning · 90 % auto-record pauses · 95 % recording stops (open positions keep writing)",
  ],
  "storage.degradation": ["Recording pauses before trading is affected."],
  "storage.degradation.detail": [
    "At 90 % of the recording budget auto-record pauses; at 95 % recording stops for symbols without an open position; orders and positions are never gated by the disk.",
  ],
  "storage.autostop.next": [
    "Recording stops at {halt} % in about {d} days",
    "Recording stops at 95 % in about 69 days",
  ],
  "storage.accelerated": ["Retention accelerated"],
  "storage.volume_refused": [
    "The recording volume was refused at start-up; the gate opens once it is fixed",
  ],
  "storage.actions.shorten": ["Shorten retention"],
  "storage.actions.depth": ["Reduce depth"],
  "storage.actions.unpin": ["Unpin"],
  "storage.tier.questdb": ["QuestDB · hot"],
  "storage.tier.parquet": ["Parquet/DuckDB · cold"],
  "storage.tier.postgres": ["Postgres · relational"],
  "storage.tier.rows": [
    "Size",
    "Share of budget",
    "Retention",
    "Growth/day",
    "Projected full",
    "Health",
    "Ingestion",
    "Last compaction",
    "Last vacuum",
    "Migration",
    "Rows by table",
  ],
  "storage.tier.not_counted": ["not counted"],
  "storage.tier.all_tiers": ["all tiers {growth}", "all tiers 1.45 GB/day", "all tiers 2028-03-27"],
  "storage.tier.health": ["healthy", "degraded", "warning", "down", "not deployed", "not reported"],
  "storage.tier.unreachable": [
    "{Tier} unreachable since {HH:MM:SS} UTC",
    "QuestDB unreachable since 10:24:03 UTC",
  ],
  "storage.tier.retry": ["Retry"],
  "storage.ingestion": [
    "Ingest {rate} msg/s, backlog {rows} rows, lag —",
    "Ingest 18,400 msg/s, backlog 25,000 rows, lag — (PROPOSED — D04-G4, RULED (orchestrator, 2026-10-29, #2701 ledger 1 row 57))",
  ],
  "storage.lag.banner": [
    "Ingestion backlog {rows} rows — writes are behind the feed",
    "Ingestion backlog 25,000 rows — writes are behind the feed",
  ],
  "storage.proposed.caption": [
    "PROPOSED — D04-G{n}, RULED (orchestrator, 2026-10-29, #2701 ledger 1 row {row})",
  ],
  "storage.proposed.rows": ["Row counts by table are not produced yet"],
  "storage.proposed.queries": ["Slowest queries are not produced yet"],
  "storage.compaction.schedule": ["weekly, Sundays 03:00 UTC"],
  "storage.symbols.attributed": [
    "{sum} of {used} attributed to symbols ({pct})",
    "813.6 GB of 1,188.0 GB attributed to symbols (68.5 %)",
  ],
  "storage.migration.banner": [
    "Migration pending · {n} pending · {from} → {to} — applied with the next release",
    "Migration pending · 1 pending · 0008 → 0009 — applied with the next release",
  ],
  "storage.unavailable": ["Disk figures could not be loaded."],
  "storage.stale.announce": ["Storage figures are stale"],
  "notice.panel_read_only": [
    "Read-only — read-only while viewing as {user}.",
    "Read-only — read-only while viewing as alex.",
  ],
  "storage.vacuum.button": ["Vacuum Postgres…"],
  "storage.vacuum.title": ["Vacuum Postgres?"],
  "storage.vacuum.body": [
    "Reclaims space from deleted rows. Nothing is deleted. Queries may be slower while it runs.",
  ],
  "storage.audited": ["This action is audited."],
  "storage.confirm.cancel": ["Cancel"],
  "storage.job.running": [
    "{verb} running · {pct} %",
    "Compaction running · 42 %",
    "Import running · 38 %",
  ],
  "storage.job.started": ["{verb} started", "Compaction started", "Import started"],
  "storage.job.stop": ["Stop job"],
  "storage.job.refused.running": [
    "A {verb} is already running.",
    "A compaction is already running.",
  ],
  "storage.vacuum.succeeded": ["Vacuumed at {HH:MM} UTC"],
  "storage.vacuum.failed": ["Vacuum failed (`<code>`); nothing was deleted."],
  "storage.vacuum.cancelled": ["Vacuum cancelled; nothing was deleted."],
  "storage.vacuum.unknown": ["Vacuum status is no longer available on the server."],
  "storage.import.button": ["Import archives"],
  "storage.import.consequence": [
    "Imports Bybit's public daily trade archives (trades only, no book data). Recorded data wins where they overlap. Re-running skips finished days.",
  ],
  "storage.import.tag": ["Archive-derived · trades only · no book data"],
  "storage.import.range.reason": ["Choose a range of at most 366 days."],
  "storage.import.progress": [
    "{done} of {n} days · {pct} %",
    "12 of 31 days · 38 %",
    "30 of 31 days · 96 %",
  ],
  "storage.import.skipped_count": ["{k} skipped", "1 skipped"],
  "storage.import.finished": [
    "Import finished: {symbol}, {from} → {to}",
    "Import finished: BTCUSDT, 2026-01-01 → 2026-01-31",
  ],
  "storage.import.columns": ["Day", "Status", "Reason", "Rows"],
  "storage.import.status": ["done", "skipped", "error", "downloading"],
  "storage.import.reason.checksum": ["Checksum did not match; the file was skipped."],
  "storage.import.reason.parse": ["The file could not be read; it was skipped."],
  "storage.import.reason.download": [
    "The file could not be downloaded; run the import again to retry it.",
  ],
  "storage.import.reason.already": ["Already imported on an earlier run."],
  "storage.import.overlap": [
    "{rows} rows inside recorded windows were discarded — recorded data wins.",
    "660,000 rows inside recorded windows were discarded — recorded data wins.",
  ],
  "storage.import.summary": [
    "Imported {days} days of {symbol} trades · {k} file skipped · {e} file failed · {rows} overlapping rows discarded",
    "Imported 29 days of BTCUSDT trades · 1 file skipped · 1 file failed · 660,000 overlapping rows discarded",
  ],
  "storage.import.failed": [
    "Import failed ({code}). Finished days are kept; run it again to resume.",
    "Import failed (download_failed). Finished days are kept; run it again to resume.",
  ],
  "storage.import.cancelled": ["Import cancelled. Finished days are kept."],
  "storage.import.unknown": [
    "The import's status is no longer available on the server. Run it again: finished days are skipped.",
  ],
  "storage.import.resume": ["Run it again to resume: finished days are skipped."],
  "storage.links.storage_details": ["Storage details →"],
  "storage.links.health": ["System health →"],
} as const satisfies Readonly<Record<string, readonly string[]>>;

export type StorageDeckKey = keyof typeof STORAGE_DECK;

type ImportSkipReason = ArchiveImportResult["files_skipped"][number]["reason"];

/**
 * An import's skipped-file code (`22` `ArchiveImportResult`, the served names, BQ-4) to its
 * E16-D04 sentence; null where the deck has none (a file the archive lacks, or one over the size
 * cap), and a code this table lacks (the set is open-ended), are shown as the code token alone.
 * `storage.import.reason.already` words `files_already_imported`, a count, not a skip code.
 */
export const IMPORT_SKIP_REASONS = {
  import_checksum_failed: "storage.import.reason.checksum",
  import_parse_failed: "storage.import.reason.parse",
  import_download_failed: "storage.import.reason.download",
  import_file_not_found: null,
  import_file_too_large: null,
} as const satisfies Readonly<Record<ImportSkipReason, StorageDeckKey | null>>;
