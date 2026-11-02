import { useEffect, useRef, useState, type JSX } from "react";
import { Icon } from "../icons/Icon.js";
import { cx } from "./internal/cx.js";
import { MonoText } from "./Typography.js";

/** The §7 states of E08-D06, one at a time. */
export type FundingCountdownState =
  "ahead" | "settling" | "elapsed" | "unknown" | "not-trading" | "clock-alarm";

export type FundingRateSign = "positive" | "negative" | "zero";

export interface FundingCountdownProps {
  /** The symbol, spoken in the 5 min and 1 min announcements and in the not-trading sentence. */
  symbol: string;
  /**
   * The ticker's `next_funding_time_ms` (epoch ms), rendered and never recomputed from an interval
   * (E24-D01 F11). Absent: "Next funding time not available" (D06 §7). A new value restarts the count.
   */
  nextFundingTimeMs?: number | undefined;
  /**
   * The host's formatted rate (A-5, a decimal string, F1), shown before the count with its sign in the
   * text, so colour is never the only signal. SCR-103 passes none: its rate is its own row (§4.2).
   */
  rate?: string | undefined;
  /** The symbol is not trading: "No funding — BTCUSDT is not trading." and no countdown. */
  notTrading?: boolean | undefined;
  /** SCR-152's `clock-skew` is on (or the client skew exceeds 2 000 ms): the absolute time replaces the count. */
  clockAlarm?: boolean | undefined;
  /** The measured skew in ms; absent with `clockAlarm`, the offset is unknown and the time stands alone. */
  clockSkewMs?: number | undefined;
  /** The clock, epoch ms (`Date.now` by default); injectable for tests and frozen stories. */
  now?: () => number;
  className?: string;
}

const MINUTE = 60;
const HOUR = 3600;
/** E24-D01's thresholds: one polite announcement at each, never CMP-035's 60, 10 and 0 s (A-5). */
const ANNOUNCE_AT: readonly number[] = [5 * MINUTE, MINUTE];

const pad = (n: number): string => String(n).padStart(2, "0");
const plural = (n: number, unit: string): string => `${n} ${unit}${n === 1 ? "" : "s"}`;

/**
 * Whole seconds left, never negative. The floor is deliberate (D06 §7 draws 5,053,771 ms as 01:24:13) and
 * differs from CMP-035's ceil.
 */
const secondsTo = (target: number, at: number): number =>
  Math.max(0, Math.floor((target - at) / 1000));

/** "08:00" or, with `seconds`, "08:00:00": the settlement in UTC. */
const utcClock = (ms: number, seconds = false): string =>
  new Date(ms).toISOString().slice(11, seconds ? 19 : 16);

/** E24-D01's fixed-width form: "01:24:13". */
export function formatFundingCount(total: number): string {
  return `${pad(Math.floor(total / HOUR))}:${pad(Math.floor((total % HOUR) / MINUTE))}:${pad(total % MINUTE)}`;
}

/** The spoken twin of the count: "1 hour 24 minutes" above an hour, then minutes and seconds. */
export function spokenFundingCount(total: number): string {
  const h = Math.floor(total / HOUR);
  const m = Math.floor((total % HOUR) / MINUTE);
  const s = total % MINUTE;
  if (h > 0) return m > 0 ? `${plural(h, "hour")} ${plural(m, "minute")}` : plural(h, "hour");
  if (m > 0) return s > 0 ? `${plural(m, "minute")} ${plural(s, "second")}` : plural(m, "minute");
  return plural(s, "second");
}

/**
 * "1 h 24 min" / "12 min": the clock-alarm form's rough distance (D06 draws "about 1 h 24 min").
 * PROPOSED (not verbatim): the `Math.max(1, …)` rounding, so the last minute reads "1 min", never "0 min".
 */
const approxCount = (total: number): string => {
  const minutes = Math.max(1, Math.round(total / MINUTE));
  const h = Math.floor(minutes / 60);
  return h > 0 ? `${h} h ${minutes % 60} min` : `${minutes} min`;
};

/** The sign of a host-formatted rate: its leading sign, else zero when every digit is zero. */
export function fundingRateSign(rate: string): FundingRateSign {
  const text = rate.trim();
  if (!/[1-9]/.test(text)) return "zero";
  return /^[-−]/.test(text) ? "negative" : "positive";
}

/**
 * PROPOSED (not verbatim): the "+" added to an unsigned positive rate, so the sign never rests on colour
 * (D06 §7, 05 §4).
 */
const signed = (rate: string, sign: FundingRateSign): string =>
  sign === "positive" && !rate.trim().startsWith("+") ? `+${rate.trim()}` : rate.trim();

/** The state for a deadline and a reading of the clock (§7), without the host's `notTrading` and `clockAlarm`. */
export function fundingCountdownState(
  nextFundingTimeMs: number | undefined,
  at: number,
): "ahead" | "settling" | "elapsed" | "unknown" {
  if (nextFundingTimeMs === undefined || !Number.isFinite(nextFundingTimeMs)) return "unknown";
  if (nextFundingTimeMs <= at) return "elapsed";
  return secondsTo(nextFundingTimeMs, at) < 5 * MINUTE ? "settling" : "ahead";
}

/** D06 §7, verbatim. */
const ELAPSED = "Settlement time passed — waiting for an update";

