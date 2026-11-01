/**
 * The retention policy model for SCR-141 (E16-S03; E16-D03 §3, §5, §7): the eight `22` streams and
 * their `21` §7 seed, a draft over the loaded set, the whole-set request, the field checks, and the
 * classification of a diff (a lengthening, a tiering change, or a reduction of kinds K1-K7 with its
 * typed word and its copy keys). Pure and synchronous: no React, no DOM, no fetch and no strings;
 * the dialog renders the deck's sentences from the keys (`RetentionDeckKey`s) and parameters. The
 * client classifies only to choose the confirm; the server validates, audits and decides (C-12.4,
 * C-2.9).
 */
import type { generated } from "@candleviewer/protocol";
import type { RetentionDeckKey } from "./retentionCopy";

type Schemas = generated.rest.components["schemas"];
export type StreamKind = Schemas["StreamKind"];
export type RetentionAction = Schemas["RetentionAction"];
export type RetentionPolicy = Schemas["RetentionPolicy"];
export type RetentionPolicyInput = Schemas["RetentionPolicyInput"];
export type StorageUsage = Schemas["StorageUsage"];
export type SymbolCode = Schemas["Symbol"];
/** `setRetentionPolicies`' body: the whole set, replaced in one transaction (`22`). */
export type RetentionRequest =
  generated.rest.operations["setRetentionPolicies"]["requestBody"]["content"]["application/json"];

/** The contract's eight streams, in its order (`22` `StreamKind`; D03 §2 region (b)). */
export const STREAMS = [
  "trades",
  "orderbook_delta",
  "orderbook_snapshot",
  "tickers",
  "klines",
  "liquidations",
  "open_interest",
  "funding",
] as const satisfies readonly StreamKind[];

/** The two actions the UI offers: `downsample` and `pin` are absences (D03 §1.3; `22` refuses them). */
export const OFFERED_ACTIONS = [
  "archive_parquet",
  "drop",
] as const satisfies readonly RetentionAction[];
export type OfferedAction = (typeof OFFERED_ACTIONS)[number];

/**
 * A stream's `21` §7 seed: the hot window, the total horizon (null: kept forever) and whether the
 * nightly roll-off moves it to Parquet (`recorder/rolloff.py` `ROLLOFF_STREAMS`; D03-C9).
 */
export interface StreamSeed {
  readonly hotDays: number;
  readonly totalDays: number | null;
  readonly rollsOff: boolean;
}

/**
 * Mirrors `recorder/retention_defaults.py` `STREAM_DEFAULTS` and `recorder/rolloff.py`
 * `ROLLOFF_STREAMS` (BQ-10): no route serves it. A test holds it to both and to D03's seed.
 */
export const SEED: Readonly<Record<StreamKind, StreamSeed>> = Object.freeze({
  trades: { hotDays: 30, totalDays: 730, rollsOff: true },
  orderbook_delta: { hotDays: 7, totalDays: 730, rollsOff: true },
  orderbook_snapshot: { hotDays: 30, totalDays: 730, rollsOff: false },
  tickers: { hotDays: 30, totalDays: 730, rollsOff: true },
  klines: { hotDays: 90, totalDays: null, rollsOff: false },
  liquidations: { hotDays: 90, totalDays: null, rollsOff: true },
  open_interest: { hotDays: 90, totalDays: null, rollsOff: false },
  funding: { hotDays: 365, totalDays: null, rollsOff: false },
});

/** `retain_days`' bounds (`22`; `21` `rp_days`). */
export const DAYS_MIN = 1;
export const DAYS_MAX = 3650;
/** A field check's key (D03 §7, the deck's `retention.err.*`): below 1, above 3650, not whole. */
export type DaysError = "min" | "max" | "int";

export function validateDays(days: number): DaysError | null {
  if (days < DAYS_MIN) return "min";
  if (days > DAYS_MAX) return "max";
  return Number.isInteger(days) ? null : "int";
}

/** Days; null is kept forever (the four streams whose §7 total is infinite). */
export type Horizon = number | null;

