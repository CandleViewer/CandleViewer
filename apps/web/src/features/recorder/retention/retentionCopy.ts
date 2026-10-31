/**
 * SCR-141's copy (E16-S03), verbatim: E16-D03 §14 as `docs/design/E16/E16-D06-copy.json` keys it.
 * A row is its parent's quoted strings in order, a template before its example (the boards'
 * fixtures); the deck joins them with " · " and a test holds every row to it. A placeholder is the
 * parent's own token ("{Stream}", "{size clause}"), filled at render; nothing here is composed from
 * a server `message` or `detail` (E16-D06 §20.3). The view-as reason `rbac.view_as` is not here: it
 * is E09-D09's, `@candleviewer/ui`'s `RBAC_REASONS`. A word the deck lacks is PROPOSED apart
 * (`RETENTION_PROPOSED`). Nothing renders these rows until SCR-141 mounts: no route, no flag
 * (C-4.13).
 */
import type { generated } from "@candleviewer/protocol";

type StreamKind = generated.rest.components["schemas"]["StreamKind"];

/** `retention.stream.*`: the word for each `22` `StreamKind`, in the contract's order. */
export const STREAM_WORDS = {
  trades: "Trades",
  orderbook_delta: "Order-book deltas",
  orderbook_snapshot: "Order-book snapshots",
  tickers: "Tickers",
  klines: "Exchange klines",
  liquidations: "Liquidations",
  open_interest: "Open interest",
  funding: "Funding rates",
} as const satisfies Readonly<Record<StreamKind, string>>;

