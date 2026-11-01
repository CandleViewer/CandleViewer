/**
 * SCR-142's words that the deck (`storage/storageCopy.ts`, E16-D04 §14) does not hold, each with its source. A
 * string marked PROPOSED is this story's, for E16-D04's owner at its next text touch (owner E16-D04 unless named);
 * nothing here is composed from a server `message` or `detail` (E16-D06 §20.3).
 */
export const PANEL_TEXT = {
  /** PROPOSED: region (g)'s card, the sketch's "(g) Maintenance" (D04 §2). */
  maintenance: "Maintenance",
  /** `14` SCR-142's sign-off item "per-symbol breakdown for the hot tier": region (e)'s caption. */
  symbolsCaption: "Per-symbol breakdown for the hot tier",
  /** D04 §4 `TIER/per-symbol`: the Pinned column and its word; PROPOSED, the hidden reading of its "—". */
  pinnedColumn: "Pinned",
  pinned: "pinned",
  notPinned: "not pinned",
  /** PROPOSED (A-486P3-06): a listed Symbol's name, the visible symbol first (SC 2.5.3), naming what it opens. */
  openDetail: "{symbol}: open row detail",
  /** PROPOSED: `storage.tier.unreachable` when the component names no last good time. */
  unreachable: "{Tier} unreachable",
  /** D04 §8 `IMPORT/form`: "Symbol (CMP-009)", "From / To (CMP-047 range)"; PROPOSED the range's name. */
  importSymbol: "Symbol",
  importRange: "Date range",
  importFrom: "From",
  importTo: "To",
  /** PROPOSED: the validity reason while no symbol is chosen (the list was empty). */
  chooseSymbol: "Choose a symbol.",
  /** PROPOSED (E16-D06 G-08: the strip renders `Job.status`'s served word, D04 draws running only). */
  queued: "{verb} queued",
  /** PROPOSED: `storage.job.refused.running` for the import, its article agreeing ("A {verb}" reads "An import"). */
  importRunning: "An import is already running.",
  /** PROPOSED (C-486P3-03 (a)): the validity reason for a range ending after today, UTC (D04 §8: past days only). */
  endAfterToday: "Choose a range ending on or before {date}.",
  /**
   * PROPOSED (C-486P3-05): a succeeded compaction's served result, the partitions it left as they were, as counts
   * only (never a partition's key): `{parts}` joins the two below that are not zero.
   */
  compactLeft: "Partitions not compacted: {parts}.",
  compactFailed: "{n} failed the row-count check",
  compactDeferred: "{n} in use by a replay",
  /** PROPOSED with D04-G4 / D04-Q4 (C-486P3-04 (a)): the lag warning's rule, beside its banner. */
  lagThreshold: "Threshold: {batches} batches of {rows} rows for two samples",
  /**
   * PROPOSED (BQ-4: the summary renders the served `ArchiveImportResult`, whose names are not D04-G11's; the labels
   * are the ticket's own words, #486 AC "Import reports its summary honestly").
   */
  summary: {
    processed: "Files processed",
    alreadyImported: "Already imported",
    written: "Rows written",
    overlap: "Rows discarded as overlap",
    skipped: "Files skipped",
    ofTotal: "{n} of {total}",
  },
} as const;