/**
 * The total horizon a row keeps (`21` §3.6.3 `read_policy_row`, the server's `_checked`): the days
 * for `drop`; max(the days, the §7 total) for `archive_parquet`, forever when that total is.
 */
export function totalHorizon(stream: StreamKind, days: number, action: OfferedAction): Horizon {
  if (action === "drop") return days;
  const total = SEED[stream].totalDays;
  return total === null ? null : Math.max(days, total);
}

/** `a` is shorter than `b`; null is forever. */
const shorter = (a: Horizon, b: Horizon): boolean => a !== null && (b === null || a < b);

/** A row's address: a symbol's override, or the global row (`symbol` null, `22` "Null = global default."). */
export interface RowKey {
  readonly symbol: SymbolCode | null;
  readonly stream: StreamKind;
}

/** One editable row; `days` holds what was entered, valid or not (`validateDays`). */
export interface DraftRow extends RowKey {
  readonly days: number;
  readonly action: OfferedAction;
  /** A staged removal (D03-D15): drawn struck with Undo and never sent. A global row is never removed. */
  readonly removed: boolean;
}

/**
 * The loaded set (`base`) and its edits (`rows`): the eight global rows in `STREAMS` order, the
 * stored overrides by symbol and stream, then the added ones in the order they were added.
 */
export interface Draft {
  readonly base: readonly DraftRow[];
  readonly rows: readonly DraftRow[];
}

const isStream = (value: string): value is StreamKind => Object.hasOwn(SEED, value);
const sameKey = (a: RowKey, b: RowKey): boolean => a.symbol === b.symbol && a.stream === b.stream;
const idOf = (key: RowKey): string => `${key.symbol ?? ""}/${STREAMS.indexOf(key.stream)}`;
/** Global rows first, then each symbol's (code-unit order), each by the contract's stream order. */
const inScopeOrder = <T extends RowKey>(rows: readonly T[]): T[] =>
  [...rows].sort((a, b) => {
    const [x, y] = [idOf(a), idOf(b)];
    return x < y ? -1 : x > y ? 1 : 0;
  });
const seedRow = (stream: StreamKind): DraftRow => ({
  symbol: null,
  stream,
  days: SEED[stream].hotDays,
  action: "archive_parquet",
  removed: false,
});

/**
 * The draft over `listRetentionPolicies`' items. A stream with no global row stands on its seed
 * (BQ-10: the PUT needs all eight); an action the UI does not offer reads as `archive_parquet`, as
 * the server reads it (`21` §3.6.3), so it is never sent back; a repeated row keeps the first; a
 * stream outside the contract is skipped.
 */
export function load(items: readonly RetentionPolicy[]): Draft {
  const rows = new Map<string, DraftRow>();
  for (const item of items) {
    const key: RowKey = { symbol: item.symbol ?? null, stream: item.stream };
    if (!isStream(item.stream) || rows.has(idOf(key))) continue;
    const action = item.action === "drop" ? "drop" : "archive_parquet";
    rows.set(idOf(key), { ...key, days: item.retain_days, action, removed: false });
  }
  const base = [
    ...STREAMS.map((stream) => rows.get(idOf({ symbol: null, stream })) ?? seedRow(stream)),
    ...inScopeOrder([...rows.values()].filter((row) => row.symbol !== null)),
  ];
  return { base, rows: base };
}

function update(draft: Draft, key: RowKey, change: (row: DraftRow) => DraftRow): Draft {
  const at = draft.rows.findIndex((row) => sameKey(row, key));
  if (at < 0) return draft;
  return { ...draft, rows: draft.rows.map((row, i) => (i === at ? change(row) : row)) };
}

export const setDays = (draft: Draft, key: RowKey, days: number): Draft =>
  update(draft, key, (row) => ({ ...row, days }));

export const setAction = (draft: Draft, key: RowKey, action: OfferedAction): Draft =>
  update(draft, key, (row) => ({ ...row, action }));

/** "Reset to default" (D03 §2): the global row back on its seed. */
export const resetToDefault = (draft: Draft, stream: StreamKind): Draft =>
  update(draft, { symbol: null, stream }, () => seedRow(stream));

