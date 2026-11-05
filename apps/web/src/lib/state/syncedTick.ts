// E24-S03 (#778, BQ 2): the app's one 1 Hz tick on the exchange-synced clock, `Date.now` plus the WS session's
// measured skew (E17's clock sync), read at each tick. Every countdown subscribes to it, so none can drift.
import { useSyncExternalStore } from "react";
import { createSecondTick, type SecondTick } from "@candleviewer/ui";
import { getActiveClient } from "../ws/client/activeClient";

/** The measured skew in ms, or `undefined` before the first `diag`. */
export const syncedClockSkew = (): number | undefined => {
  const skew = getActiveClient()?.diagnostics()?.clockSkewMs;
  return typeof skew === "number" && Number.isFinite(skew) ? skew : undefined;
};

/** CMP-126 / E08-D06 D-7: past this, or with no measurement, the countdown shows the absolute time. */
export const CLOCK_ALARM_MS = 2_000;

export const clockAlarmFor = (skewMs: number | undefined): boolean =>
  skewMs === undefined || Math.abs(skewMs) > CLOCK_ALARM_MS;

export const syncedNow = (): number => Date.now() + (syncedClockSkew() ?? 0);

export const syncedTick: SecondTick = createSecondTick({ now: syncedNow });

/** The measured skew as state, re-read each tick (a render only on change), so the alarm follows it. */
export const useSyncedClockSkew = (tick: SecondTick): number | undefined =>
  useSyncExternalStore(tick.subscribe, syncedClockSkew, syncedClockSkew);
