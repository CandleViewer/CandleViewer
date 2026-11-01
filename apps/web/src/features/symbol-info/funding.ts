/**
 * CMP-126's state function (E08-D06 §7, D-7), pure: the funding row's words and the polite announcement from the
 * ticker's next funding time, the clock and the symbol's status. The target is a fixed time (never
 * `interval × 60 000`, E24-D01 F11); the digits are for `aria-live="off"` text, and only the 5 min and 1 min marks
 * announce. The clock alarm swaps the seconds for an absolute time when SCR-152's `clock-skew` state is on or the
 * client skew passes ±2 000 ms (`23` §4.2).
 */
import * as copy from "./copy";

/** `23` §4.2: the client-to-server skew warns above this. */
export const CLIENT_SKEW_LIMIT_MS = 2_000;
/** E24-D01's marks; CMP-035's 60, 10 and 0 s do not apply (A-5). */
export const WARN_MS = 5 * 60_000;
export const FINAL_MS = 60_000;

export interface ClockAlarm {
  /** SCR-152's `clock-skew` state is on. */
  readonly shellAlarm: boolean;
  /** The client-to-server skew (`welcome.clock_skew_ms`), `null` when unknown. */
  readonly clientSkewMs: number | null;
  /** The backend-to-Bybit offset (US-MKT-009), `null` when unknown. */
  readonly exchangeOffsetMs: number | null;
}

export const NO_ALARM: ClockAlarm = {
  shellAlarm: false,
  clientSkewMs: null,
  exchangeOffsetMs: null,
};

export interface FundingInput {
  readonly symbol: string;
  readonly trading: boolean;
  /** Epoch ms from the ticker's `next_funding_time_ms`, or `null` when absent. */
  readonly nextFundingMs: number | null;
  readonly nowMs: number;
  readonly alarm?: ClockAlarm;
}

export type FundingState =
  | { readonly kind: "not_trading"; readonly text: string }
  | { readonly kind: "unknown"; readonly text: string }
  | { readonly kind: "passed"; readonly text: string; readonly announce: string }
  | {
      readonly kind: "clock_alarm";
      readonly text: string;
      /** `null` when the offset is unknown: the absolute time alone. */
      readonly note: string | null;
      readonly announce: string | null;
    }
  | {
      readonly kind: "counting";
      readonly text: string;
      /** The ⚠ glyph below 5 min. */
      readonly warn: boolean;
      /** The mark the remaining time is under (5 or 1 min), else `null`; `crossedMark` says when to announce. */
      readonly mark: 5 | 1 | null;
      readonly spoken: string;
    };

const pad2 = (n: number): string => String(n).padStart(2, "0");

/** Floored `hh:mm:ss`: 5 053 771 ms reads "01:24:13". */
export function clockText(remainingMs: number): string {
  const s = Math.floor(Math.max(remainingMs, 0) / 1000);
  return `${pad2(Math.floor(s / 3600))}:${pad2(Math.floor((s % 3600) / 60))}:${pad2(s % 60)}`;
}

const utc = (ms: number, seconds: boolean): string =>
  new Date(ms).toISOString().slice(11, seconds ? 19 : 16);

/** "1 h 24 min", "24 min": whole minutes, at least 1. */
function about(remainingMs: number): string {
  const minutes = Math.max(Math.floor(remainingMs / 60_000), 1);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h === 0
    ? `${String(m)} min`
    : m === 0
      ? `${String(h)} h`
      : `${String(h)} h ${String(m)} min`;
}

/** "1 hour 24 minutes": the spoken name's words (D06 §7). */
function spokenAbout(remainingMs: number): string {
  const minutes = Math.max(Math.floor(remainingMs / 60_000), 1);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const unit = (n: number, word: string): string => `${String(n)} ${word}${n === 1 ? "" : "s"}`;
  return [h > 0 ? unit(h, "hour") : "", m > 0 ? unit(m, "minute") : ""].filter(Boolean).join(" ");
}

/** The alarm is on with the shell's state or a client skew past ±2 000 ms; its shown skew is the larger known one. */
export function alarmSkewMs(alarm: ClockAlarm): {
  readonly on: boolean;
  readonly skewMs: number | null;
} {
  const client = alarm.clientSkewMs === null ? null : Math.abs(alarm.clientSkewMs);
  const on = alarm.shellAlarm || (client !== null && client > CLIENT_SKEW_LIMIT_MS);
  const known = [
    client,
    alarm.exchangeOffsetMs === null ? null : Math.abs(alarm.exchangeOffsetMs),
  ].filter((v): v is number => v !== null);
  return { on, skewMs: known.length === 0 ? null : Math.max(...known) };
}

export function fundingState(input: FundingInput): FundingState {
  if (!input.trading) return { kind: "not_trading", text: copy.noFunding(input.symbol) };
  const target = input.nextFundingMs;
  if (target === null || !Number.isFinite(target)) {
    return { kind: "unknown", text: copy.NEXT_FUNDING_UNKNOWN };
  }
  const remaining = target - input.nowMs;
  // Never negative, never a frozen 00:00:00: past the time it waits for the next ticker.
  if (remaining <= 0) {
    return { kind: "passed", text: copy.SETTLEMENT_PASSED, announce: copy.SETTLEMENT_PASSED };
  }
  const alarm = alarmSkewMs(input.alarm ?? NO_ALARM);
  if (alarm.on) {
    return {
      kind: "clock_alarm",
      text: copy.clockAlarmAt(utc(target, true), about(remaining)),
      note: alarm.skewMs === null ? null : copy.clockSkew(Math.round(alarm.skewMs)),
      announce: alarm.skewMs === null ? null : copy.clockSkew(Math.round(alarm.skewMs)),
    };
  }
  const at = utc(target, false);
  const warn = remaining < WARN_MS;
  const mark = remaining < FINAL_MS ? 1 : warn ? 5 : null;
  return {
    kind: "counting",
    text: (warn ? copy.settlesIn : copy.nextIn)(clockText(remaining), at),
    warn,
    mark,
    spoken: copy.fundingSpokenName(spokenAbout(remaining), at),
  };
}

/** "BTCUSDT funding settles in 5 minutes." for a crossed mark. */
export const markSentence = (symbol: string, mark: 5 | 1): string =>
  copy.fundingSpoken(symbol, mark);

/** Which mark a tick crosses, for "polite once": each of 5 and 1 min announces at most once per target. */
export function crossedMark(prevRemainingMs: number | null, remainingMs: number): 5 | 1 | null {
  if (remainingMs <= 0) return null;
  if (remainingMs < FINAL_MS && (prevRemainingMs === null || prevRemainingMs >= FINAL_MS)) return 1;
  if (remainingMs < WARN_MS && (prevRemainingMs === null || prevRemainingMs >= WARN_MS)) return 5;
  return null;
}