/** Remove stages the removal (D03-D15); a global row cannot be removed. */
export const stageRemoval = (draft: Draft, key: RowKey): Draft =>
  key.symbol === null ? draft : update(draft, key, (row) => ({ ...row, removed: true }));

export const undoRemoval = (draft: Draft, key: RowKey): Draft =>
  update(draft, key, (row) => ({ ...row, removed: false }));

/**
 * "Add override" (D03 §6 `row-add`): the stream's effective days (its global row's, the seed's while
 * that field is invalid) and Move to Parquet after. A pair that has a row, live or staged for
 * removal, is not added again (Undo restores a staged one).
 */
export function addOverride(draft: Draft, symbol: SymbolCode, stream: StreamKind): Draft {
  if (draft.rows.some((row) => sameKey(row, { symbol, stream }))) return draft;
  const global = draft.rows.find((row) => sameKey(row, { symbol: null, stream }));
  const valid = global !== undefined && validateDays(global.days) === null;
  const days = valid ? global.days : SEED[stream].hotDays;
  const row: DraftRow = { symbol, stream, days, action: "archive_parquet", removed: false };
  return { ...draft, rows: [...draft.rows, row] };
}

/** The "Default {n} d" chip (D03 §2): a global row on its seed; "Reset to default" otherwise. */
export const isAtSeed = (row: DraftRow): boolean =>
  row.symbol === null && row.days === SEED[row.stream].hotDays && row.action === "archive_parquet";

const sameRow = (a: DraftRow, b: DraftRow | undefined): boolean =>
  b !== undefined &&
  sameKey(a, b) &&
  a.days === b.days &&
  a.action === b.action &&
  a.removed === b.removed;

/** Unsaved edits (D03-D16's caption): a row differs from the loaded set, was added, or is staged. */
export const isDirty = (draft: Draft): boolean =>
  draft.rows.length !== draft.base.length ||
  draft.rows.some((row, i) => !sameRow(row, draft.base[i]));

const sameItem = (a: RetentionPolicyInput, b: RetentionPolicyInput | undefined): boolean =>
  b !== undefined &&
  a.stream === b.stream &&
  a.symbol === b.symbol &&
  a.retain_days === b.retain_days &&
  a.action === b.action;

/** Apply has something to send (D03-D1: an empty diff is not sent, it would cost a step-up). */
export function hasChanges(draft: Draft): boolean {
  const now = toRequest(draft).items;
  const then = toRequest({ base: draft.base, rows: draft.base }).items;
  return now.length !== then.length || now.some((item, i) => !sameItem(item, then[i]));
}

/** "Fix {n} fields." (D03 §7): the live rows whose days fail `validateDays`. */
export const invalidCount = (draft: Draft): number =>
  draft.rows.filter((row) => !row.removed && validateDays(row.days) !== null).length;

/**
 * The PUT body, the WHOLE set as `setRetentionPolicies` replaces it: all eight global rows (symbol
 * null) always, then every live override by symbol and stream; a staged removal is left out; never
 * `downsample`, `pin` or `applies_to_pinned` (D03 §1.3; `22` refuses them). The days go as entered:
 * send only when `invalidCount` is 0.
 */
export function toRequest(draft: Draft): RetentionRequest {
  const live = draft.rows.filter((row) => !row.removed);
  const globals = STREAMS.map(
    (stream) => live.find((row) => sameKey(row, { symbol: null, stream })) ?? seedRow(stream),
  );
  const overrides = inScopeOrder(live.filter((row) => row.symbol !== null));
  return {
    items: [...globals, ...overrides].map((row) => ({
      stream: row.stream,
      retain_days: row.days,
      action: row.action,
      symbol: row.symbol,
      applies_to_pinned: false,
    })),
  };
}

/**
 * The rows the policy holds once applied: no staged removal; a field the server would refuse is read
 * at its loaded value, and an invalid added row is left out, so an entry in progress never moves the
 * estimate or the classification.
 */
