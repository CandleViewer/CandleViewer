// E24-S03 (#778) slice 1: the funding pane's formats. Formatting only: a rate arrives as a decimal string
// (a fraction per interval, `0.0001` is 0.01 %) and is shown in percent with four decimals (D03 §5.1,
// BQ-13's form), rounded half-up on its own digits, never through a float. The sign is text (U+2212 or
// "+"), never a hue (D03 §5.1). Times are UTC.

const MINUS = "−";
const pad = (n: number): string => String(n).padStart(2, "0");

/** "0.0001" → { text: "+0.0100 %", spoken: "plus 0.0100 percent" }; "0" → "0.0000 %". */
export function ratePercent(value: string): { readonly text: string; readonly spoken: string } {
  const negative = value.startsWith("-");
  const [int = "0", frac = ""] = (negative ? value.slice(1) : value).split(".");
  // the rate × 10^6 is the percent × 10^4: six fraction digits, rounded half-up on the seventh
  const digits = `${frac}0000000`;
  let scaled = BigInt(`${int}${digits.slice(0, 6)}`) + (Number(digits[6]) >= 5 ? 1n : 0n);
  if (scaled < 0n) scaled = -scaled;
  const body = `${String(scaled / 10_000n)}.${String(scaled % 10_000n).padStart(4, "0")}`;
  if (scaled === 0n) return { text: `${body} %`, spoken: `${body} percent` };
  return negative
    ? { text: `${MINUS}${body} %`, spoken: `minus ${body} percent` }
    : { text: `+${body} %`, spoken: `plus ${body} percent` };
}

/** 480 → "8 h", 60 → "1 h", 30 → "30 min". */
export function intervalWords(minutes: number): string {
  return minutes % 60 === 0 ? `${String(minutes / 60)} h` : `${String(minutes)} min`;
}

/** "09:14:02 UTC". */
export function utcTime(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

/** The table's settlement cell: "2023-11-15 00:00". */
export function settlementTime(ms: number): string {
  return new Date(ms).toISOString().slice(0, 16).replace("T", " ");
}