/**
 * CMP-126: the time to the next funding settlement (E08-D06 §7, A-5) and, optionally, the rate. The digits tick
 * once a second in `aria-live="off"` text (`aria-hidden`, with a visually hidden twin in words); a separate polite
 * status speaks once at 5 minutes and once at 1 minute, never per tick. Past the settlement it says so and waits
 * for the ticker's next time; it never restarts from an interval. It keeps counting while the live band is stale.
 */
export function FundingCountdown({
  symbol,
  nextFundingTimeMs,
  rate,
  notTrading = false,
  clockAlarm = false,
  clockSkewMs,
  now = Date.now,
  className,
}: FundingCountdownProps): JSX.Element {
  const [at, setAt] = useState(() => now());
  const [message, setMessage] = useState("");
  const latest = useRef({ now, symbol, clockSkewMs, clockAlarm });
  useEffect(() => {
    latest.current = { now, symbol, clockSkewMs, clockAlarm };
  });
  const running = !notTrading && nextFundingTimeMs !== undefined;

  useEffect(() => {
    // A new deadline forgets what the old one said (a stale "settles in 1 minute" or the elapsed line).
    setMessage("");
    if (!running || nextFundingTimeMs === undefined) return undefined;
    const target = nextFundingTimeMs;
    const start = secondsTo(target, latest.current.now());
    // Thresholds already passed at mount (or at a new deadline) were never crossed here: none speaks.
    const spoken = new Set(ANNOUNCE_AT.filter((t) => t >= start));
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = (): void => {
      const read = latest.current.now();
      const left = secondsTo(target, read);
      setAt(read);
      const crossed = ANNOUNCE_AT.filter((t) => left <= t && !spoken.has(t));
      if (crossed.length > 0 && target > read) {
        crossed.forEach((t) => spoken.add(t));
        // Several at once (a tab back from the background): the latest, the smallest, speaks alone.
        // While the clock alarm is on the count is not shown, so the thresholds are marked but never spoken.
        const t = Math.min(...crossed);
        if (!latest.current.clockAlarm)
          setMessage(
            `${latest.current.symbol} funding settles in ${plural(t / MINUTE, "minute")}.`,
          );
      }
      if (target <= read) {
        setMessage(ELAPSED);
        return;
      }
      // The floor changes 1 ms past a whole second of the deadline: the next tick lands there.
      timer = setTimeout(tick, ((target - read) % 1000) + 1);
    };
    tick();
    return () => clearTimeout(timer);
  }, [running, nextFundingTimeMs]);

  // The clock alarm is announced once on entry, with the skew when it is known.
  useEffect(() => {
    const skew = latest.current.clockSkewMs;
    if (clockAlarm && skew !== undefined) {
      setMessage(`Clock skew ${Math.round(Math.abs(skew))} ms — the countdown may be off`);
    }
  }, [clockAlarm]);

  const state: FundingCountdownState = notTrading
    ? "not-trading"
    : nextFundingTimeMs === undefined
      ? "unknown"
      : fundingCountdownState(nextFundingTimeMs, at) === "elapsed"
        ? "elapsed" // the passed deadline wins over the clock alarm
        : clockAlarm
          ? "clock-alarm"
          : fundingCountdownState(nextFundingTimeMs, at);
  const left = nextFundingTimeMs === undefined ? 0 : secondsTo(nextFundingTimeMs, at);
  const sign = rate === undefined ? undefined : fundingRateSign(rate);
  const target = nextFundingTimeMs ?? 0;

  let body: JSX.Element | null = null;
  if (state === "ahead" || state === "settling") {
    const lead = state === "settling" ? "settles in" : "next in";
    body = (
      <span className="cv-funding__count" aria-live="off">
        {state === "settling" ? (
          <span className="cv-funding__warn">
            <Icon name="warning" size="sm" />
          </span>
        ) : null}
        <MonoText size="base" className="cv-funding__digits" aria-hidden="true">
          <span className="cv-funding__part">{`${lead} ${formatFundingCount(left)}`}</span>
          {" · "}
          <span className="cv-funding__part">{`${utcClock(target)} UTC`}</span>
        </MonoText>
        <span className="cv-visually-hidden">
          {`Next funding in ${spokenFundingCount(left)}, at ${utcClock(target)} UTC`}
        </span>
      </span>
    );
  } else if (state === "clock-alarm") {
    body = (
      <span className="cv-funding__absolute">
        <span>{`at ${utcClock(target, true)} UTC (in about ${approxCount(left)})`}</span>
        {clockSkewMs === undefined ? null : (
          <span className="cv-funding__note">
            {`Clock skew ${Math.round(Math.abs(clockSkewMs))} ms — the countdown may be off`}
          </span>
        )}
      </span>
    );
  } else if (state === "elapsed") {
    body = <span className="cv-funding__note">{ELAPSED}</span>;
  } else if (state === "unknown") {
    body = <span className="cv-funding__note">Next funding time not available</span>;
  } else {
    body = <span className="cv-funding__note">{`No funding — ${symbol} is not trading.`}</span>;
  }

  return (
    <span
      className={cx("cv-funding", className)}
      data-cmp="CMP-126"
      data-state={state}
      data-sign={sign}
    >
      {rate === undefined || sign === undefined || notTrading ? null : (
        <MonoText size="base" className="cv-funding__rate" data-sign={sign}>
          {signed(rate, sign)}
        </MonoText>
      )}
      {body}
      <span className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {message}
      </span>
    </span>
  );
}