export function effectiveRows(draft: Draft): readonly DraftRow[] {
  const rows: DraftRow[] = [];
  for (const row of draft.rows) {
    if (row.removed) continue;
    const kept = validateDays(row.days) === null ? row : draft.base.find((b) => sameKey(b, row));
    if (kept !== undefined) rows.push(kept);
  }
  return rows;
}

/**
 * The classification's symbols from the storage report: every symbol with recorded data; the pinned.
 * With no report (`GET /recording/storage` answers 503 before its first sample) `symbols` is null:
 * which symbols hold data, and which are pinned, is unknown (`ClassifyContext`).
 */
export function symbolsOf(storage: StorageUsage | null): {
  readonly symbols: readonly SymbolCode[] | null;
  readonly pinned: readonly SymbolCode[];
} {
  if (storage === null) return { symbols: null, pinned: [] };
  const listed = storage.symbols ?? [];
  return {
    symbols: listed.flatMap((s) => (s.symbol === undefined ? [] : [s.symbol])),
    pinned: listed.flatMap((s) => (s.symbol !== undefined && s.pinned === true ? [s.symbol] : [])),
  };
}

/** When the deletion happens (the confirm's timing clause, D03 §5): the next daily run, or now. */
export type Timing = "next_run" | "now";
export type ReductionKind = "K1" | "K2" | "K3" | "K4" | "K5" | "K6" | "K7";
/** A line's own kind; K5 (several streams or several symbols at once) names a whole confirm only. */
export type LineKind = Exclude<ReductionKind, "K5">;
/** A change to a pair: its total shrinks, its days move to Parquet sooner, it keeps longer, or none. */
export type Effect = "shrink" | "tier" | "lengthen" | "same";

/**
 * A rule's windows: its days and action, the fast-store window (the days for both actions, as
 * `read_policy_row` reads them, `21` §3.6.3: a `drop` row's is its total) and the total horizon.
 */
export interface RuleState {
  readonly days: number;
  readonly action: OfferedAction;
  readonly hot: number;
  readonly total: Horizon;
}

/**
 * How the pairs came under the rule they follow now: its row was edited (the global row, symbol
 * null, or a stored override), an override was added, or one was removed and its pairs fall back to
 * the global row (`symbol` then names the removed override).
 */
export type Rule =
  | { readonly cause: "edited"; readonly symbol: SymbolCode | null }
  | { readonly cause: "added" | "removed"; readonly symbol: SymbolCode };

/** One rule's change over the recorded symbols it governs (D03 §3: a pair's effective rule). */
export type Line = Rule & {
  readonly stream: StreamKind;
  readonly effect: Effect;
  /**
   * The non-pinned symbols whose pair changes through this rule, in code-unit order; null when no
   * storage report lists them (the global rule over unknown symbols, `ClassifyContext`).
   */
  readonly scope: readonly SymbolCode[] | null;
  /** The pinned symbols it would change: exempt, their data is never deleted (D03 §1.3). */
  readonly exempt: readonly SymbolCode[];
  readonly before: RuleState;
  readonly after: RuleState;
};

/**
 * `{total}` (D03 §14): the total after the change; `seed` when the §7 total, the larger, set it
 * ("24 months").
 */
export interface TotalParam {
  readonly days: number;
  readonly seed: boolean;
}

/** A deck key and its parameters: the dialog renders the sentence (`retentionCopy.ts`). */
export interface Copy<K extends RetentionDeckKey, P> {
  readonly key: K;
  readonly params: P;
}
interface StreamDays {
  readonly stream: StreamKind;
  readonly n: number;
}
interface StreamTotal {
  readonly stream: StreamKind;
  readonly total: TotalParam;
}
/** `{scope}`: the line's symbols; null when no report lists them (`RETENTION_PROPOSED` words it). */
interface Scope {
  readonly stream: StreamKind;
  readonly scope: readonly SymbolCode[] | null;
}

