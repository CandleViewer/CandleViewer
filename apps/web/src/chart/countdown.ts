/**
 * CMP-226's state, pure (E11-S07, BQ-19; E11-D02 §7.4, E11-D06 §6.1): the words and digits for the
 * seconds left to a time bar's close. The clock is the WS-corrected server time: `skewMs` is
 * `connection.clockSkewMs` (server minus local), so server now is `nowMs + skewMs`.
 */

/** US-CHART-008: the warn state starts at 10 s (`warnBelowMs`). */
export const WARN_BELOW_MS = 10_000;
export const NO_COUNTDOWN_TITLE = "No countdown for tick bars";

export type CountdownState =
  | { readonly kind: "normal" | "warn"; readonly text: string; readonly remainingMs: number }
  | { readonly kind: "closed"; readonly text: "closed"; readonly remainingMs: 0 }
  | { readonly kind: "na"; readonly text: "—"; readonly title: string };

/** `m:ss` of a whole number of seconds. */
export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * `intervalMs` is null (or not positive) for a non-time bar, which has no countdown. Seconds round
 * up, so the digits reach `0:01` and never show `0:00` while the bar is still open; at the close the
 * state is `closed` until the caller passes the next bar's open.
 */
export function countdownState(
  barOpenMs: number,
  intervalMs: number | null,
  nowMs: number,
  skewMs: number,
): CountdownState {
  if (intervalMs === null || !Number.isFinite(intervalMs) || intervalMs <= 0) {
    return { kind: "na", text: "—", title: NO_COUNTDOWN_TITLE };
  }
  const remainingMs = barOpenMs + intervalMs - (nowMs + skewMs);
  if (!(remainingMs > 0)) return { kind: "closed", text: "closed", remainingMs: 0 };
  const clock = formatClock(Math.ceil(remainingMs / 1000));
  return remainingMs <= WARN_BELOW_MS
    ? { kind: "warn", text: `${clock} closing`, remainingMs }
    : { kind: "normal", text: clock, remainingMs };
}

/** Milliseconds to the next whole second of the wall clock, so a 1 Hz tick lands on the boundary. */
export const msToNextSecond = (nowMs: number): number => 1000 - (((nowMs % 1000) + 1000) % 1000);
