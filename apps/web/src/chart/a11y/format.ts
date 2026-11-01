/**
 * The one bar sentence (E47-S01, #1316 BQ-04): the chart's cursor announcement (#520 imports it) and the SCR-045
 * table describe a bar with these functions, so the canvas and the table can never word one bar two ways.
 *
 * Numbers arrive as decimal strings, never floats: `ticksToDecimal` and `qtyToDecimal` turn the engine's typed arrays
 * (Int32 ticks + `priceOrigin`/`tickSize`, Float32 volumes; `26` §8) into exact strings through scaled integers, so a
 * price is shown with the digits the axis shows and is never re-quantised. Output is locale-stable on purpose: `,`
 * groups thousands, `.` is the decimal point, U+2212 is the displayed minus and times are UTC (E11-D04 §5.4).
 */

const DECIMAL = /^-?\d+(?:\.\d+)?$/;
/** U+2212, the displayed minus (E11-D04 §5.4); TSV keeps ASCII `-`. */
export const MINUS = "−";

/** One bar as the sentence and the table read it: µs-epoch time and decimal strings. */
export interface BarFields {
  readonly timeUs: number;
  readonly open: string;
  readonly high: string;
  readonly low: string;
  readonly close: string;
  readonly volume: string;
  /** Ask − bid over the bar's footprint; absent when the bar has no footprint. */
  readonly delta?: string | undefined;
}

function assertDecimal(value: string): void {
  if (!DECIMAL.test(value)) throw new RangeError(`not a decimal string: "${value}"`);
}

/** Decimals a step needs (`0.5` → 1, `0.01` → 2, `1` → 0), read from its shortest round-trip text. */
export function decimalsOf(step: number): number {
  if (!Number.isFinite(step) || step <= 0) throw new RangeError(`bad step: ${step}`);
  const text = String(step);
  const exp = /e-(\d+)$/.exec(text);
  if (exp !== null) {
    const mantissa = text.slice(0, text.indexOf("e"));
    const dot = mantissa.indexOf(".");
    return Number(exp[1]) + (dot < 0 ? 0 : mantissa.length - dot - 1);
  }
  const dot = text.indexOf(".");
  return dot < 0 ? 0 : text.length - dot - 1;
}

/** An integer `scaled` read with `decimals` implied decimals: (12345, 2) → "123.45". */
export function scaledToDecimal(scaled: number, decimals: number): string {
  if (!Number.isSafeInteger(scaled)) throw new RangeError(`unsafe scaled integer: ${scaled}`);
  const negative = scaled < 0;
  const digits = String(Math.abs(scaled)).padStart(decimals + 1, "0");
  const int = digits.slice(0, digits.length - decimals);
  const body = decimals === 0 ? int : `${int}.${digits.slice(digits.length - decimals)}`;
  return negative ? `-${body}` : body;
}

/** `value × unit` as an integer, or a RangeError when `decimals` cannot show `value` exactly. */
function exactScaled(value: number, unit: number, what: string): number {
  const scaled = value * unit;
  const int = Math.round(scaled);
  if (Math.abs(scaled - int) > 1e-6 * Math.max(1, Math.abs(scaled)))
    throw new RangeError(`${what} ${value} needs more than ${Math.log10(unit)} decimals`);
  return int;
}

/**
 * A price in ticks as an exact decimal: `priceOrigin + ticks × tickSize`, in scaled integers (`26` §8). A tick or an
 * origin that `decimals` cannot show (tick 0.05 at 1 decimal) is a RangeError, never a silently re-quantised price;
 * the table's render path shows "not available" for it.
 */
export function ticksToDecimal(
  ticks: number,
  priceOrigin: number,
  tickSize: number,
  decimals: number,
): string {
  const unit = 10 ** decimals;
  const scaled =
    exactScaled(priceOrigin, unit, "price origin") + ticks * exactScaled(tickSize, unit, "tick");
  return scaledToDecimal(scaled, decimals);
}

/** A quantity scaled to `decimals` (the instrument's `qty_step`): summing these is exact. */
export function qtyScaled(value: number, decimals: number): number {
  return Math.round(value * 10 ** decimals);
}

/** A quantity as a decimal string at `decimals`. */
export function qtyToDecimal(value: number, decimals: number): string {
  return scaledToDecimal(qtyScaled(value, decimals), decimals);
}

/** "-64010.5" → "−64,010.5": thousands grouped, the displayed minus. */
export function displayDecimal(value: string): string {
  assertDecimal(value);
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const dot = unsigned.indexOf(".");
  const int = dot < 0 ? unsigned : unsigned.slice(0, dot);
  const frac = dot < 0 ? "" : unsigned.slice(dot);
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const zero = /^[0.]+$/.test(unsigned);
  return `${negative && !zero ? MINUS : ""}${grouped}${frac}`;
}

/** A signed reading (`signDisplay: "always"`, E11-D04 §5.4): "+118", "−14", "+0". */
export function signedDecimal(value: string): string {
  const shown = displayDecimal(value);
  return shown.startsWith(MINUS) ? shown : `+${shown}`;
}

/** TSV's number: the decimal as given, ASCII `-`, no grouping (E11-D04 §8.3). "-0" reads "0". */
export function tsvDecimal(value: string): string {
  assertDecimal(value);
  return /^-[0.]+$/.test(value) ? value.slice(1) : value;
}

const pad2 = (n: number): string => String(n).padStart(2, "0");

/** The bar's open time, UTC: `hh:mm` at intervals ≥ 1 min, `hh:mm:ss` below (E11-D04 §5.1). */
export function formatBarTime(timeUs: number, intervalMs: number): string {
  const d = new Date(Math.floor(timeUs / 1000));
  const hm = `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
  return intervalMs >= 60_000 ? hm : `${hm}:${pad2(d.getUTCSeconds())}`;
}

/** The time cell's full name: "2026-10-20 13:58:00 UTC" (E11-D04 §5.1). */
export function formatBarTimeFull(timeUs: number): string {
  const iso = new Date(Math.floor(timeUs / 1000)).toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
}

/** TSV's time: ISO-8601 UTC to the second, "2026-10-20T13:58:00Z" (E11-D04 §8.3). */
export function tsvTime(timeUs: number): string {
  return `${new Date(Math.floor(timeUs / 1000)).toISOString().slice(0, 19)}Z`;
}

/**
 * One bar as one utterance (Gherkin 1): "13:58, open 64,010.0, high 64,031.5, low 64,002.0, close 64,028.0,
 * volume 212, delta +118". PROPOSED wording pending E47-D06 (#1305): E11-D04 §17.1's row announcement order.
 */
export function formatBarSentence(bar: BarFields, intervalMs: number): string {
  const parts = [
    formatBarTime(bar.timeUs, intervalMs),
    `open ${displayDecimal(bar.open)}`,
    `high ${displayDecimal(bar.high)}`,
    `low ${displayDecimal(bar.low)}`,
    `close ${displayDecimal(bar.close)}`,
    `volume ${displayDecimal(bar.volume)}`,
  ];
  if (bar.delta !== undefined) parts.push(`delta ${signedDecimal(bar.delta)}`);
  return parts.join(", ");
}
