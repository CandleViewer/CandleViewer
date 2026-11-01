/**
 * SCR-140's row model (E16-S01): REST rows, the `recorder` frame's rows and the refused `idle`
 * entries merged by `symbol` (BQ-7), the row state derived severity-first (BQ-8), the T2 reasons,
 * the state words, the summary line and the 10 s batch's phrases. Pure: the generated protocol
 * types in, plain values out. The server decides every write (C-12.4); a T2 reason here only
 * presents the server's `refusal` and `policy`.
 */
import { DECK, TEXT, fill } from "./copy";
import { formatClock, formatDayMonth, parseMs } from "./model/format";
import type {
  RecordReason,
  RecordedSymbol,
  RecorderFrame,
  RecordingState,
  RecordingStatus,
} from "./model/types";

export * from "./model/announcer";
export * from "./model/disk";
export * from "./model/format";
export type * from "./model/types";

/** CMP-177's `state` (E16-D02 §4.2): the server's states but `idle`, and four the UI derives. */
export type RowState =
  Exclude<RecordingState, "idle"> | "lingering" | "gated" | "refused" | "silent";
type StartRefusal = "symbol_cap" | "disk_pressure";
type StopRefusal = "chart_open" | "position_open";
type Refusal = StartRefusal | StopRefusal;

export interface RecorderRow {
  /** The row's key (BQ-7): the frame carries no id. */
  readonly symbol: string;
  /** REST's id; null for a refused `idle` entry or a symbol the list has not caught up with. */
  readonly id: string | null;
  readonly reason: RecordReason | null;
  readonly state: RowState;
  /** CMP-177's `refusal`: set with `refused` only. */
  readonly refusal: StartRefusal | null;
  /** The row's stop refusal, never derived from `reason` (§4.2). */
  readonly stopBlockedReason: StopRefusal | null;
  readonly recordAgainBlockedReason: "symbol_cap" | null;
  /** While lingering; under a graver state the countdown stays secondary text (BQ-8). */
  readonly lingerUntilMs: number | null;
  readonly startedAt: string | null;
  readonly depth: 1 | 50 | 200 | 500 | null;
  readonly retentionDays: number | null;
  readonly pinned: boolean;
  readonly diskBytes: number | null;
  readonly lastEventAtMs: number | null;
  readonly droppedMessages: number;
}

/** The fields the state derives from (§2: `state`, `lingering`, `refusal`, the gate, `last_event_at`). */
export interface DeriveInput {
  readonly state: RecordingState;
  readonly refusal: Refusal | null;
  readonly lingering: boolean;
  readonly lastEventAtMs: number | null;
}

/** A frame row or a status row; their times arrive parsed (ms vs ISO). */
interface LiveSource {
  readonly state: RecordingState;
  readonly refusal?: string | null;
  readonly lingering?: boolean;
  readonly reason?: RecordReason;
  readonly pinned?: boolean;
  readonly disk_bytes?: number;
  readonly dropped_messages?: number;
}

/** US-REC-008 (D02 D-11): no write for 60 s. USDT perpetuals trade around the clock. */
export const SILENT_AFTER_MS = 60_000;
const DAY_MS = 86_400_000;
const REFUSALS: readonly string[] = ["symbol_cap", "disk_pressure", "chart_open", "position_open"];
/** `refusal` is open-ended for readers (C-6.3): a value this build does not know is no refusal. */
const refusalOf = (value: string | null | undefined): Refusal | null =>
  value != null && REFUSALS.includes(value) ? (value as Refusal) : null;
const isStartRefusal = (r: Refusal | null): r is StartRefusal =>
  r === "symbol_cap" || r === "disk_pressure";

export const isSilent = (lastEventAtMs: number | null, nowMs: number): boolean =>
  lastEventAtMs !== null && nowMs - lastEventAtMs > SILENT_AFTER_MS;

/**
 * BQ-8, severity first (an approved deviation from §4.1's row order, so a closed write gate is
 * never masked, C-2.14): refused (`idle` + a start refusal), stopped and stopping by `state`; then
 * for an active row gated > error > silent > degraded > starting > lingering > recording. Null: an
 * `idle` entry without a start refusal renders no row.
 */
export function deriveRowState(f: DeriveInput, gated: boolean, nowMs: number): RowState | null {
  if (f.state === "idle") return isStartRefusal(f.refusal) ? "refused" : null;
  if (f.state === "stopped" || f.state === "stopping") return f.state;
  if (gated && f.refusal !== "position_open") return "gated";
  if (f.state === "error") return "error";
  if (isSilent(f.lastEventAtMs, nowMs)) return "silent";
  if (f.state === "degraded" || f.state === "starting") return f.state;
  return f.lingering ? "lingering" : "recording";
}

