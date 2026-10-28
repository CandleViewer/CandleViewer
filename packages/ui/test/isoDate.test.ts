import { describe, expect, it } from "vitest";
import {
  FIRST_DAY,
  LAST_DAY,
  addDays,
  addMonths,
  addYears,
  clampIso,
  daysInMonth,
  endOfWeek,
  formatIsoDate,
  fromDayNumber,
  isLeapYear,
  isWithin,
  isoFromEpochMs,
  isoWeekday,
  longLabel,
  monthLabel,
  monthWeeks,
  normaliseIso,
  parseIsoDate,
  startOfWeek,
  toDayNumber,
} from "../src/components/internal/isoDate.js";

const DAY_MS = 86_400_000;
/** The oracle: the platform's UTC calendar, used in tests only (the module never touches `Date`). */
const oracle = (days: number): string => new Date(days * DAY_MS).toISOString().slice(0, 10);

describe("isoDate: day numbers", () => {
  it("round-trips every 997th day from 1900 to 2400 against the platform's UTC calendar", () => {
    const from = toDayNumber({ year: 1900, month: 1, day: 1 });
    const to = toDayNumber({ year: 2400, month: 12, day: 31 });
    for (let n = from; n <= to; n += 997) {
      const iso = formatIsoDate(fromDayNumber(n));
      expect(iso).toBe(oracle(n));
      expect(toDayNumber(parseIsoDate(iso) ?? { year: 0, month: 0, day: 0 })).toBe(n);
    }
  });

  it("anchors the epoch and the ISO range ends", () => {
    expect(toDayNumber({ year: 1970, month: 1, day: 1 })).toBe(0);
    expect(formatIsoDate(fromDayNumber(FIRST_DAY))).toBe("0001-01-01");
    expect(formatIsoDate(fromDayNumber(LAST_DAY))).toBe("9999-12-31");
  });

  it("knows the leap-year rule, including the century exceptions", () => {
    expect([1900, 2000, 2023, 2024, 2100].map(isLeapYear)).toEqual([
      false,
      true,
      false,
      true,
      false,
    ]);
    expect(daysInMonth(2024, 2)).toBe(29);
    expect(daysInMonth(2100, 2)).toBe(28);
    expect(daysInMonth(2026, 4)).toBe(30);
    expect(daysInMonth(2026, 12)).toBe(31);
  });
});

describe("isoDate: parsing", () => {
  it.each(["2024-02-29", "2026-10-23", "0001-01-01", "9999-12-31"])("accepts %s", (text) => {
    expect(normaliseIso(text)).toBe(text);
  });

  it.each([
    "2023-02-29",
    "2026-13-01",
    "2026-00-10",
    "2026-04-31",
    "0000-01-01",
    "2026-1-5",
    "26-10-23",
    "2026/10/23",
    " 2026-10-23",
    "2026-10-23T00:00",
    "",
  ])("rejects %j", (text) => {
    expect(parseIsoDate(text)).toBeNull();
  });

  it("treats null and undefined as no date", () => {
    expect(normaliseIso(null)).toBeNull();
    expect(normaliseIso(undefined)).toBeNull();
  });
});

describe("isoDate: arithmetic", () => {
  it("moves by days across month and year edges", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2027-01-01", -1)).toBe("2026-12-31");
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
    expect(addDays("2023-02-28", 1)).toBe("2023-03-01");
  });

  it("clamps the day number to the target month's last day", () => {
    expect(addMonths("2026-01-31", 1)).toBe("2026-02-28");
    expect(addMonths("2024-01-31", 1)).toBe("2024-02-29");
    expect(addMonths("2026-03-31", -1)).toBe("2026-02-28");
    expect(addMonths("2026-12-15", 1)).toBe("2027-01-15");
    expect(addMonths("2026-01-15", -1)).toBe("2025-12-15");
    expect(addYears("2024-02-29", 1)).toBe("2025-02-28");
    expect(addYears("2024-02-29", 4)).toBe("2028-02-29");
  });

  it("stays within 0001-01-01 and 9999-12-31", () => {
    expect(addDays("0001-01-01", -1)).toBe("0001-01-01");
    expect(addDays("9999-12-31", 7)).toBe("9999-12-31");
    expect(addMonths("0001-01-15", -1)).toBe("0001-01-01");
    expect(addYears("9999-06-15", 1)).toBe("9999-12-31");
  });

  it("throws on a value that is not an ISO date", () => {
    expect(() => addDays("nope", 1)).toThrow(RangeError);
    expect(() => addMonths("2026-02-30", 1)).toThrow(RangeError);
  });

  it("starts weeks on Monday", () => {
    expect(isoWeekday("2026-10-26")).toBe(0);
    expect(isoWeekday("2026-11-01")).toBe(6);
    expect(isoWeekday("1970-01-01")).toBe(3);
    expect(isoWeekday("1969-12-29")).toBe(0);
    expect(startOfWeek("2026-10-23")).toBe("2026-10-19");
    expect(endOfWeek("2026-10-23")).toBe("2026-10-25");
    expect(startOfWeek("2026-11-01")).toBe("2026-10-26");
    expect(endOfWeek("2026-12-30")).toBe("2027-01-03");
  });

  it("reads the UTC day of a clock, before and after the epoch", () => {
    expect(isoFromEpochMs(Date.UTC(2026, 9, 23, 23, 59, 59, 999))).toBe("2026-10-23");
    expect(isoFromEpochMs(Date.UTC(2026, 9, 24))).toBe("2026-10-24");
    expect(isoFromEpochMs(-1)).toBe("1969-12-31");
  });

  it("clamps and tests a day against optional bounds", () => {
    expect(clampIso("2026-08-01", "2026-09-01", "2026-10-28")).toBe("2026-09-01");
    expect(clampIso("2026-11-01", "2026-09-01", "2026-10-28")).toBe("2026-10-28");
    expect(clampIso("2026-10-01", null, undefined)).toBe("2026-10-01");
    expect(isWithin("2026-09-01", "2026-09-01", "2026-10-28")).toBe(true);
    expect(isWithin("2026-08-31", "2026-09-01")).toBe(false);
  });
});

describe("isoDate: labels and the month matrix", () => {
  it("names a day and a month in words", () => {
    expect(longLabel("2026-10-23")).toBe("23 October 2026");
    expect(longLabel("bad")).toBe("bad");
    expect(monthLabel(2024, 2)).toBe("February 2024");
  });

  it("lays a month out as 6 Monday-first weeks with blanks outside it", () => {
    const weeks = monthWeeks(2026, 10);
    expect(weeks).toHaveLength(6);
    expect(weeks.every((week) => week.length === 7)).toBe(true);
    // 1 October 2026 is a Thursday.
    expect(weeks[0]).toEqual([
      null,
      null,
      null,
      "2026-10-01",
      "2026-10-02",
      "2026-10-03",
      "2026-10-04",
    ]);
    expect(weeks.flat().filter((day) => day !== null)).toHaveLength(31);
    expect(weeks[5]?.every((day) => day === null)).toBe(true);
  });

  it("fills all six weeks for a 31-day month that starts on a Sunday", () => {
    // 1 March 2026 is a Sunday.
    const weeks = monthWeeks(2026, 3);
    expect(weeks[0]?.[6]).toBe("2026-03-01");
    expect(weeks[5]?.[1]).toBe("2026-03-31");
  });
});
