/**
 * CMP-226 BarCountdown (E11-S07; E11-D02 §7.4 D11, E11-D06 §6.1): `m:ss` to the close of a time
 * bar. The warn state (final 10 s) adds the word "closing" and a weight, never only a colour; the
 * flip is instant. `aria-live="off"`: it ticks at 1 Hz, aligned to the skew-corrected second
 * boundaries, and is never announced. Non-time bars read "—" with a title. `skewMs` is
 * `connection.clockSkewMs` (the panel wires it); `nowMs` is injectable for tests and stories.
 */
import { useEffect, useState, type JSX } from "react";
import { Icon } from "@candleviewer/ui";
import { countdownState, msToNextSecond } from "./countdown";
import "./bar-countdown.css";

export interface BarCountdownProps {
  /** The open time of the live bar (epoch ms); ignored for non-time bars. */
  readonly barOpenMs: number;
  /** The bar length for a time interval, or null for tick, volume, range or renko bars. */
  readonly intervalMs: number | null;
  /** Server minus local clock (ms); 0 when unknown. */
  readonly skewMs?: number;
  readonly now?: () => number;
}

export function BarCountdown({
  barOpenMs,
  intervalMs,
  skewMs = 0,
  now = Date.now,
}: BarCountdownProps): JSX.Element {
  const [nowMs, setNowMs] = useState(now);
  useEffect(() => {
    if (intervalMs === null) return undefined;
    let timer: ReturnType<typeof setTimeout>;
    const tick = (): void => {
      const t = now();
      setNowMs(t);
      timer = setTimeout(tick, msToNextSecond(t + skewMs)); // the digits read server time
    };
    timer = setTimeout(tick, msToNextSecond(now() + skewMs));
    return () => clearTimeout(timer);
  }, [intervalMs, now, skewMs]);

  const state = countdownState(barOpenMs, intervalMs, nowMs, skewMs);
  return (
    <span
      className="cv-bar-countdown"
      data-state={state.kind}
      aria-live="off"
      title={state.kind === "na" ? state.title : undefined}
    >
      {state.kind === "warn" ? <Icon name="pending" size="sm" decorative /> : null}
      {state.kind === "normal" || state.kind === "warn" ? (
        <span className="cv-bar-countdown__label">bar close </span>
      ) : null}
      <span className="cv-bar-countdown__text">{state.text}</span>
    </span>
  );
}
