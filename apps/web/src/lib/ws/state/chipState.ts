// #5345 (E08-D14 DF-1): the CMP-076 chip's state, E17-D02 §3's selector, pure over what the chip
// reads: the link (`WsState`), the shell's SCR-153 fact that the exchange's public feed is down
// (§2 row 13), the `connection_quality` multiplier (row 5), the live public topics' freshness
// (rows 10–12, 16) and a clock. No timers or I/O: the caller ticks it at 1 Hz and keeps the two
// holds (`ChipMemory`) with `stepChipMemory`. Thresholds are E17-D01 §4.1's (T1–T3).
import { connectionPresentation } from "./connectionPresentation";
import type { TopicStatus, WsState } from "./types";

/** T1 per judged family (E17-D01 §4.1, architect ruling A2): book 2 s, ticker 5 s, trades 10 s. */
export const STALE_T1_MS = { book: 2_000, ticker: 5_000, trades: 10_000 } as const;
/** T2 = 3 × T1: the strong chip (row 11). */
export const STALE_T2_FACTOR = 3;
/** T3: the Delayed chip shows this long at least, as anti-flicker; never a hold against a higher state. */
export const DELAYED_MIN_MS = 5_000;

export type JudgedFamily = keyof typeof STALE_T1_MS;

/**
 * The families the chip judges by their silence (E17-D01 §4.1 T1). Private topics and `system`
 * emit on change, so silence is normal for them; the derived ones (bars, footprint, heatmap,
 * profile, metrics, liquidations) inherit their symbol's ticker staleness and are in-panel only.
 */
export function judgedFamily(ch: string): JudgedFamily | null {
  const dot = ch.indexOf(".");
  switch (dot < 0 ? ch : ch.slice(0, dot)) {
    case "book":
      return "book";
    case "ticker":
      return "ticker";
    case "trades":
      return "trades";
    default:
      return null;
  }
}

/**
 * What the WS client knows of one consumer's topic (`WsClientHandle.topics()`), as of the call. Its
 * `…AtMs` / `…FromMs` times are on the client's monotonic clock (`timers.now`), so a step of the
 * wall clock moves no age; `lastDataMs` is wall time, for the "last data … UTC" text only.
 */
export interface TopicReading {
  readonly ch: string;
  /** The replay session it reads; `undefined` for the live stream. */
  readonly rs: string | undefined;
  readonly source: "live" | "replay";
  readonly status: TopicStatus;
  /**
   * Its newest fresh frame: a `d`, or a `snap` without `meta.stale`, and never a ticker frame whose
   * every item says `stale` (23 §14.8); `null` before its first (row 13's hold counts it held).
   */
  readonly freshAtMs: number | null;
  /** What T1 and T2 age it from: its newest fresh frame (its consume time before one), or the link's last coming up when later. */
  readonly agedFromMs: number;
  /** Wall ms of its newest fresh frame; `null` before its first. */
  readonly lastDataMs: number | null;
  /** Its baseline's `meta.stale` (23 §7.2): held from that `snap` to the next one. */
  readonly serverStale: boolean;
  /**
   * Row 16: the link dropped (or it was made while down) and no `snap` has come since. The chip
   * holds Reconnecting for it for its T1 from the link's coming up at most, then reads its age.
   */
  readonly awaitingReconnect: boolean;
}

export interface ChipInput {
  readonly ws: WsState;
  /**
   * SCR-153's fact (`degradedIssues`): `exchange_state` / `health.exchange` `public_ws` connecting
   * or disconnected. Row 13's other source, `err exchange_unavailable`, is deliberately unfed: the
   * gateway never sends it on the socket (#32).
   */
  readonly upstreamDown: boolean;
  /** `connection_quality.applied.throttle_multiplier`, vetted: "Reduced rate ×N" (§10 A). */
  readonly throttleMultiplier: number | undefined;
  readonly topics: readonly TopicReading[];
  /** The clock the topics' times are on (the client's monotonic one); the two holds run on it too. */
  readonly clockMs: number;
}