const toLive = (s: LiveSource, lingerUntilMs: number | null, lastEventAtMs: number | null) => ({
  state: s.state,
  refusal: refusalOf(s.refusal),
  lingering: s.lingering ?? false,
  lingerUntilMs,
  lastEventAtMs,
  reason: s.reason ?? null,
  pinned: s.pinned ?? null,
  diskBytes: s.disk_bytes ?? null,
  dropped: s.dropped_messages ?? 0,
});
type Live = ReturnType<typeof toLive>;

/** The frame's rows; before one, the status's (23 §6.2.2: the topic carries what the status serves). */
function liveRows(frame: RecorderFrame | null, status: RecordingStatus | null): Map<string, Live> {
  const rows = new Map<string, Live>();
  for (const s of frame?.symbols ?? []) {
    rows.set(s.symbol, toLive(s, s.linger_until_ms ?? null, s.last_event_at_ms ?? null));
  }
  if (frame !== null) return rows;
  for (const { symbol, state, ...s } of status?.symbols ?? []) {
    if (symbol === undefined || state === undefined) continue;
    rows.set(symbol, toLive({ ...s, state }, parseMs(s.linger_until), parseMs(s.last_event_at)));
  }
  return rows;
}

/** The live states that write rows: one with no write yet is Silent's from when the page first saw it. */
const WRITING: ReadonlySet<RecordingState> = new Set(["recording", "degraded"]);

/**
 * A-5309-08: when the page first saw each live row that writes but has written nothing yet (no
 * `last_event_at`; the server sets it only once a row is written): Silent's clock for that row, a lower
 * bound of how long it has been silent. A row's first sight stands; a row that writes, or stops writing
 * rows, leaves the map.
 */
export function firstSeen(
  previous: ReadonlyMap<string, number>,
  frame: RecorderFrame | null,
  status: RecordingStatus | null,
  nowMs: number,
): ReadonlyMap<string, number> {
  const seen = new Map<string, number>();
  for (const [symbol, live] of liveRows(frame, status)) {
    if (live.lastEventAtMs !== null || !WRITING.has(live.state)) continue;
    seen.set(symbol, previous.get(symbol) ?? nowMs);
  }
  return seen;
}

/** REST seeds a row; a live entry overlays it, unless it is an untracked `idle` (23 §6.2.2). */
function merge(
  symbol: string,
  rest: RecordedSymbol | undefined,
  live: Live | undefined,
  seenAtMs: number | undefined,
) {
  const overlay =
    live !== undefined && (live.state !== "idle" || isStartRefusal(live.refusal))
      ? live
      : undefined;
  return {
    symbol,
    id: rest?.id ?? null,
    state: overlay?.state ?? rest?.state ?? "idle",
    refusal: overlay !== undefined ? overlay.refusal : refusalOf(rest?.refusal),
    lingering: overlay !== undefined ? overlay.lingering : (rest?.lingering ?? false),
    lingerUntilMs: overlay !== undefined ? overlay.lingerUntilMs : parseMs(rest?.linger_until),
    lastEventAtMs: overlay === undefined ? null : (overlay.lastEventAtMs ?? seenAtMs ?? null),
    reason: overlay?.reason ?? rest?.reason ?? null,
    pinned: overlay?.pinned ?? rest?.pinned ?? false,
    diskBytes: overlay?.diskBytes ?? rest?.disk_bytes ?? null,
    dropped: overlay?.dropped ?? 0,
    startedAt: rest?.started_at ?? null,
    depth: rest?.depth ?? null,
    retentionDays: rest?.retention_days ?? null,
  };
}

export interface RowSources {
  /** `listRecordedSymbols` items, in the server's order (the default sort, BQ-10). */
  readonly rest: readonly RecordedSymbol[];
  /** `getRecordingStatus`, the first paint's live view until a frame arrives. */
  readonly status: RecordingStatus | null;
  /** The latest `recorder` frame: a whole frame, never merged (23 §6.2.2). */
  readonly frame: RecorderFrame | null;
  /** The write gate: the frame's `storage` (or REST `StorageUsage.write_gate` before one). */
  readonly gateClosed: boolean;
  /** Silent's clock; while stale, the time the page went stale, so rows keep their words (§3.1). */
  readonly nowMs: number;
  /** `firstSeen`'s map: a live row with no write yet is silent 60 s after the page first saw it. */
  readonly firstSeenMs?: ReadonlyMap<string, number>;
}

