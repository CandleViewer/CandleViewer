// E24-S01 (#776) slice 2: the OI pane's number and time formats. Formatting only — the decimals arrive as
// strings from the engine and are never combined (the ticket's "No client-side computation"). Formats are
// D03 §2's rows: OI level k / M / B with one decimal + " USDT"; base quantities comma-grouped as sent;
// times in UTC.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MINUS = "−";

const groupInt = (digits: string): string => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** "57911.602" → "57,911.602": the decimal as sent, grouped; the sign as text (U+2212). */
export function groupedDecimal(value: string): string {
  const negative = value.startsWith("-");
  const [int = "", frac] = (negative ? value.slice(1) : value).split(".");
  const body = frac === undefined ? groupInt(int) : `${groupInt(int)}.${frac}`;
  return negative ? `${MINUS}${body}` : body;
}

/** Smallest first: the scale is the largest one the integer part reaches, then a rounding carry moves it up. */
const SCALES = [
  { digits: 3, suffix: "k", word: "thousand" },
  { digits: 6, suffix: "M", word: "million" },
  { digits: 9, suffix: "B", word: "billion" },
] as const;

/**
 * D03 §2 "OI level": "4792254559.42" → "4.8B"; below 1 000 the grouped decimal. Rounded half-up on the decimal
 * string's own digits (no float), and a carry that reaches 1 000.0 moves to the next scale: 999 950 000 → "1.0B".
 */
export function compact(value: string): { readonly text: string; readonly spoken: string } {
  const negative = value.startsWith("-");
  const int = (negative ? value.slice(1) : value).split(".")[0]?.replace(/^0+(?=\d)/, "") ?? "";
  const plain = (): { text: string; spoken: string } => {
    const text = groupedDecimal(value);
    return { text, spoken: text.replace(MINUS, "minus ") };
  };
  if (!/^\d+$/.test(int)) return plain();
  let i = -1;
  SCALES.forEach((sc, k) => {
    if (int.length > sc.digits) i = k;
  });
  if (i < 0) return plain();
  for (;;) {
    const scale = SCALES[i];
    if (scale === undefined) return plain();
    // tenths of the scale: the integer digits above `digits - 1`, rounded on the next digit
    const cut = int.length - (scale.digits - 1);
    const tenths = BigInt(int.slice(0, cut) || "0") + (Number(int[cut] ?? "0") >= 5 ? 1n : 0n);
    if (tenths >= 10_000n && i < SCALES.length - 1) {
      i += 1;
      continue;
    }
    const digits = `${String(tenths / 10n)}.${String(tenths % 10n)}`;
    const sign = negative ? MINUS : "";
    return {
      text: `${sign}${digits}${scale.suffix}`,
      spoken: `${negative ? "minus " : ""}${digits} ${scale.word}`,
    };
  }
}

/** A signed per-bar delta as sent: "+12.5" / "−3.1", the sign as text. */
export function signedDecimal(value: string): string {
  const unsigned = value.startsWith("-") ? value.slice(1) : value;
  if (/^0*(\.0*)?$/.test(unsigned)) return groupedDecimal(unsigned); // zero is unsigned, "-0.000" too
  return value.startsWith("-") ? groupedDecimal(value) : `+${groupedDecimal(value)}`;
}

const pad = (n: number): string => String(n).padStart(2, "0");

/** "09:14:02 UTC". */
export function utcTime(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

/** "21 Oct 09:14 UTC": the date before the time (D02 DV-11). */
export function utcDateTime(ms: number): string {
  const d = new Date(ms);
  const day = `${String(d.getUTCDate())} ${MONTHS[d.getUTCMonth()] ?? ""}`;
  return `${day} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

/** The table's time cell: "2026-10-21 09:14:00". */
export function tableTime(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19).replace("T", " ");
}
