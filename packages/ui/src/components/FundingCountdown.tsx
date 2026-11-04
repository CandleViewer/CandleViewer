import { useEffect, useRef, useState, type JSX, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { cx } from "./internal/cx.js";
import { systemSecondTick, type SecondTick } from "./secondTick.js";
import { MonoText } from "./Typography.js";

/** The §7 states of E08-D06, one at a time. */
export type FundingCountdownState =
  "ahead" | "settling" | "elapsed" | "unknown" | "not-trading" | "clock-alarm";

export type FundingRateSign = "positive" | "negative" | "zero";

/**
 * One server-computed charge line (E24-S03 #778, BQ 4; D02 §5.2): `Position.funding_estimate`, formatted by the
 * host and never computed here. One line per account; never summed across environments (C-2.11).
 */
export interface FundingCharge {
  /** The account's label, e.g. "Demo 1". */
  readonly accountLabel: string;
  readonly env: "DEMO" | "LIVE";
  readonly direction: "pay" | "receive";
  /** The amount as the host formatted it, in USDT, unsigned: "12.40". */
  readonly amountUsdt: string;
  /** The CMP-239 marker text when the estimate is stale ("Stale 7s · last 15:55:41"); absent when fresh. */
  readonly staleNote?: string | undefined;
}

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
  /**
   * The shared 1 Hz tick (BQ 2): one timer for every countdown on it, and its clock is the countdown's clock.
   * The app passes its exchange-synced tick; absent, the local-clock `systemSecondTick`.
   */
  tick?: SecondTick | undefined;
  /** Reads the clock, epoch ms; the tick's clock by default. Injectable for frozen stories. */
  now?: (() => number) | undefined;
  /**
   * The charge lines shown under 5 minutes (D02 §5.2), server-computed. Absent or empty: no charge line, never
   * a zero (BQ 4).
   */
  charges?: readonly FundingCharge[] | undefined;
  /**
   * Whether this instance speaks the 5 min and 1 min lines (default true). Where one countdown is shown twice
   * (the symbol header and the funding sub-pane), only one speaks: the other passes `false` and renders no
   * status region, so AN-1 / AN-2 are said once (E24-D03 §13).
   */
  announce?: boolean | undefined;
  /**
   * E24-S04 (#779), additive: the host's words after the rate ("/ 8 h · 10.95 % p.a. · predicted (estimated)",
   * or "Funding n/a" with no `rate`), so a predicted rate is never drawn as settled. Rendered as given.
   */
  rateExtra?: ReactNode;
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

/** D02 §5.2 "you pay ≈ 12.40 USDT on Demo 1 · DEMO": the written clause after the count. */
const chargeText = (c: FundingCharge): string =>
  `— you ${c.direction} ≈ ${c.amountUsdt} USDT on ${c.accountLabel} · ${c.env}`;
/** D03 AN-1 / AN-2's spoken clause: "about" for "≈", a comma for "·". */
const chargeSpoken = (c: FundingCharge): string =>
  `you ${c.direction} about ${c.amountUsdt} USDT on ${c.accountLabel}, ${c.env}`;

/**
 * E08-D06's sentence, with D03 AN-1 / AN-2's charge clauses appended where a position exists (PROPOSED: the two
 * specs joined; AN-3 with no position is E08-D06's sentence unchanged).
 */
const announcement = (
  symbol: string,
  seconds: number,
  charges: readonly FundingCharge[] | undefined,
): string => {
  const lead = `${symbol} funding settles in ${plural(seconds / MINUTE, "minute")}`;
  const clauses = (charges ?? []).map(chargeSpoken);
  return clauses.length === 0 ? `${lead}.` : `${lead} — ${clauses.join("; ")}.`;
};

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
  tick = systemSecondTick,
  now,
  charges,
  announce = true,
  rateExtra,
  className,
}: FundingCountdownProps): JSX.Element {
  const read = now ?? tick.now;
  const [at, setAt] = useState(() => read());
  const [message, setMessage] = useState("");
  const latest = useRef({ read, symbol, clockSkewMs, clockAlarm, charges });
  useEffect(() => {
    latest.current = { read, symbol, clockSkewMs, clockAlarm, charges };
  });
  const running = !notTrading && nextFundingTimeMs !== undefined;

  useEffect(() => {
    // A new deadline forgets what the old one said (a stale "settles in 1 minute" or the elapsed line).
    setMessage("");
    if (!running || nextFundingTimeMs === undefined) return undefined;
    const target = nextFundingTimeMs;
    const start = secondsTo(target, latest.current.read());
    // Thresholds already passed at mount (or at a new deadline) were never crossed here: none speaks.
    const spoken = new Set(ANNOUNCE_AT.filter((t) => t >= start));
    let unsubscribe: (() => void) | undefined;
    let done = false;
    const step = (): void => {
      if (done) return;
      const reading = latest.current.read();
      const left = secondsTo(target, reading);
      setAt(reading);
      const crossed = ANNOUNCE_AT.filter((t) => left <= t && !spoken.has(t));
      if (crossed.length > 0 && target > reading) {
        crossed.forEach((t) => spoken.add(t));
        // Several at once (a tab back from the background): the latest, the smallest, speaks alone.
        // While the clock alarm is on the count is not shown, so the thresholds are marked but never spoken.
        const t = Math.min(...crossed);
        if (!latest.current.clockAlarm)
          setMessage(announcement(latest.current.symbol, t, latest.current.charges));
      }
      if (target <= reading) {
        setMessage(ELAPSED);
        done = true;
        unsubscribe?.();
      }
    };
    step();
    // One shared tick for every countdown (BQ 2); none per instance.
    if (!done) unsubscribe = tick.subscribe(step);
    return () => {
      done = true;
      unsubscribe?.();
    };
  }, [running, nextFundingTimeMs, tick]);

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
            <Icon name="pending" size="sm" />
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
        {state === "settling"
          ? (charges ?? []).map((c) => (
              <span
                key={`${c.accountLabel}:${c.env}`}
                className="cv-funding__charge"
                data-stale={c.staleNote === undefined ? undefined : "true"}
              >
                <span aria-hidden="true">{chargeText(c)}</span>
                <span className="cv-visually-hidden">{chargeSpoken(c)}</span>
                {c.staleNote === undefined ? null : (
                  <span className="cv-funding__note">{c.staleNote}</span>
                )}
              </span>
            ))
          : null}
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
      {notTrading ? null : rateExtra}
      {body}
      {announce ? (
        <span className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
          {message}
        </span>
      ) : null}
    </span>
  );
}