/** The two holds the selector cannot see in its input; `stepChipMemory` keeps them, on `clockMs`. */
export interface ChipMemory {
  /** When the feed went down: the chip reads it until each judged topic has a fresh frame after it (§3 exits). */
  readonly upstreamSinceMs: number | null;
  /** T3: when Delayed began, and its multiplier, for its 5 s minimum. */
  readonly delayed: { readonly sinceMs: number; readonly multiplier: number | undefined } | null;
}

export const NO_CHIP_MEMORY: ChipMemory = Object.freeze({ upstreamSinceMs: null, delayed: null });

/** One of the five chip values (E17-D02 §3, CMP-076) with what its word and name need. */
export type ChipView =
  | { readonly status: "live" }
  | { readonly status: "delayed"; readonly throttleMultiplier: number | undefined }
  | {
      readonly status: "stale";
      /** Row 13 (the exchange's feed), row 12 (`meta.stale`), rows 10–11 (a topic's age). */
      readonly cause: "upstream" | "server" | "age";
      /** The oldest stale topic's age (`age` only): the chip's word. */
      readonly ageMs: number | undefined;
      /** The oldest age among the topics past T2 (`age` only): §11 row 4's sentence. */
      readonly t2AgeMs: number | undefined;
      /** T2 (`age` only): the strong variant. */
      readonly strong: boolean;
      /** The last fresh frame the chip names ("last data 13:42:05 UTC"); `null` when it has none. */
      readonly lastGoodTs: number | null;
      /** The symbols past T2, the oldest first (§11 row 4's sentence). */
      readonly t2Symbols: readonly string[];
    }
  | {
      readonly status: "reconnecting" | "offline";
      readonly attempt: number | undefined;
      /** Before the session's first `auth_ok`: "Connecting…" (§5, Q1). */
      readonly firstConnect: boolean;
      readonly lastGoodTs: number | null;
    };

interface Judged {
  readonly topic: TopicReading;
  readonly family: JudgedFamily;
  readonly ageMs: number;
}

/** The live public topics of the three judged families; a replay, revoked or unjudged one never counts. */
function judged(input: ChipInput): Judged[] {
  const out: Judged[] = [];
  for (const topic of input.topics) {
    const family = judgedFamily(topic.ch);
    if (family === null || topic.rs !== undefined || topic.source !== "live") continue;
    if (topic.status === "revoked") continue;
    out.push({ topic, family, ageMs: Math.max(0, input.clockMs - topic.agedFromMs) });
  }
  return out;
}

/** The symbol a channel names (`ticker.BTCUSDT`); a batched one (`ticker`) names none. */
const symbolOf = (ch: string): string | undefined => ch.split(".")[1];
/** The oldest of `topics` (the greatest age), or `undefined`. */
const oldestOf = (topics: readonly Judged[]): Judged | undefined =>
  topics.reduce<Judged | undefined>(
    (a, b) => (a === undefined || b.ageMs > a.ageMs ? b : a),
    undefined,
  );

/** Whether a judged topic has had no fresh frame since the feed went down at `sinceMs` (or none yet). */
const heldBy = (topics: readonly Judged[], sinceMs: number | null): boolean =>
  sinceMs !== null &&
  topics.some((j) => j.topic.freshAtMs === null || j.topic.freshAtMs <= sinceMs);

/**
 * E17-D02 §3, D2's precedence on one chip: the transport first (keyed on retry state, B-1); then
 * the exchange's feed down (held to each topic's first fresh frame), which `auth_ok`'s `system`
 * snapshot makes known, so it beats row 16's wait for the public snapshots after a reconnect; then
 * the rest of the topic rule — `meta.stale` on ticker or book, a topic past its T2, past its T1 —
 * and Delayed only where the topic rule yields Live (T3's 5 s included).
 */