export const RETENTION_DECK = {
  "retention.title": ["Retention policy"],
  "retention.rule": ["A symbol's rule wins over the global default. Pinned symbols are exempt."],
  "retention.loading": ["Loading retention policy…"],
  "retention.section.global": ["Global defaults"],
  "retention.section.overrides": ["Per-symbol overrides"],
  "retention.section.pinned": ["Pinned symbols (exempt)"],
  "retention.stream.*": Object.values(STREAM_WORDS),
  "retention.field.days": ["Retention (days)", "days"],
  "retention.help.archive": [
    "Days in the fast store before the nightly move to Parquet. Parquet keeps it for {total} in total.",
    "Days in the fast store before the nightly move to Parquet. Parquet keeps it for 24 months in total.",
  ],
  "retention.help.drop": ["Days before this stream's data is deleted for good, Parquet included."],
  "retention.help.derived": [
    "Bars, footprints and profiles are rebuilt from trades, so trades must be kept at least as long as them.",
  ],
  "retention.kept_until": ["Kept in Parquet until {total}", "Kept in Parquet with no end date"],
  "retention.action.archive_parquet": ["Move to Parquet after"],
  "retention.action.drop": ["Delete after"],
  "retention.baseline": ["Default {n} d", "Default 30 d"],
  "retention.reset": ["Reset to default"],
  "retention.no_source": [
    "This stream has no other source.",
    "Irreplaceable: there is no history to fetch again.",
  ],
  "retention.add": ["Add override"],
  "retention.remove": ["Remove {symbol} {stream} rule", "Remove ETHUSDT order-book deltas rule"],
  "retention.removed.status": [
    "Removed: follows the global rule ({n} d)",
    "Removed: follows the global rule (7 d)",
  ],
  "retention.undo": ["Undo"],
  "retention.remove.title": [
    "Remove the {symbol} {stream} rule?",
    "Remove the ETHUSDT trades rule?",
  ],
  "retention.confirm.removed": [
    "{symbol} follows the global rule: {n} days, then Parquet.",
    "ETHUSDT follows the global rule: 7 days, then Parquet.",
  ],
  "retention.exempt": ["Exempt (pinned)"],
  "retention.pin.manage": ["Manage pin in Recorder"],
  "retention.pin.help": [
    "Pinned symbols are never deleted by retention. Unpin a symbol in the Recorder to let its data follow the policy; the Recorder states the volume that becomes eligible.",
  ],
  "retention.pin.none": ["No pinned symbols."],
  "retention.err.min": ["Keep at least 1 day."],
  "retention.err.max": ["At most 3650 days (10 years)."],
  "retention.err.int": ["Whole days only."],
  "retention.err.summary": ["Fix {n} fields before applying.", "Fix 2 fields before applying."],
  "retention.apply.no_changes": ["No changes to apply."],
  "retention.apply.preview_first": ["Preview the change first."],
  "retention.apply.typed": ["Type {word} to confirm.", "Type trades to confirm."],
  "retention.apply.invalid": ["Fix {n} fields.", "Fix 1 field.", "Fix 2 fields."],
  "retention.preview.button": ["Preview changes"],
  "retention.preview.title": ["What becomes eligible for deletion"],
  "retention.preview.row": [
    "{symbol} · {stream} · {from} · {to} · about {size}",
    "{symbol} · {stream} · — · — · about 0 GB now (recorded since about {since})",
    "ETHUSDT · Trades · — · — · about 0 GB now (recorded since about 2026-09-12)",
  ],
  "retention.preview.total": ["About {size} across {n} symbols", "About 0 GB now across 1 symbol"],
  "retention.preview.none": [
    "Nothing becomes eligible: this policy keeps data as long as today.",
    "Nothing becomes eligible: this change keeps data longer.",
  ],
  "retention.confirm.tiering": [
    "Moves {stream} older than {n} days to Parquet sooner; it is still kept for {total}. This change deletes nothing.",
    "Moves trades older than 7 days to Parquet sooner; it is still kept for 24 months. This change deletes nothing.",
  ],
  "retention.preview.pinned": [
    "{symbol} is pinned and is not affected.",
    "BTCUSDT is pinned and is not affected.",
  ],
  "retention.preview.caption": [
    "Estimated from the storage report, per symbol across its recorded streams; the retention run's audit record carries the exact figures.",
  ],
  "retention.confirm.title": [
    "Delete {stream} after {n} days?",
    "Delete trades after 7 days?",
    "Delete trades after 3 days?",
  ],
  "retention.confirm.title_symbol": [
    "Delete {symbol} {stream} after {n} days?",
    "Delete ETHUSDT trades after 14 days?",
  ],
  "retention.confirm.title_multi": [
    "Shorten retention for {k} streams?",
    "Shorten retention for 2 streams?",
  ],
  "retention.confirm.title_total_move": [
    "Move {stream} to Parquet and shorten retention to {total}?",
    "Move trades to Parquet and shorten retention to 24 months?",
    "Move trades to Parquet and shorten retention to 800 days?",
  ],
  "retention.confirm.title_total": [
    "Shorten {stream} retention to {total}?",
    "Shorten trades retention to 24 months?",
  ],
  "retention.confirm.body": [
    "{Stream} for {scope} older than {n} days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. {size clause} It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
    "Trades for ETHUSDT older than 7 days become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. Nothing recorded before 2026-09-07 exists yet (about 0 GB now; recording started about 2026-09-12), so the first run deletes nothing. It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
  ],
  "retention.confirm.size": [
    "About {size} across {symbol}'s recorded streams, recorded from {from} to {to}, goes at the first run.",
    "Nothing recorded before {to} exists yet (about 0 GB now; recording started about {since}), so the first run deletes nothing.",
    "this sweep",
  ],
  "retention.confirm.body_now": [
    "{Stream} for {scope} older than {n} days are deleted when you apply: a retention sweep starts now, and every daily run repeats it, Parquet included. {size clause} It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
    "Trades for ETHUSDT older than 7 days are deleted when you apply: a retention sweep starts now, and every daily run repeats it, Parquet included. Nothing recorded before 2026-09-07 exists yet (about 0 GB now; recording started about 2026-09-12), so this sweep deletes nothing. It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
  ],
  "retention.confirm.body_removed": [
    "{symbol} then follows the global rule.",
    "ETHUSDT then follows the global rule.",
  ],
  "retention.confirm.body_multi": [
    "{Stream} for {scope}: older than {n} days",
    "become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included.",
    "It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
  ],
  "retention.confirm.body_total": [
    "{Stream} for {scope} older than {total} become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. {size clause} It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
    "Trades for ETHUSDT older than 24 months become eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it, Parquet included. Nothing recorded before 2024-09-14 exists yet (about 0 GB now; recording started about 2026-09-12), so the first run deletes nothing. It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
  ],
  "retention.help.drop_cold": [
    "Days before this stream's Parquet copy is deleted for good. The fast store keeps its rows.",
  ],
  "retention.confirm.body_cold": [
    "{Stream} for {scope}: the Parquet copy older than {n} days becomes eligible for deletion at the next retention run (daily, 03:00 UTC) and at every run after it; the fast store keeps its rows. {size clause} It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
  ],
  "retention.confirm.body_cold_now": [
    "{Stream} for {scope}: the Parquet copy older than {n} days is deleted when you apply: a retention sweep starts now, and every daily run repeats it; the fast store keeps its rows. {size clause} It cannot be undone. Replay, footprint history and the journal lose the deleted days.",
  ],
  "retention.confirm.trades_extra": ["Bars built from these trades can no longer be rebuilt."],
  "retention.confirm.typed": ["Type {word} to confirm", "Type trades to confirm"],
  "retention.confirm.ok": ["Apply · delete eligible data at the next run"],
  "retention.confirm.ok_now": ["Apply · start the retention run"],
  "retention.confirm.lengthen.title": ["Keep {stream} for {n} days?", "Keep trades for 90 days?"],
  "retention.confirm.lengthen.body": [
    "Nothing is deleted. The fast store settles at most about {size}, plus pinned data.",
    "Nothing is deleted. The fast store settles at most about 189.8 GB, plus pinned data.",
    "This change deletes nothing more. The retention run that starts now still deletes what the current rules already make eligible. The fast store settles at most about {size}, plus pinned data.",
  ],
  "retention.confirm.plain.title": ["Apply the retention changes?"],
  "retention.confirm.plain.body": ["Nothing is deleted. {detail}"],
  "retention.confirm.plain.body_now": [
    "This change deletes nothing more. The retention run that starts now still deletes what the current rules already make eligible. {detail}",
    "Nothing is deleted.",
  ],
  "retention.dirty": ["Unsaved changes — Cancel or Esc discards them."],
  "retention.stepup.code": ["You'll confirm with your password and a code."],
  "retention.stepup.grace": ["Still trusted for recorder changes · {mm:ss}"],
  "retention.stepup.not_sent": ["Not sent"],
  "retention.audited": ["This action is audited."],
  "retention.apply_now": ["Apply now (start a retention run)"],
  "retention.footer.buttons": ["Cancel", "Apply", "Close"],
  "retention.next_run": ["Next retention run: daily at 03:00 UTC"],
  "retention.job.queued": ["Retention run queued"],
  "retention.job.running": ["Retention run running · {pct} %", "Retention run running · 42 %"],
  "retention.job.succeeded": [
    "Retention run succeeded",
    "Retention run succeeded · about {size} freed",
  ],
  "retention.job.failed": [
    "Retention run failed ({code})",
    "Some data may already be deleted: check the storage report.",
  ],
  "retention.job.cancelled": ["Retention run cancelled"],
  "retention.outcome.saved": ["Retention policy saved. Audited as retention.change."],
  "retention.refused.job_running": ["A retention run is already running."],
  "retention.refused.scheduler_off": ["Retention runs are off on this server."],
  "retention.refused.audit": ["Not saved: the audit record could not be written."],
  "retention.refused.invalid": [
    "Bars can't be deleted before the ticks they came from are kept — adjust the tiers.",
    "The server did not accept this policy set.",
  ],
  "retention.refused.unknown": ["Something in this form is not accepted by the server."],
  "retention.estimate": [
    "Under this policy the fast store settles at most about {size} ({pct} % of {cap}), plus pinned data.",
    "Under this policy the fast store settles at most about 189.8 GB (9 % of 2,000 GB), plus pinned data.",
  ],
  "retention.estimate.formula": [
    "Non-pinned growth 520 MB/day × the longest window 365 days ≈ 189.8 GB. Pinned symbols are never deleted by retention: about 780 MB/day today. Parquet keeps archived streams until their horizon; a per-stream figure needs the storage report to split by stream.",
  ],
  "retention.effect": [
    'Shorter retention removes history from replay, footprint and profile look-backs and from journal back-fill after the cut-off date; those views then start at the oldest kept day and show "Older data was removed by the retention policy (<N> days)." Data a saved replay session or an unexported journal trade still needs is kept until they release it.',
  ],
} as const satisfies Readonly<Record<string, readonly string[]>>;

export type RetentionDeckKey = keyof typeof RETENTION_DECK;

/**
 * SCR-141's words the deck lacks, PROPOSED here for E16-D03's owner at its next text touch; not
 * deck rows, so outside `RETENTION_DECK` until D03 adopts them.
 */
export const RETENTION_PROPOSED = {
  /** `{scope}` when no storage report lists the symbols a global rule governs (`scope` null). */
  "retention.scope.unknown": ["every unpinned symbol without its own rule"],
} as const satisfies Readonly<Record<string, readonly string[]>>;
