// E24-S06 (#781) slice 2: the bar's time cell and the interval's words (`format.ts`), pinned with their edges.
import { describe, expect, it } from "vitest";
import {
  barTime,
  intervalLabel,
} from "../../../../../src/features/derivatives/liquidations/bars/format";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const REF = Date.parse("2026-10-21T11:00:00Z");

describe("barTime", () => {
  it("reads the time alone on the reference day and with its date on another", () => {
    expect(barTime(Date.parse("2026-10-21T09:00:00Z"), REF, HOUR)).toBe("09:00");
    expect(barTime(Date.parse("2026-10-20T23:00:00Z"), REF, HOUR)).toBe("20 Oct 23:00");
  });

  it("reads a bar of a day or more as its date and year, never a time", () => {
    expect(barTime(Date.parse("2026-10-21T00:00:00Z"), REF, DAY)).toBe("21 Oct 2026");
    expect(barTime(Date.parse("2026-10-19T00:00:00Z"), REF, 7 * DAY)).toBe("19 Oct 2026");
    expect(barTime(Date.parse("2026-01-05T00:00:00Z"), REF, DAY)).toBe("5 Jan 2026");
  });

  it("treats just under a day as a time bar", () => {
    expect(barTime(Date.parse("2026-10-21T09:00:00Z"), REF, DAY - 1)).toBe("09:00");
  });
});

describe("intervalLabel", () => {
  it("names minutes, hours, a day and a week", () => {
    expect(intervalLabel(15 * 60_000)).toBe("15 min");
    expect(intervalLabel(HOUR)).toBe("1 h");
    expect(intervalLabel(4 * HOUR)).toBe("4 h");
    expect(intervalLabel(DAY)).toBe("1 d");
    expect(intervalLabel(7 * DAY)).toBe("1 w");
  });

  it("keeps the edges: just under an hour is minutes, just under a day is hours, just under a week is a day", () => {
    expect(intervalLabel(HOUR - 60_000)).toBe("59 min");
    expect(intervalLabel(12 * HOUR)).toBe("12 h");
    expect(intervalLabel(7 * DAY - 1)).toBe("1 d");
  });
});