export function selectChip(input: ChipInput, memory: ChipMemory): ChipView {
  const { chip, lastGoodTs } = connectionPresentation(input.ws);
  if (chip.status === "reconnecting" || chip.status === "offline") {
    return {
      status: chip.status,
      attempt: chip.attempt,
      firstConnect: chip.firstConnect === true,
      lastGoodTs,
    };
  }
  const topics = judged(input);
  const stale = (
    cause: "upstream" | "server" | "age",
    of: readonly Judged[],
  ): Extract<ChipView, { readonly status: "stale" }> => {
    const oldest = oldestOf(of);
    const t2 = of
      .filter((j) => j.ageMs >= STALE_T1_MS[j.family] * STALE_T2_FACTOR)
      .sort((a, b) => b.ageMs - a.ageMs);
    const aged = cause === "age";
    return {
      status: "stale",
      cause,
      ageMs: aged ? oldest?.ageMs : undefined,
      t2AgeMs: aged ? t2[0]?.ageMs : undefined,
      strong: aged && t2.length > 0,
      lastGoodTs: cause === "server" ? null : (oldest?.topic.lastDataMs ?? null),
      t2Symbols: aged
        ? [...new Set(t2.map((j) => symbolOf(j.topic.ch)))].filter((s) => s !== undefined)
        : [],
    };
  };
  if (input.upstreamDown || heldBy(topics, memory.upstreamSinceMs))
    return stale("upstream", topics);
  // Row 16 / §3 exits: Live waits for the public snapshots, each for its own T1 from the link's
  // coming up at most (`ageMs` runs from there). One the worker marks overdue (`stale`), or still
  // undelivered at its T1 (a consumer nobody snapshots: its pane collapsed), reads by its age.
  const owed = (j: Judged): boolean =>
    j.topic.awaitingReconnect && j.topic.status !== "stale" && j.ageMs < STALE_T1_MS[j.family];
  if (topics.some(owed)) {
    return { status: "reconnecting", attempt: undefined, firstConnect: false, lastGoodTs: null };
  }
  if (topics.some((j) => j.topic.serverStale && j.family !== "trades")) return stale("server", []);
  const past = topics.filter((j) => j.ageMs >= STALE_T1_MS[j.family]);
  if (past.length > 0) return stale("age", past);
  if (input.ws.quality === "saturated") {
    return { status: "delayed", throttleMultiplier: input.throttleMultiplier };
  }
  const held = memory.delayed;
  if (held !== null && input.clockMs - held.sinceMs < DELAYED_MIN_MS) {
    return { status: "delayed", throttleMultiplier: held.multiplier };
  }
  return { status: "live" };
}

/**
 * The holds after `input` (pure; the same object back when nothing changed): the feed-down episode
 * starts at its first fact and ends once the fact is gone and every judged topic has had a fresh
 * frame since; Delayed starts at the first saturated state and ends 5 s on once the link improved.
 */
export function stepChipMemory(memory: ChipMemory, input: ChipInput): ChipMemory {
  const up = input.ws.link.kind === "up";
  const since = memory.upstreamSinceMs;
  const upstreamSinceMs = input.upstreamDown
    ? (since ?? input.clockMs)
    : heldBy(judged(input), since)
      ? since
      : null;
  const was = memory.delayed;
  let delayed = was;
  if (up && input.ws.quality === "saturated") {
    const multiplier = input.throttleMultiplier ?? was?.multiplier;
    if (was === null || was.multiplier !== multiplier) {
      delayed = { sinceMs: was?.sinceMs ?? input.clockMs, multiplier };
    }
  } else if (was !== null && (!up || input.clockMs - was.sinceMs >= DELAYED_MIN_MS)) {
    delayed = null;
  }
  if (upstreamSinceMs === since && delayed === was) return memory;
  return { upstreamSinceMs, delayed };
}
