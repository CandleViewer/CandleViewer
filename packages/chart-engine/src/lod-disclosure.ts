// The aggregated-level text (E12-S09 PR 1, #421 BQ-08; E12-D06 §6.1, §13): a pure formatter the
// app's status-row chip and the DOM mirror (E11-S13) read, so the tier is said in words, never
// by a badge's colour alone (AC4). The chip, its polite announcements and the readout are PR 2's
// (the app and E11-S13's mirror); the engine reports the state (`viewport.lod`, E11-S12).

/** `LodState` (26 §8, E11-S12), structurally: the candle tier and the bars per device column. */
export interface LodDisclosureInput {
  readonly candles: number;
  readonly barsPerColumn: number;
  readonly aggregated: boolean;
}

/**
 * The words for a candle tier: null at L0 and L1 (nothing is aggregated, D06 §6.1). At L2
 * aggregated, the chip "Zoomed out · 1 column = N bars" and the mirror suffix "N bars per column",
 * N = barsPerColumn rounded half up (D06 §2); else the PROPOSED "Zoomed out · high–low only".
 */
export function lodDisclosure(lod: LodDisclosureInput): { chip: string; mirror: string } | null {
  if (lod.candles !== 2) return null;
  const n = Math.floor(lod.barsPerColumn + 0.5);
  if (!lod.aggregated || !Number.isFinite(n) || n < 1) {
    return { chip: "Zoomed out · high–low only", mirror: "high–low only" };
  }
  const bars = n === 1 ? "1 bar" : `${n} bars`;
  return { chip: `Zoomed out · 1 column = ${bars}`, mirror: `${bars} per column` };
}
