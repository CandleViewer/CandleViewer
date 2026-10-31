// THROWAWAY SPIKE HARNESS (E11-K01, BQ-172). Glyph sets per family, shared by Node and the browser.
const ascii = () =>
  Array.from({ length: 0x7f - 0x20 }, (_, i) => String.fromCodePoint(0x20 + i)).join("");

/** Recommended set: printable ASCII per family, plus `× ▲ ▼` (mono) and `·` (UI). 98 + 96 = 194. */
export const FULL = { mono: ascii() + "×▲▼", ui: ascii() + "·" };

/** Floor fallback: E06-D01 §3's 73 + `:` (mono) and `A–Z 0–9 a–z · space` (UI, 64). */
const AZ = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const az = AZ.toLowerCase();
export const FLOOR = {
  mono: "0123456789.,-+%×KMB" + AZ + az + "▲▼" + " ()" + ":",
  ui: AZ + "0123456789" + az + "· ",
};

/** Footprint cell glyphs (E06-D01 §3 without letters): the SSIM gate is read on these first. */
export const CELL = "0123456789.,-+%×KMB▲▼()";

/** Confusable pairs for the legibility gate (BQ-179). */
export const PAIRS = ["08", "38", "56", "68", "17", ",."];

/** The sample line drawn in the legibility images (E06-D01 cells, E11-D02 axis formats). */
export const SAMPLE = "1.2K × 3.4K ▲+128 ▼-64 13:30 14 Oct 2027 63,201.5 (estimated)";

export const FNV = (s) => {
  let h = 0x811c9dc5;
  for (const ch of s) h = Math.imul(h ^ ch.codePointAt(0), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, "0");
};
