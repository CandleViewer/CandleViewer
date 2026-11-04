// E24-S04 (#779): the predicted (accruing, unsettled) funding rate, kept apart from every settled one. Fail
// closed (the ticket's Security notes, BQ-2): an item is settled only when it says `predicted: false` and
// does not say `estimated: true`; an absent or non-boolean flag reads as predicted, never as settled.
// `annualised_pct` is the server's (#5699 §19.110); nothing here multiplies a rate.

/** The rate accruing for the next settlement, as served: a fraction per interval and the server's annualised %. */
export interface PredictedRate {
  /** The item's time (the next settlement), or `null` when not served or unreadable. */
  readonly tMs: number | null;
  readonly rate: string;
  /** Percent per year, server-computed; `null` until the contract serves it. Never derived here. */
  readonly annualisedPct: string | null;
}

/** BQ-2: the ticker carries no flag, and its rate is the accruing one (`24` §2.7), so it is always accruing. */
export function isAccruing(
  source: "ticker" | { readonly predicted: unknown; readonly estimated: unknown },
): boolean {
  if (source === "ticker") return true;
  return source.predicted !== false || source.estimated === true;
}

/** Whether two reads of the accruing rate say the same thing (both absent counts as the same). */
export function samePredicted(a: PredictedRate | null, b: PredictedRate | null): boolean {
  return a === null || b === null
    ? a === b
    : a.tMs === b.tMs && a.rate === b.rate && a.annualisedPct === b.annualisedPct;
}

/** Equal as numbers, compared on their digits (never through a float): "0.0001" equals "0.00010". */
export function sameDecimal(a: string, b: string): boolean {
  const norm = (v: string): string => {
    const neg = v.startsWith("-");
    const [int = "0", frac = ""] = (neg ? v.slice(1) : v).split(".");
    const body = `${int.replace(/^0+(?=\d)/, "")}.${frac.replace(/0+$/, "")}`.replace(/\.$/, "");
    return body === "0" ? "0" : `${neg ? "-" : ""}${body}`;
  };
  return norm(a) === norm(b);
}

/** What the header and the legend show for the accruing rate. */
export type FundingReadout =
  | { readonly kind: "na" }
  | {
      readonly kind: "predicted";
      /** The ticker's rate, per interval. */
      readonly rate: string;
      readonly intervalMinutes: number | null;
      /**
       * The server's annualised % for exactly this rate, else `null`: the REST item's value is used only while it
       * is the same rate the ticker shows, so a number and its formula never disagree (BQ-6).
       */
      readonly annualisedPct: string | null;
    };

export interface ReadoutInput {
  /** The ticker's `funding_rate`; `null` when absent. */
  readonly tickerRate: string | null;
  /** Whether the REST read answered (`ready`), so an absent predicted item means "none published" (BQ-4). */
  readonly historyReady: boolean;
  readonly predicted: PredictedRate | null;
  readonly intervalMinutes: number | null;
}

/** BQ-4: n/a when the ticker rate is absent, or REST answered with no predicted item; nothing is carried over. */
export function buildReadout({
  tickerRate,
  historyReady,
  predicted,
  intervalMinutes,
}: ReadoutInput): FundingReadout {
  if (tickerRate === null || (historyReady && predicted === null)) return { kind: "na" };
  const same = predicted !== null && sameDecimal(predicted.rate, tickerRate);
  return {
    kind: "predicted",
    rate: tickerRate,
    intervalMinutes,
    annualisedPct: same && intervalMinutes !== null ? predicted.annualisedPct : null,
  };
}