/** The confirm's title by kind (D03 §5's table; `retention.confirm.title*`, `retention.remove.title`). */
export type TitleCopy =
  | Copy<"retention.confirm.title", StreamDays>
  | Copy<"retention.confirm.title_symbol", StreamDays & { readonly symbol: SymbolCode }>
  | Copy<"retention.remove.title", { readonly stream: StreamKind; readonly symbol: SymbolCode }>
  | Copy<"retention.confirm.title_multi", { readonly k: number }>
  | Copy<"retention.confirm.title_total_move" | "retention.confirm.title_total", StreamTotal>;

/**
 * A line's consequence sentence (`retention.confirm.body*`): `scope` is its symbols, `n` the days
 * back to the cut-off. The four streams without roll-off take the `_cold` pair (D03-C9).
 */
export type BodyCopy =
  | Copy<
      | "retention.confirm.body"
      | "retention.confirm.body_now"
      | "retention.confirm.body_cold"
      | "retention.confirm.body_cold_now",
      Scope & { readonly n: number }
    >
  | Copy<"retention.confirm.body_total", Scope & { readonly total: TotalParam }>;

/** Several lines: one `retention.confirm.body_multi` paragraph over the confirm's `lines`. */
export type MultiBodyCopy = Copy<"retention.confirm.body_multi", { readonly k: number }>;
/** K4's first sentence, "{symbol} then follows the global rule.". */
export type LeadCopy = Copy<"retention.confirm.body_removed", { readonly symbol: SymbolCode }>;

export type ReductionLine = Line & {
  readonly reductionKind: LineKind;
  /** The total after the change: the cut-off's distance back from the run. */
  readonly total: TotalParam;
  readonly title: TitleCopy;
  readonly lead: LeadCopy | null;
  readonly body: BodyCopy;
};

/** The typed confirm (D03 §5): its kind, typed word, title, body, lines and timing, as keys. */
export interface TypedConfirm {
  readonly reductionKind: ReductionKind;
  /** The typed value (D03-D14): the `22` stream word, the symbol, or "all streams". */
  readonly word: string;
  readonly title: TitleCopy;
  readonly body: BodyCopy | MultiBodyCopy;
  readonly lines: readonly ReductionLine[];
  readonly timing: Timing;
}

/** A pinned symbol a reduction would otherwise reach, with those streams ("Exempt (pinned)"). */
export interface ExemptRow {
  readonly symbol: SymbolCode;
  readonly streams: readonly StreamKind[];
}

export type Classification =
  | { readonly kind: "none" }
  | { readonly kind: "lengthen" | "tiering"; readonly lines: readonly Line[] }
  | {
      readonly kind: "reduction";
      readonly confirm: TypedConfirm;
      readonly exempt: readonly ExemptRow[];
    };
export type Reduction = Extract<Classification, { readonly kind: "reduction" }>;

export interface ClassifyContext {
  /**
   * The storage report's symbols (`symbolsOf`): only their pairs are read. Null with no report:
   * which symbols hold data, or are pinned, is unknown, so any rule whose total shrinks is a
   * reduction (fail closed); an override's line names its symbol, a global row's has `scope` null.
   */
  readonly symbols: readonly SymbolCode[] | null;
  readonly pinned: readonly SymbolCode[];
  readonly applyNow: boolean;
}

/** The typed value when several streams shrink at once (D03 §5, K5). */
export const ALL_STREAMS = "all streams";

const stateOf = (row: DraftRow): RuleState => ({
  days: row.days,
  action: row.action,
  hot: row.days,
  total: totalHorizon(row.stream, row.days, row.action),
});

function effectOf(before: RuleState, after: RuleState): Effect {
  if (shorter(after.total, before.total)) return "shrink";
  if (after.hot < before.hot) return "tier";
  if (shorter(before.total, after.total) || after.hot > before.hot) return "lengthen";
  return "same";
}

function ruleOf(was: DraftRow, now: DraftRow): Rule {
  if (now.symbol !== null)
    return { cause: was.symbol === null ? "added" : "edited", symbol: now.symbol };
  if (was.symbol !== null) return { cause: "removed", symbol: was.symbol };
  return { cause: "edited", symbol: null };
}

