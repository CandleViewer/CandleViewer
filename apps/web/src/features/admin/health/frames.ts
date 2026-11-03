/**
 * SCR-143's component records (E42-D05 D5, D6; the build plan's §1.2): the REST report and the
 * `system` topic's `health` frames, merged into one record per component. Words (the state, its
 * detail, the last good time) come from the newer source: the frames once one was seen at or after
 * the report answered, else the report; the probe number (`latency_ms`) comes from the report alone.
 * A frame names `not_deployed` as `healthy` with the detail "not deployed" (`23` §15.9), which reads
 * back as `not_deployed`; a name no table knows passes through, and a name in a state the client
 * does not know has no word: its record reads `not_received`, with no number, and never falls back
 * to an older word (fail closed). Pure functions: the store keeps what they fold.
 */
import type { generated } from "@candleviewer/protocol";
import type { ComponentState, HealthReport } from "../ops/opsReads";
import { timeOf } from "../overview/tileModels";

export type SystemUpdate = generated.ws.System;

/** One component's words as a source last gave them. */
export interface Word {
  readonly state: ComponentState;
  readonly detail?: string | undefined;
  /** The last healthy observation, kept for a fault only: a healthy one moves on every probe. */
  readonly lastGoodAt?: number | undefined;
}
/** Every name the last frame listed; null: named in a state the client cannot read. */
export type Words = ReadonlyMap<string, Word | null>;
export const NO_WORDS: Words = new Map();

/** A report the store kept, and when it answered (the client's clock). */
export interface Reported {
  readonly body: HealthReport;
  readonly at: number;
}

/** A record's state: the contract's word, or none readable in the newer frame (A-1084P1-d01). */
export type RecordState = ComponentState | "not_received";

export interface ComponentRecord {
  readonly name: string;
  /** Which source gave the words: a frame, or the report (no frame named it, or it answered later). */
  readonly source: "frame" | "report";
  readonly state: RecordState;
  readonly detail?: string | undefined;
  readonly lastGoodAt?: number | undefined;
  /** A frame's words: `framesSeenAt`; the report's: its answer. Undefined: the frame held at mount [BQ-8]. */
  readonly wordAt?: number | undefined;
  /** The report's `latency_ms` and when the report answered: never a frame's. */
  readonly latencyMs?: number | undefined;
  readonly latencyAt?: number | undefined;
}

const FRAME_STATES = ["healthy", "degraded", "warning", "down"] as const;
type FrameState = (typeof FRAME_STATES)[number];
const FAULTS: ReadonlySet<RecordState> = new Set(["degraded", "warning", "down"]);
/** `23` §15.9: `not_deployed` reaches a frame as `healthy` with this detail. */
const NOT_DEPLOYED = "not deployed";
/** S01's bound on a server string (F34). */
const MAX_TEXT = 500;

const isRecord = (raw: unknown): raw is Record<string, unknown> =>
  typeof raw === "object" && raw !== null && !Array.isArray(raw);
export const isFrameState = (raw: unknown): raw is FrameState =>
  typeof raw === "string" && (FRAME_STATES as readonly string[]).includes(raw);
export const isFault = (state: RecordState): boolean => FAULTS.has(state);

const isProbe = (raw: unknown): raw is number =>
  typeof raw === "number" && Number.isFinite(raw) && raw >= 0;
const textOf = (raw: unknown): string | undefined =>
  typeof raw === "string" && raw !== "" && raw.length <= MAX_TEXT ? raw : undefined;

function wordOf(state: ComponentState, detail: unknown, lastGood: unknown): Word {
  if (state === "not_deployed") return { state };
  const lastGoodAt = isFault(state) ? timeOf(lastGood) : undefined;
  return { state, detail: textOf(detail), lastGoodAt };
}

const sameWords = (a: Word, b: Word): boolean =>
  a.state === b.state && a.detail === b.detail && a.lastGoodAt === b.lastGoodAt;

/** A frame's component: its name and words (null for a state it cannot read), else null. */
function frameWord(item: unknown): readonly [string, Word | null] | null {
  if (!isRecord(item)) return null;
  const { name, state, detail } = item;
  if (typeof name !== "string" || textOf(name) === undefined) return null;
  if (!isFrameState(state)) return [name, null];
  const undeployed = state === "healthy" && detail === NOT_DEPLOYED;
  return [name, wordOf(undeployed ? "not_deployed" : state, detail, item["last_good_at"])];
}

/**
 * `frame`'s components, which are every probe (`23` §15.9), over `words`: a name it no longer lists
 * goes. The same words keep their object, so a frame that changes one component changes one
 * record (one tile renders, the 2 ms budget's precondition); no word carries a time, "as of" is the
 * store's one `framesSeenAt` [BQ-8]. Returns `words` when nothing changed.
 */
export function foldHealthFrame(words: Words, frame: SystemUpdate): Words {
  if (!Array.isArray(frame.components)) return words;
  const next = new Map<string, Word | null>();
  let changed = false;
  for (const item of frame.components) {
    const read = frameWord(item);
    if (read === null) continue;
    const [name, word] = read;
    const prev = words.get(name);
    const same =
      prev === null || word === null ? prev === word : prev !== undefined && sameWords(prev, word);
    next.set(name, same ? (prev ?? null) : word);
    changed ||= !same;
  }
  return changed || next.size !== words.size ? next : words;
}