/** The rows, REST's order first, then live-only symbols in the frame's order. */
export function buildRows(src: RowSources): RecorderRow[] {
  const live = liveRows(src.frame, src.status);
  const rest = new Map(src.rest.map((r) => [r.symbol, r]));
  const drafts = [...new Set([...rest.keys(), ...live.keys()])].flatMap((symbol) => {
    const m = merge(symbol, rest.get(symbol), live.get(symbol), src.firstSeenMs?.get(symbol));
    const state = deriveRowState(m, src.gateClosed, src.nowMs);
    return state === null ? [] : [{ ...m, state }];
  });
  const maxSymbols = (src.frame?.policy ?? src.status?.policy)?.max_symbols ?? null;
  const capped = symbolCapReached(drafts, maxSymbols);
  return drafts.map((m) => ({
    symbol: m.symbol,
    id: m.id,
    reason: m.reason,
    state: m.state,
    refusal: m.state === "refused" && isStartRefusal(m.refusal) ? m.refusal : null,
    stopBlockedReason:
      m.refusal === "chart_open" || m.refusal === "position_open" ? m.refusal : null,
    recordAgainBlockedReason: m.state === "stopped" && capped ? "symbol_cap" : null,
    lingerUntilMs: m.lingering ? m.lingerUntilMs : null,
    startedAt: m.startedAt,
    depth: m.depth,
    retentionDays: m.retentionDays,
    pinned: m.pinned,
    diskBytes: m.diskBytes,
    lastEventAtMs: m.lastEventAtMs,
    droppedMessages: m.dropped,
  }));
}

/**
 * T2-02 (`recorder.symbol_cap`): the active rows (all but stopped and refused ones) reach
 * `policy.max_symbols` and `symbol` is not among them (§8.5); Record again and Start recording.
 */
export function symbolCapReached(
  rows: readonly Pick<RecorderRow, "symbol" | "state">[],
  maxSymbols: number | null,
  symbol?: string,
): boolean {
  const active = rows.filter((r) => r.state !== "stopped" && r.state !== "refused");
  return (
    maxSymbols !== null && active.length >= maxSymbols && !active.some((r) => r.symbol === symbol)
  );
}

const STOP_KEYS = {
  chart_open: ["recorder.stop_blocked.chart_auto", "recorder.stop_blocked.chart_manual"],
  position_open: ["recorder.stop_blocked.position_auto", "recorder.stop_blocked.position_manual"],
} as const;
export type StopBlockedKey = (typeof STOP_KEYS)[StopRefusal][number];

/** §8.5's key for a T2 Stop: the refusal picks the pair, `reason` manual or not picks the key. */
export function stopBlockedKey(row: RecorderRow): StopBlockedKey | null {
  if (row.stopBlockedReason === null) return null;
  return STOP_KEYS[row.stopBlockedReason][row.reason === "manual" ? 1 : 0];
}

/** A T2 reason's sentence (§8.5; `{grace}` is the policy's linger, decision 1). */
export function t2Reason(key: StopBlockedKey | "recorder.symbol_cap", grace: string): string {
  return fill(DECK[key][0], { "{grace}": grace });
}

const [LINGER, UNDER_A_MINUTE] = DECK["d02.8.r09"];
const COUNTDOWN = "stops in {n} min";

/** §8.2: whole minutes rounded up, "under a minute" below 60 s, past the deadline "stopping". */
export function lingerCountdown(untilMs: number, nowMs: number): string {
  const left = untilMs - nowMs;
  if (left <= 0) return TEXT.lingerPast;
  return left < 60_000 ? UNDER_A_MINUTE : fill(COUNTDOWN, { "{n}": Math.ceil(left / 60_000) });
}

export interface WordsContext {
  readonly nowMs: number;
  readonly maxSymbols: number | null;
  /** A stopped row's last session `ended_at` (`listRecordingSessions`, §2). */
  readonly stoppedAtMs?: number | null;
  /** Its gaps in the last 24 h (`getDataCoverage`). */
  readonly gaps?: number;
}

/**
 * §4.1's state words for a row: the batch says them without a date or gaps (SR-01), and #484 PR 3's row
 * detail passes both. A grid row draws CMP-177's own copy, and a test holds their leading words equal.
 * A recording row names its position only while that refuses its stop (§4.1's Auto: position and
 * "position open" rows).
 */