const indexed = (rows: readonly DraftRow[]): ReadonlyMap<string, DraftRow> =>
  new Map(rows.map((row) => [idOf(row), row]));

/** A pair's rule (`21` :3093): the symbol's row, else the global row, else the seed. */
const governing = (
  rows: ReadonlyMap<string, DraftRow>,
  symbol: SymbolCode | null,
  stream: StreamKind,
): DraftRow =>
  rows.get(idOf({ symbol, stream })) ?? rows.get(idOf({ symbol: null, stream })) ?? seedRow(stream);

/** A shrinking line's kind, title, lead and body (D03 §5's reduction-kinds table, D03-C9). */
function reductionLine(line: Line, timing: Timing): ReductionLine {
  const { stream, scope, before, after } = line;
  const seedTotal = SEED[stream].totalDays;
  // D03 §14: "24 months" only when the §7 total is the larger; at exactly the total, "{n} days".
  const total: TotalParam =
    after.action === "drop" || seedTotal === null
      ? { days: after.days, seed: false }
      : { days: Math.max(after.days, seedTotal), seed: after.days < seedTotal };
  const now = timing === "now";
  const cold = now ? "retention.confirm.body_cold_now" : "retention.confirm.body_cold";
  const body: BodyCopy = !SEED[stream].rollsOff
    ? { key: cold, params: { stream, scope, n: total.days } }
    : after.action === "archive_parquet"
      ? { key: "retention.confirm.body_total", params: { stream, scope, total } }
      : {
          key: now ? "retention.confirm.body_now" : "retention.confirm.body",
          params: { stream, scope, n: after.days },
        };
  if (line.cause === "removed") {
    const { symbol } = line;
    return {
      ...line,
      reductionKind: "K4",
      total,
      title: { key: "retention.remove.title", params: { symbol, stream } },
      lead: { key: "retention.confirm.body_removed", params: { symbol } },
      body,
    };
  }
  if (after.action === "archive_parquet") {
    const move = before.action === "drop";
    const key = move ? "retention.confirm.title_total_move" : "retention.confirm.title_total";
    const title: TitleCopy = { key, params: { stream, total } };
    return { ...line, reductionKind: move ? "K6" : "K7", total, title, lead: null, body };
  }
  if (line.symbol !== null) {
    const title: TitleCopy = {
      key: "retention.confirm.title_symbol",
      params: { symbol: line.symbol, stream, n: after.days },
    };
    return { ...line, reductionKind: "K3", total, title, lead: null, body };
  }
  const title: TitleCopy = { key: "retention.confirm.title", params: { stream, n: after.days } };
  const reductionKind = before.action === "drop" ? "K2" : "K1";
  return { ...line, reductionKind, total, title, lead: null, body };
}

/** The whole confirm: K5 over several streams, or one stream over several rules or symbols. */
function typedConfirm(
  first: ReductionLine,
  rest: readonly ReductionLine[],
  timing: Timing,
): TypedConfirm {
  const lines = [first, ...rest];
  const streams = new Set(lines.map((line) => line.stream)).size;
  const multi: MultiBodyCopy = { key: "retention.confirm.body_multi", params: { k: lines.length } };
  if (streams > 1) {
    const title: TitleCopy = { key: "retention.confirm.title_multi", params: { k: streams } };
    return { reductionKind: "K5", word: ALL_STREAMS, title, body: multi, lines, timing };
  }
  if (rest.length > 0) {
    // One stream through several rules: the deck has no title for it; K1's, at the shortest total.
    const n = Math.min(...lines.map((line) => line.total.days));
    const title: TitleCopy = {
      key: "retention.confirm.title",
      params: { stream: first.stream, n },
    };
    return { reductionKind: "K5", word: first.stream, title, body: multi, lines, timing };
  }
  return {
    // An unknown scope (no report) keeps its line's kind: the stream is the typed word either way.
    reductionKind: first.scope !== null && first.scope.length > 1 ? "K5" : first.reductionKind,
    word: first.symbol ?? first.stream,
    title: first.title,
    body: first.body,
    lines,
    timing,
  };
}

