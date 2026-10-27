import { useEffect, useRef, useState, type JSX } from "react";
import { cx } from "./internal/cx.js";
import { MonoText, type NumSize } from "./Typography.js";

export type CountdownFormat = "mm:ss" | "hh:mm:ss" | "words" | "approx";
export type CountdownPhase = "running" | "under-threshold" | "expired";

/** J7's default thresholds, in seconds. */
const DEFAULT_THRESHOLDS: readonly number[] = [60, 10, 0];

export interface CountdownProps {
  /** The server's deadline, epoch ms, rendered and never recomputed from a local duration (conventions 41). */
  expiresAt: number;
  /** `mm:ss` "0:20", `hh:mm:ss` "07:58:12", `words` "9 h 58 m", `approx` "~4 s" (J6). */
  format?: CountdownFormat;
  /** Fires once when the deadline passes (also on mount when it already has); focus never moves. */
  onExpire?: () => void;
  /**
   * The seconds at which one polite announcement speaks (J7), default `[60, 10, 0]`. Each speaks once; a
   * crossing of several at once speaks the latest only. `[]` announces nothing: a countdown in a grid
   * column (SCR-100 "Funding in").
   */
  thresholds?: readonly number[];
  /** The host's sentence for a threshold, e.g. "10 seconds until this confirmation cancels". */
  announce?: (seconds: number) => string;
  /** The digits' `type.num.*` step: `sm` by default, or the host's size. */
  size?: NumSize;
  /** The clock, epoch ms (`Date.now` by default); injectable for tests and frozen stories. */
  now?: () => number;
  className?: string;
}

/** Whole seconds left, rounded up, never negative: "0:01" until the deadline itself. */
export function secondsLeft(expiresAt: number, now: number): number {
  return Math.max(0, Math.ceil((expiresAt - now) / 1000));
}

const pad = (n: number): string => String(n).padStart(2, "0");
const plural = (n: number, unit: string): string => `${n} ${unit}${n === 1 ? "" : "s"}`;

const split = (total: number): { h: number; m: number; s: number } => ({
  h: Math.floor(total / 3600),
  m: Math.floor((total % 3600) / 60),
  s: total % 60,
});

/** The visible digits for a format. */
export function formatCountdown(total: number, format: CountdownFormat): string {
  const { h, m, s } = split(total);
  switch (format) {
    case "hh:mm:ss":
      return `${pad(h)}:${pad(m)}:${pad(s)}`;
    case "words":
      if (h > 0) return `${h} h ${m} m`;
      return m > 0 ? `${m} m ${s} s` : `${s} s`;
    case "approx":
      if (total < 60) return `~${total} s`;
      return total < 3600 ? `~${Math.round(total / 60)} m` : `~${Math.round(total / 3600)} h`;
    default:
      return `${Math.floor(total / 60)}:${pad(s)}`;
  }
}

/** The visually hidden twin, in words at the format's granularity: "20 seconds", "about 4 seconds". */
export function spokenCountdown(total: number, format: CountdownFormat): string {
  if (format === "approx") {
    if (total < 60) return `about ${plural(total, "second")}`;
    return total < 3600
      ? `about ${plural(Math.round(total / 60), "minute")}`
      : `about ${plural(Math.round(total / 3600), "hour")}`;
  }
  const { h, m, s } = split(total);
  const parts: string[] = [];
  if (h > 0) parts.push(plural(h, "hour"));
  if (m > 0) parts.push(plural(m, "minute"));
  // `words` drops the seconds once hours show, as its digits do.
  if ((s > 0 || parts.length === 0) && !(format === "words" && h > 0))
    parts.push(plural(s, "second"));
  return parts.join(" ");
}

/** The default threshold sentence when the host passes no `announce` key. */
const defaultAnnounce = (seconds: number): string =>
  seconds === 0 ? "Time is up" : `${spokenCountdown(seconds, "mm:ss")} left`;

/**
 * The phase: "under-threshold" at or below the smallest positive threshold; with none (`[]` or `[0]`)
 * the count stays "running" until it expires.
 */
