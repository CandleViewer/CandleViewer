import { describe, expect, it } from "vitest";
import {
  countdownState,
  msToNextSecond,
  formatClock,
  NO_COUNTDOWN_TITLE,
} from "../../src/chart/countdown";

const MIN = 60_000;
const OPEN = Date.UTC(2026, 10, 1, 12, 0, 0);

describe("Scenario: The countdown warns with a word, not only a colour", () => {
  it("shows 0:08 closing at 8 s on a 1-minute bar", () => {
    const s = countdownState(OPEN, MIN, OPEN + MIN - 8_000, 0);
    expect(s).toMatchObject({ kind: "warn", text: "0:08 closing" });
  });

  it("is normal above 10 s and warns from exactly 10 s", () => {
    expect(countdownState(OPEN, MIN, OPEN + 49_000, 0)).toMatchObject({
      kind: "normal",
      text: "0:11",
    });
    expect(countdownState(OPEN, MIN, OPEN + 50_000, 0)).toMatchObject({
      kind: "warn",
      text: "0:10 closing",
    });
  });

  it("rounds seconds up so an open bar never reads 0:00", () => {
    expect(countdownState(OPEN, MIN, OPEN + MIN - 400, 0).text).toBe("0:01 closing");
  });

  it("corrects the local clock by the server skew", () => {
    // Local clock 5 s behind the server: the server is 8 s from the close.
    const s = countdownState(OPEN, MIN, OPEN + MIN - 13_000, 5_000);
    expect(s.text).toBe("0:08 closing");
    // Local clock 5 s ahead.
    expect(countdownState(OPEN, MIN, OPEN + MIN - 3_000, -5_000).text).toBe("0:08 closing");
  });

  it("reads closed at the close and rolls to the next bar's 0:59", () => {
    expect(countdownState(OPEN, MIN, OPEN + MIN, 0)).toEqual({
      kind: "closed",
      text: "closed",
      remainingMs: 0,
    });
    expect(countdownState(OPEN + MIN, MIN, OPEN + MIN + 500, 0).text).toBe("1:00");
    expect(countdownState(OPEN + MIN, MIN, OPEN + MIN + 1_000, 0).text).toBe("0:59");
  });

  it("is n/a with the title for non-time bars", () => {
    for (const interval of [null, 0, -1, Number.NaN]) {
      expect(countdownState(OPEN, interval, OPEN, 0)).toEqual({
        kind: "na",
        text: "—",
        title: NO_COUNTDOWN_TITLE,
      });
    }
    expect(NO_COUNTDOWN_TITLE).toBe("No countdown for tick bars");
  });

  it("formats m:ss and aligns ticks to the second boundary", () => {
    expect(formatClock(61)).toBe("1:01");
    expect(msToNextSecond(10_250)).toBe(750);
    expect(msToNextSecond(10_000)).toBe(1000);
  });
});