interface Group {
  readonly line: Line;
  /** Null once the rule reaches the symbols no report lists. */
  scope: SymbolCode[] | null;
  readonly exempt: SymbolCode[];
}

/** A pair to read; `symbol` null: the symbols no report lists (they follow the global row). */
type Pair = readonly [symbol: SymbolCode | null, stream: StreamKind];

/**
 * The pairs `classify` reads: each listed or pinned symbol's eight. With no report (`symbols`
 * null), also each symbol's pair that a row names, before or after the edit, and per stream the
 * unlisted symbols on the global row.
 */
function pairsOf(draft: Draft, context: ClassifyContext): Pair[] {
  const symbols = [...new Set([...(context.symbols ?? []), ...context.pinned])].sort();
  const pairs = symbols.flatMap((symbol) => STREAMS.map((stream): Pair => [symbol, stream]));
  if (context.symbols !== null) return pairs;
  const read = new Set(pairs.map(([symbol, stream]) => idOf({ symbol, stream })));
  for (const row of [...draft.base, ...draft.rows]) {
    if (row.symbol === null || read.has(idOf(row))) continue;
    read.add(idOf(row));
    pairs.push([row.symbol, row.stream]);
  }
  return [...pairs, ...STREAMS.map((stream): Pair => [null, stream])];
}

/**
 * Classifies the diff (D03 §3, D03-D5) over the recorded symbols' (symbol, stream) pairs, each
 * following its own row else the global row: a `reduction` when a non-pinned pair's total horizon
 * shrinks (K1-K7, the typed confirm), else `tiering` when a fast-store window shrinks (nothing is
 * deleted), else `lengthen`, else `none`. A change reaching only pinned symbols is not a reduction,
 * and a field in error takes no part until it is valid (`effectiveRows`). With no storage report
 * (`symbols` null) any rule whose total shrinks is a reduction (`ClassifyContext`).
 */
export function classify(draft: Draft, context: ClassifyContext): Classification {
  const before = indexed(draft.base);
  const after = indexed(effectiveRows(draft));
  const pinned = new Set(context.pinned);
  const groups = new Map<string, Group>();
  const exempt = new Map<SymbolCode, StreamKind[]>();
  for (const [symbol, stream] of pairsOf(draft, context)) {
    const was = governing(before, symbol, stream);
    const now = governing(after, symbol, stream);
    const [from, to] = [stateOf(was), stateOf(now)];
    const effect = effectOf(from, to);
    if (effect === "same") continue;
    const rule = ruleOf(was, now);
    const id = idOf({ symbol: rule.symbol, stream });
    const line: Line = {
      ...rule,
      stream,
      effect,
      scope: [],
      exempt: [],
      before: from,
      after: to,
    };
    const group = groups.get(id) ?? { line, scope: [], exempt: [] };
    groups.set(id, group);
    if (symbol === null) group.scope = null;
    else if (!pinned.has(symbol)) group.scope?.push(symbol);
    else {
      group.exempt.push(symbol);
      if (effect === "shrink") exempt.set(symbol, [...(exempt.get(symbol) ?? []), stream]);
    }
  }
  const lines = inScopeOrder(
    [...groups.values()]
      .filter((group) => group.scope === null || group.scope.length > 0)
      .map((group): Line => ({ ...group.line, scope: group.scope, exempt: group.exempt })),
  );
  const timing: Timing = context.applyNow ? "now" : "next_run";
  const [first, ...rest] = lines
    .filter((line) => line.effect === "shrink")
    .map((line) => reductionLine(line, timing));
  if (first !== undefined) {
    const rows = [...exempt].map(([symbol, streams]): ExemptRow => ({ symbol, streams }));
    return { kind: "reduction", confirm: typedConfirm(first, rest, timing), exempt: rows };
  }
  if (lines.some((line) => line.effect === "tier")) return { kind: "tiering", lines };
  return lines.length > 0 ? { kind: "lengthen", lines } : { kind: "none" };
}
