// E24-S05 (#780) PR 4: AN-4, the cascade summary (D04 LR-4, §5, §9.3; D02 §13). Polite, through the shell's one
// announcer; never per print. A summary is said on the leading edge, when the rate reaches the cascade threshold,
// then at most once per 5 000 ms while it lasts, each naming the rate; there is no closing message.
// "mostly longs" / "mostly shorts" when one side holds at least 2/3 of the window's served notional, else "on both
// sides" (D04 F-1, PROPOSED; ruled 6612481277 BQ 8).

/** D04 §5 G-1, PROPOSED to the owner: the rate at which the cascade state (and AN-4) starts. */
export const CASCADE_THRESHOLD_PER_SEC = 10;
/** AN-4's throttle (D04 §9.3, BQ-17): at most one summary per 5 s. */
export const SUMMARY_EVERY_MS = 5_000;
/**
 * While a cascade lasts, how often the summary is re-checked (a flat rate, or a write the region refused). Finer than
 * the throttle, so the cadence never stretches past 5 s plus a second; the throttle still caps it at one per 5 s.
 */
export const SUMMARY_RECHECK_MS = 1_000;
/** D04 F-1 (PROPOSED): "mostly" needs at least this share of the window's notional. */
export const MOSTLY_SHARE = 2 / 3;

const grouped = (n: number): string => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/**
 * "Liquidations: 1,240 per second, mostly longs liquidated." An unknown split (no served notional; `notional_usd` is
 * optional in `23` §14.9) names no side: "Liquidations: 1,240 per second."
 */
export function summaryText(ratePerSec: number, longShare: number | null): string {
  const rate = `Liquidations: ${grouped(ratePerSec)} per second`;
  if (longShare === null) return `${rate}.`;
  const sides =
    longShare >= MOSTLY_SHARE
      ? "mostly longs liquidated"
      : 1 - longShare >= MOSTLY_SHARE
        ? "mostly shorts liquidated"
        : "on both sides";
  return `${rate}, ${sides}.`;
}

/**
 * The throttle, outside React: `observe` returns the sentence to say now, or `null`. `canSay` is the shell region's
 * own budget (E17-D02 §11): when it refuses, nothing is consumed, so the next evaluation can still be the summary.
 */
export class CascadeSummary {
  private lastSaidAt: number | null = null;

  observe(
    ratePerSec: number,
    longShare: number | null,
    nowMs: number,
    canSay: () => boolean = () => true,
  ): string | null {
    if (ratePerSec < CASCADE_THRESHOLD_PER_SEC) return null;
    if (this.lastSaidAt !== null && nowMs - this.lastSaidAt < SUMMARY_EVERY_MS) return null;
    if (!canSay()) return null;
    this.lastSaidAt = nowMs;
    return summaryText(ratePerSec, longShare);
  }
}
