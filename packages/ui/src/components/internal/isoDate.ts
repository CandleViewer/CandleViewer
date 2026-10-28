/**
 * In-house UTC calendar math on ISO `YYYY-MM-DD` strings (CMP-047; #266 plan §3 item 3): no date library and no
 * `Date` in or out, so no local-zone slip. Day numbers count days from 1970-01-01 in the proleptic Gregorian
 * calendar (H. Hinnant's `days_from_civil` / `civil_from_days`); every result stays within 0001-01-01 to
 * 9999-12-31, the years a four-digit ISO string can hold.
 */

/** A calendar date; `month` is 1-12. */
export interface CivilDate {
  readonly year: number;
  readonly month: number;
  readonly day: number;
}

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

/** ISO 8601 weeks: Monday first, in every locale (G11). */
export const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

const MS_PER_DAY = 86_400_000;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export const isLeapYear = (year: number): boolean =>
  (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;

export const daysInMonth = (year: number, month: number): number =>
  month === 2 ? (isLeapYear(year) ? 29 : 28) : [4, 6, 9, 11].includes(month) ? 30 : 31;

/** Days from 1970-01-01 to `date` (negative before it). */
export function toDayNumber({ year, month, day }: CivilDate): number {
  const y = month <= 2 ? year - 1 : year;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (month > 2 ? month - 3 : month + 9) + 2) / 5) + day - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146_097 + doe - 719_468;
}

/** The date `days` after 1970-01-01. */
export function fromDayNumber(days: number): CivilDate {
  const z = days + 719_468;
  const era = Math.floor(z / 146_097);
  const doe = z - era * 146_097;
  const yoe = Math.floor(
    (doe - Math.floor(doe / 1460) + Math.floor(doe / 36_524) - Math.floor(doe / 146_096)) / 365,
  );
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const day = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const month = mp < 10 ? mp + 3 : mp - 9;
  return { year: yoe + era * 400 + (month <= 2 ? 1 : 0), month, day };
}

/** The first and last day an ISO string can name. */
export const FIRST_DAY = toDayNumber({ year: 1, month: 1, day: 1 });
export const LAST_DAY = toDayNumber({ year: 9999, month: 12, day: 31 });

const pad = (n: number, width: number): string => String(n).padStart(width, "0");

export const formatIsoDate = ({ year, month, day }: CivilDate): string =>
  `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`;

/** Strict `YYYY-MM-DD`: a real day (29 February in leap years only), year 0001 or later; else null. */
export function parseIsoDate(text: string): CivilDate | null {
  const match = ISO_DATE.exec(text);
  if (match === null) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  return { year, month, day };
}

/** The canonical form of a valid ISO date, or null. */
export const normaliseIso = (text: string | null | undefined): string | null => {
  const date = text == null ? null : parseIsoDate(text);
  return date === null ? null : formatIsoDate(date);
};

const fromClampedDay = (days: number): string =>
  formatIsoDate(fromDayNumber(Math.min(LAST_DAY, Math.max(FIRST_DAY, days))));

const dayOf = (iso: string): number => {
  const date = parseIsoDate(iso);
  if (date === null) throw new RangeError(`not an ISO date: ${iso}`);
  return toDayNumber(date);
};

/** `iso` moved by `days`, kept within the ISO range. */
export const addDays = (iso: string, days: number): string => fromClampedDay(dayOf(iso) + days);

/** `iso` moved by whole months; the day number clamps to the target month's last day (31 Jan + 1 = 28/29 Feb). */
export function addMonths(iso: string, months: number): string {
  const date = parseIsoDate(iso);
  if (date === null) throw new RangeError(`not an ISO date: ${iso}`);
  const index = date.year * 12 + (date.month - 1) + months;
  const year = Math.floor(index / 12);
  if (year < 1) return fromClampedDay(FIRST_DAY);
  if (year > 9999) return fromClampedDay(LAST_DAY);
  const month = index - year * 12 + 1;
  return formatIsoDate({ year, month, day: Math.min(date.day, daysInMonth(year, month)) });
}

export const addYears = (iso: string, years: number): string => addMonths(iso, years * 12);

/** 0 = Monday ... 6 = Sunday (1970-01-01 was a Thursday). */
export const isoWeekday = (iso: string): number => (((dayOf(iso) + 3) % 7) + 7) % 7;

export const startOfWeek = (iso: string): string => addDays(iso, -isoWeekday(iso));
export const endOfWeek = (iso: string): string => addDays(iso, 6 - isoWeekday(iso));

/** The UTC calendar day of an epoch time in milliseconds (an injected clock's reading). */
export const isoFromEpochMs = (ms: number): string => fromClampedDay(Math.floor(ms / MS_PER_DAY));

/** `iso` held within `[min, max]` (either bound optional); ISO strings of one width compare as text. */
export function clampIso(iso: string, min?: string | null, max?: string | null): string {
  if (min != null && iso < min) return min;
  if (max != null && iso > max) return max;
  return iso;
}

export const isWithin = (iso: string, min?: string | null, max?: string | null): boolean =>
  clampIso(iso, min, max) === iso;

/** "October 2026". */
export const monthLabel = (year: number, month: number): string =>
  `${MONTH_NAMES[month - 1] ?? ""} ${year}`;

/** "23 October 2026". */
export function longLabel(iso: string): string {
  const date = parseIsoDate(iso);
  if (date === null) return iso;
  return `${date.day} ${monthLabel(date.year, date.month)}`;
}

/** The month's weeks, Monday first: 6 rows of 7 cells, each an ISO date or null outside the month. */
export function monthWeeks(
  year: number,
  month: number,
): ReadonlyArray<ReadonlyArray<string | null>> {
  const first = formatIsoDate({ year, month, day: 1 });
  const lead = isoWeekday(first);
  const length = daysInMonth(year, month);
  return Array.from({ length: 6 }, (_, week) =>
    Array.from({ length: 7 }, (_, weekday) => {
      const day = week * 7 + weekday - lead + 1;
      return day < 1 || day > length ? null : formatIsoDate({ year, month, day });
    }),
  );
}