export function countdownPhase(left: number, thresholds: readonly number[]): CountdownPhase {
  if (left === 0) return "expired";
  const positive = thresholds.filter((t) => t > 0);
  return positive.length > 0 && left <= Math.min(...positive) ? "under-threshold" : "running";
}

/** Everything a count renders: equal keys render identically, so the tick skips the re-render. */
const countdownKey = (
  left: number,
  format: CountdownFormat,
  thresholds: readonly number[],
): string =>
  `${formatCountdown(left, format)}|${spokenCountdown(left, format)}|${countdownPhase(left, thresholds)}`;

/**
 * CMP-035: a deadline's count. The digits tick once a second, tabular, `aria-hidden`, with a visually
 * hidden twin in words, and the count is `aria-live="off"`, so nothing speaks per tick. A separate polite
 * status, pre-rendered empty, speaks each threshold once. Under the threshold nothing changes colour:
 * the number carries it (§6 J1 (b), until J1 (c)'s clock glyph is approved). Never moves focus.
 */
export function Countdown({
  expiresAt,
  format = "mm:ss",
  onExpire,
  thresholds = DEFAULT_THRESHOLDS,
  announce,
  size = "sm",
  now = Date.now,
  className,
}: CountdownProps): JSX.Element {
  // The count belongs to the deadline it was read for: a new `expiresAt` derives a fresh count in this
  // render, so the old one never flashes before the timer's first tick.
  const [count, setCount] = useState(() => ({
    for: expiresAt,
    left: secondsLeft(expiresAt, now()),
  }));
  const left = count.for === expiresAt ? count.left : secondsLeft(expiresAt, now());
  const [message, setMessage] = useState("");
  // The latest props, read by the timer without restarting it on every render.
  const latest = useRef({ now, onExpire, thresholds, announce, format });
  useEffect(() => {
    latest.current = { now, onExpire, thresholds, announce, format };
  });
  // The deadline whose expiry has fired: once per deadline, StrictMode's re-run effects included.
  const firedFor = useRef<number | null>(null);

  useEffect(() => {
    // Thresholds already passed at mount (or at a new deadline) were never crossed here: none speaks.
    const start = secondsLeft(expiresAt, latest.current.now());
    const spoken = new Set(latest.current.thresholds.filter((t) => t >= start));
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = (): void => {
      const { now: read, onExpire: expire, thresholds: marks, announce: say } = latest.current;
      const at = read();
      const ms = expiresAt - at;
      const s = secondsLeft(expiresAt, at);
      // Re-render only when what shows (or is read) changes: `words` and `approx` change less than 1 Hz.
      setCount((prev) =>
        prev.for === expiresAt &&
        countdownKey(prev.left, latest.current.format, marks) ===
          countdownKey(s, latest.current.format, marks)
          ? prev
          : { for: expiresAt, left: s },
      );
      const crossed = marks.filter((t) => s <= t && !spoken.has(t));
      if (crossed.length > 0) {
        crossed.forEach((t) => spoken.add(t));
        // Several at once (a tab back from the background): the latest, the smallest, speaks alone.
        const t = Math.min(...crossed);
        setMessage((say ?? defaultAnnounce)(t));
      }
      if (s === 0) {
        if (firedFor.current !== expiresAt) {
          firedFor.current = expiresAt;
          expire?.();
        }
        return;
      }
      // The next whole-second boundary of the deadline.
      timer = setTimeout(tick, ms % 1000 || 1000);
    };
    tick();
    return () => clearTimeout(timer);
  }, [expiresAt]);

  const phase = countdownPhase(left, thresholds);
  return (
    <span
      className={cx("cv-countdown", className)}
      data-cmp="CMP-035"
      data-format={format}
      data-phase={phase}
    >
      <span className="cv-countdown__count" aria-live="off">
        <MonoText size={size} className="cv-countdown__digits" aria-hidden="true">
          {formatCountdown(left, format)}
        </MonoText>
        <span className="cv-visually-hidden">{spokenCountdown(left, format)}</span>
      </span>
      {thresholds.length === 0 ? null : (
        <span className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
          {message}
        </span>
      )}
    </span>
  );
}
