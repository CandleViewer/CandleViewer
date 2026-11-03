/** E08-D06 §7: the clock-alarm inputs CMP-126 takes (the countdown itself is the component's). */
import { describe, expect, it } from "vitest";
import { alarmSkewMs, CLIENT_SKEW_LIMIT_MS } from "../../../src/features/symbol-info/funding";

const alarm = (
  shellAlarm: boolean,
  clientSkewMs: number | null,
  exchangeOffsetMs: number | null,
): Parameters<typeof alarmSkewMs>[0] => ({ shellAlarm, clientSkewMs, exchangeOffsetMs });

describe("alarmSkewMs", () => {
  it("is off with no skew known", () => {
    expect(alarmSkewMs(alarm(false, null, null))).toEqual({ on: false, skewMs: null });
  });

  it("does not alarm at a client skew of 2 000 ms or less", () => {
    expect(CLIENT_SKEW_LIMIT_MS).toBe(2_000);
    expect(alarmSkewMs(alarm(false, 2_000, 612))).toEqual({ on: false, skewMs: 2_000 });
  });

  it("alarms past 2 000 ms either way and shows the absolute skew", () => {
    expect(alarmSkewMs(alarm(false, -2_500, null))).toEqual({ on: true, skewMs: 2_500 });
  });

  it("alarms on the shell's state alone, showing the exchange offset when it is all there is", () => {
    expect(alarmSkewMs(alarm(true, null, -612))).toEqual({ on: true, skewMs: 612 });
    expect(alarmSkewMs(alarm(true, null, null))).toEqual({ on: true, skewMs: null });
  });

  it("shows the larger of the client skew and the exchange offset", () => {
    expect(alarmSkewMs(alarm(false, 300, -900))).toEqual({ on: false, skewMs: 900 });
  });
});