/**
 * One record per component: the report's in server order, then the frames' others in theirs. A
 * component's words are the frames' when one was seen (`framesSeenAt`, the store's one number) at or
 * after the report answered, else the report's; a frame held at mount is older than any answer.
 * Its number is the report's alone. "As of" [BQ-8: the newest frame seen]: a frame's words read
 * `framesSeenAt` (undefined until a frame arrives after mount), the report's words its answer time.
 * The newer source is the truth, both ways: a name the newer frame does not list (or lists in a
 * state the client cannot read), a name the newer report does not list though the older frames
 * still carry it, and a name the newer report serves in such a state, keep their record as
 * `not_received`, with no number and no older word, so the tile stays and D9 withholds
 * (C-1084P1-02, A-1084P1-d01).
 */
export function mergeComponents(
  report: Reported | undefined,
  words: Words,
  framesSeenAt: number | undefined,
): ComponentRecord[] {
  const framesNewer = framesSeenAt !== undefined && framesSeenAt >= (report?.at ?? 0);
  type Served = NonNullable<HealthReport["components"]>[number];
  const served = new Map<string, Served>();
  for (const c of report?.body.components ?? []) {
    if (typeof c.name === "string" && !served.has(c.name)) served.set(c.name, c);
  }
  const names = [...served.keys(), ...[...words.keys()].filter((name) => !served.has(name))];
  return names.flatMap((name): ComponentRecord[] => {
    const c = served.get(name);
    // The report serves a name with no readable state (`vetHealthReport` keeps it): no word.
    const rest =
      c === undefined
        ? undefined
        : c.state === undefined
          ? null
          : wordOf(c.state, c.detail, c.last_good_at);
    const frame = words.get(name);
    // Newest source wins both ways: a report newer than the frames is the whole truth, so a name
    // it no longer lists (`rest` undefined) has no word, though the older frames still carry one.
    const fromFrame = framesNewer || report === undefined;
    const word = fromFrame ? (frame ?? null) : (rest ?? null);
    if (word === null) {
      const wordAt = fromFrame ? framesSeenAt : report?.at;
      return [{ name, source: fromFrame ? "frame" : "report", state: "not_received", wordAt }];
    }
    const source = fromFrame ? "frame" : "report";
    const latencyMs = c?.latency_ms;
    const number =
      report === undefined || !isProbe(latencyMs) ? {} : { latencyMs, latencyAt: report.at };
    const { state, detail, lastGoodAt } = word;
    const wordAt = source === "frame" ? framesSeenAt : report?.at;
    return [{ name, source, state, detail, lastGoodAt, wordAt, ...number }];
  });
}

/** The newest frame's overall word, `health` (a frame never sends `not_deployed`). */
export const frameOverall = (frame: SystemUpdate): FrameState | undefined =>
  isFrameState(frame.health) ? frame.health : undefined;

/**
 * The clock's sources (HL-8): the frames' newest offset, when it last changed and when a frame last
 * carried one; the newest `clock_drift` notice that came while the page was open, and its offset.
 */
export interface ClockSeen {
  readonly offsetMs?: number | undefined;
  readonly offsetAt?: number | undefined;
  readonly offsetSeenAt?: number | undefined;
  readonly driftAt?: number | undefined;
  readonly driftMs?: number | undefined;
}

export type Clock =
  | { readonly kind: "ok"; readonly offsetMs: number; readonly at?: number | undefined }
  | { readonly kind: "drift"; readonly offsetMs?: number | undefined; readonly at: number }
  | { readonly kind: "not_measured" };

const offsetOf = (raw: unknown): number | undefined =>
  typeof raw === "number" && Number.isSafeInteger(raw) ? raw : undefined;

/**
 * A `health` or `clock_drift` frame over `seen`. A drift notice counts only when it arrives while
 * the page is open: one held at mount may be long over. A health frame without an offset is a
 * clock no longer measured.
 */
export function foldClock(seen: ClockSeen, frame: SystemUpdate, at: number | undefined): ClockSeen {
  const offset = offsetOf(frame.clock_offset_ms);
  if (frame.kind === "clock_drift") {
    return at === undefined ? seen : { ...seen, driftAt: at, driftMs: offset };
  }
  if (offset === undefined) {
    return seen.offsetMs === undefined ? seen : { ...seen, offsetMs: undefined, offsetAt: at };
  }
  const changed = offset !== seen.offsetMs || (seen.offsetAt === undefined && at !== undefined);
  return { ...seen, offsetSeenAt: at, ...(changed ? { offsetMs: offset, offsetAt: at } : {}) };
}

/**
 * HL-8's three words: drift while the newest clock word is a drift notice; else the frames'
 * offset, else the report's (null until E08 lands time sync, never a made-up 0); else not measured.
 */
export function clockOf(seen: ClockSeen, report: Reported | undefined): Clock {
  const { driftAt, offsetSeenAt } = seen;
  if (driftAt !== undefined && (offsetSeenAt === undefined || driftAt > offsetSeenAt)) {
    return { kind: "drift", offsetMs: seen.driftMs, at: driftAt };
  }
  if (seen.offsetMs !== undefined)
    return { kind: "ok", offsetMs: seen.offsetMs, at: seen.offsetAt };
  const rest = offsetOf(report?.body.clock_offset_ms);
  return rest === undefined
    ? { kind: "not_measured" }
    : { kind: "ok", offsetMs: rest, at: report?.at };
}