export function stateWords(row: RecorderRow, ctx: WordsContext): string {
  const w = TEXT.words;
  const gaps = ctx.gaps
    ? ` ${fill(w.gaps, { "{n} gaps": ctx.gaps === 1 ? "1 gap" : `${ctx.gaps} gaps` })}`
    : "";
  switch (row.state) {
    case "recording": {
      if (row.stopBlockedReason !== "position_open") return w.recording + gaps;
      return (row.reason === "position_open" ? w.position : w.positionOpen) + gaps;
    }
    case "lingering":
      return (
        LINGER.replace(COUNTDOWN, lingerCountdown(row.lingerUntilMs ?? ctx.nowMs, ctx.nowMs)) + gaps
      );
    case "degraded":
      return w.degraded + gaps;
    case "refused":
      return row.refusal === "disk_pressure"
        ? w.refusedDisk
        : fill(w.refusedCap, {
            "{limit}-symbol": ctx.maxSymbols === null ? "symbol" : `${ctx.maxSymbols}-symbol`,
          });
    case "silent":
      return fill(w.silent, { "{hh:mm:ss}": formatClock(row.lastEventAtMs ?? ctx.nowMs) });
    case "stopped": {
      const at = ctx.stoppedAtMs ?? null;
      if (at === null) return head(w.stopped);
      const stopped = fill(w.stopped, { "{date}": formatDayMonth(at) });
      if (row.pinned) return `${stopped} · ${w.keptForever}`;
      if (row.retentionDays === null) return stopped;
      return `${stopped} · ${fill(w.goneBy, { "{date}": formatDayMonth(at + row.retentionDays * DAY_MS) })}`;
    }
    default:
      return w[row.state];
  }
}

const head = (words: string): string => (words.split(/ · | \{/)[0] ?? words).trim();

/**
 * SR-01's batch grammar, "ETHUSDT degraded" (§4.1's leading word; the lingering countdown and a gated
 * row's "data dropped" kept, A-5309-11), and SR-02's "SOLUSDT stopped recording". G-01: no "started"
 * string is invented; a new row says its state ("BTCUSDT starting").
 */
export function batchPhrase(row: RecorderRow, ctx: WordsContext): string {
  if (row.state === "stopped") return fill(TEXT.stoppedRecording, { "{symbol}": row.symbol });
  const words = stateWords(row, { nowMs: ctx.nowMs, maxSymbols: ctx.maxSymbols });
  const said = row.state === "lingering" || row.state === "gated" ? words : head(words);
  return `${row.symbol} ${said.charAt(0).toLowerCase()}${said.slice(1)}`;
}

/** The rows' states, the next `rowChanges` call's `previous`. */
export const rowStates = (rows: readonly RecorderRow[]): ReadonlyMap<string, RowState> =>
  new Map(rows.map((r) => [r.symbol, r.state]));

/**
 * SR-01 / SR-02: one phrase per row whose state changed (a new row included), and a row that left
 * while active names its symbol (§9.1). Nothing before the first paint (`previous` null).
 */
export function rowChanges(
  previous: ReadonlyMap<string, RowState> | null,
  rows: readonly RecorderRow[],
  ctx: WordsContext,
): string[] {
  if (previous === null) return [];
  const changed = rows
    .filter((r) => previous.get(r.symbol) !== r.state)
    .map((r) => batchPhrase(r, ctx));
  const present = new Set(rows.map((r) => r.symbol));
  const left = [...previous]
    .filter(([symbol, state]) => !present.has(symbol) && state !== "stopped" && state !== "refused")
    .map(([symbol]) => fill(TEXT.stoppedRecording, { "{symbol}": symbol }));
  return [...changed, ...left];
}

const COUNTED: readonly RowState[] = ["recording", "lingering", "degraded", "gated", "silent"];
const [SUMMARY, STARTING, UPDATED] = DECK["d02.8.r10"];
type Overall = NonNullable<RecordingStatus["overall"]> | RecorderFrame["overall"];

/**
 * §8.2: "Recording 4 symbols · 2 auto-recorded · Recorder healthy", "· 1 starting" with a starting
 * row; the count is the rows recording now (gated and silent ones too: the server still records
 * them), never stopped, refused, stopping or error rows.
 */
export function summaryLine(rows: readonly RecorderRow[], overall: Overall | null): string {
  const counted = rows.filter((r) => COUNTED.includes(r.state));
  const auto = counted.filter((r) => r.reason !== null && r.reason !== "manual").length;
  const word = overall === "not_deployed" ? "not deployed" : overall;
  const line = fill(word === null ? SUMMARY.slice(0, SUMMARY.indexOf(" · Recorder")) : SUMMARY, {
    "{n} symbols": counted.length === 1 ? "1 symbol" : `${counted.length} symbols`,
    "{m}": auto,
    "{healthy|degraded|warning|down}": word ?? "",
  });
  const starting = rows.filter((r) => r.state === "starting").length;
  return starting === 0 ? line : `${line} ${STARTING.replace("1", `${starting}`)}`;
}

/** §3.1: the summary's words while no frame has arrived for 2 s (SR-15). */
export const staleLine = (sinceMs: number): string =>
  fill(TEXT.stale, { "{hh:mm:ss}": formatClock(sinceMs) });

/** "updated 10:31:02 UTC", outside the live region (§8.2). */
export const updatedLine = (atMs: number): string =>
  fill(UPDATED, { "{hh:mm:ss}": formatClock(atMs) });
