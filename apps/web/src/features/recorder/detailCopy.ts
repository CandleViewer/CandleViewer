/**
 * SCR-140's words for the row detail, Keep forever, retention and Purge data… (E16-S01 PR 3), the strings
 * `copy.ts` (the deck's rows and E16-D02 §3, §4.1, §6) does not hold, each with its source. A string marked
 * PROPOSED is this story's, for its owner at the next text touch (E16-D06 §16.4: a code with no named sentence is
 * the consuming story's to build); its owner is E16-D02 unless named. Nothing here is composed from a server
 * `message` or `detail` (E16-D06 §20.3).
 */
export const DETAIL_TEXT = {
  /** PROPOSED: D02 §6.7's fields, named by its own nouns ("state words, reason, started, streams, …"). */
  fields: {
    state: "State",
    reason: "Reason",
    started: "Started",
    streams: "Streams",
    depth: "Depth",
    retention: "Retention",
    lag: "Lag",
    rows: "Rows in the last hour",
    resyncs: "Resyncs in the last hour",
    lastWrite: "Last write",
    dropped: "Dropped messages",
    size: "Size",
    rate: "Rate (7-day trend)",
    share: "Share of budget",
  },
  /** "42 ms" (D02 §6.7: "lag `lag_ms` ms"). */
  lag: "{ms} ms",
  /** "0.71 GB a day"; "est." while the rate is the add-time estimate (D02 §1). PROPOSED form. */
  rate: "{growth} a day",
  estimated: "est.",
  /** The bar's numeric text (D02 §6.7: "share of the budget (CMP-023 with its number)"); §4.2's words. */
  share: "{pct} % of budget",
  /** D02 §4.1 (stopped): "the tooltip and the row detail say …", verbatim. */
  erodes: "data erodes daily under the {days}-day retention",
  /** D02 §6.4: the retention select's options, "7 · 30 · 90 · 365 days", and "Custom…" (SCR-141). */
  retentionDays: [7, 30, 90, 365] as const,
  days: "{n} days",
  /** A one-day retention (a custom one, SCR-141): never "1 days" (C-5347-08). PROPOSED form. */
  day: "1 day",
  forever: "Forever",
  custom: "Custom…",
  /** PROPOSED (C-5347-06): the Gaps section with none, one line in place of an empty table. */
  noGaps: "No gaps in the last 24 h.",
} as const;

/** E16-D02 §6.4's dialogs: Keep forever on and off, and a retention change (board 18 not drawn: the text binds). */
export const RETENTION_TEXT = {
  /** PROPOSED: the confirms' effect names (CMP-044 names the effect, never "Confirm"). */
  onConfirm: "Keep {symbol} data forever",
  offConfirm: "Stop keeping {symbol} forever",
  /** PROPOSED: §6.4's retention change ("shortening states the GB and the date range that become eligible"). */
  shortenTitle: "Shorten {symbol} retention to {n} days?",
  shortenBody:
    "Retention becomes {n} days, so about {size} recorded before {date} becomes eligible for deletion at the next retention run. Type {symbol} to confirm.",
  shortenConfirm: "Shorten retention to {n} days",
  lengthenTitle: "Lengthen {symbol} retention to {n} days?",
  lengthenBody: "Retention becomes {n} days, and nothing is deleted. Type {symbol} to confirm.",
  lengthenConfirm: "Lengthen retention to {n} days",
} as const;

/** The refusals' words (the generic T4 of E16-D06 §16.4), the code token after them in parentheses. */
export const DETAIL_REFUSED = {
  /** PROPOSED: a refused pin, unpin, retention or depth change. */
  change: "Not changed: the server refused it.",
  /** PROPOSED: a refused purge, the add's words (`pageCopy.ts`). */
  purge: "Not started: the server refused it.",
} as const;

export const PURGE_TEXT = {
  /** PROPOSED (owner E16-D04, beside its `storage.purge.*.reason` rows): the reason field's validity reason. */
  reasonShort: "Give a reason of at least 3 characters.",
  /** PROPOSED (C-5347-04): a purge the server reports done with no `freed_bytes`, never "Purged — of …". */
  finished: "Purge of {symbol} finished.",
  /**
   * PROPOSED code token (C-5347-04): a purge that ended `succeeded` with partitions it could not delete
   * (`Job.result.failed`) reads as `storage.purge.failed` with this code; the server's status is a contract gap.
   */
  partial: "partial",
} as const;
