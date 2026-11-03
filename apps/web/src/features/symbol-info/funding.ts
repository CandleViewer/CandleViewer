/**
 * The clock-alarm inputs for CMP-126 `FundingCountdown` (`@candleviewer/ui`, E08-D06 §7). The countdown, its
 * spoken name and its announcements live in the component; this slice only derives the `clockAlarm` and
 * `clockSkewMs` props from SCR-152's `clock-skew` state and the client skew (`23` §4.2).
 */

/** `23` §4.2: the client-to-server skew warns above this. */
export const CLIENT_SKEW_LIMIT_MS = 2_000;

export interface ClockAlarm {
  /** SCR-152's `clock-skew` state is on. */
  readonly shellAlarm: boolean;
  /** The client-to-server skew (`welcome.clock_skew_ms`), `null` when unknown. */
  readonly clientSkewMs: number | null;
  /** The backend-to-Bybit offset (US-MKT-009), `null` when unknown. */
  readonly exchangeOffsetMs: number | null;
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
