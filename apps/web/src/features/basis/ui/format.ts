// E24-S08 (#783) slice 1: the basis readout's number formats. Formatting only: the decimals are strings
// and are never combined here (`decimal.ts` owns the one exact subtraction). D03 §2 "basis": the tick's
// decimals, then the percentage in parentheses at three decimals; the sign is text (U+2212).
const MINUS = "−";

const groupInt = (digits: string): string => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** "82751.20" → "82,751.20"; the sign as text (U+2212). */
export function groupedDecimal(value: string): string {
  const negative = value.startsWith("-");
  const [int = "", frac] = (negative ? value.slice(1) : value).split(".");
  const body = frac === undefined ? groupInt(int) : `${groupInt(int)}.${frac}`;
  return negative ? `${MINUS}${body}` : body;
}

const isZero = (value: string): boolean => /^-?0*(\.0*)?$/.test(value);

/** A signed value: "+12.5" / "−3.1"; zero is unsigned. */
export function signedDecimal(value: string): string {
  if (value.startsWith("-")) return groupedDecimal(value);
  return isZero(value) ? groupedDecimal(value) : `+${groupedDecimal(value)}`;
}

/** "−31.17 (−0.038 %)": the basis's decimals, then the percentage. */
export const basisText = (basis: string, pct: string): string =>
  `${signedDecimal(basis)} (${signedDecimal(pct)} %)`;

const spoken = (text: string): string => text.replace(MINUS, "minus ").replace("+", "plus ");

/** The same, for assistive technology: the sign and the units in words. */
export const basisSpoken = (basis: string, pct: string, unit: string): string =>
  `${spoken(signedDecimal(basis))} ${unit}, ${spoken(signedDecimal(pct))} percent`;

const pad = (n: number): string => String(n).padStart(2, "0");

/** "09:14:02 UTC". */
export function utcTime(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

/** The table's time cell: "2026-10-21 09:14:02". */
export const tableTime = (ms: number): string =>
  new Date(ms).toISOString().slice(0, 19).replace("T", " ");
