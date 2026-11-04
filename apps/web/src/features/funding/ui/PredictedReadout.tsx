// E24-S04 (#779): the accruing funding rate beside CMP-126's countdown (D02 §5.1, D03 §5.1): "0.0100 % / 8 h ·
// 10.95 % p.a. · predicted (estimated)" or, annualised, "10.95 % p.a. · 0.0100 % / 8 h · predicted (estimated)".
// Never styled as settled: the word "predicted" and the CMP-227 badge carry it (colour is never the signal), and
// the component takes no flag to switch them off. The annualised figure is the server's, only formatted here.
import { useId, type JSX } from "react";
import { EstimatedBadge } from "@candleviewer/ui";
import type { FundingReadout } from "../predicted";
import * as copy from "./copy";
import { annualisedFormula, annualisedPercent, intervalWords, ratePercent } from "./format";

type Predicted = Extract<FundingReadout, { kind: "predicted" }>;

/** True when the server's annualised value is served together with the interval its formula needs (BQ-6). */
const annualisedOf = (r: Predicted): { text: string; spoken: string; formula: string } | null =>
  r.annualisedPct === null || r.intervalMinutes === null
    ? null
    : {
        ...annualisedPercent(r.annualisedPct),
        formula: annualisedFormula(r.rate, r.intervalMinutes, r.annualisedPct),
      };

/** CMP-126's `rate`: the primary figure, per interval or annualised; absent for n/a. */
export function readoutRate(readout: FundingReadout, annualised: boolean): string | undefined {
  if (readout.kind === "na") return undefined;
  const ann = annualised ? annualisedOf(readout) : null;
  return ann === null ? ratePercent(readout.rate).text : ann.text;
}

export interface PredictedReadoutProps {
  readonly readout: FundingReadout;
  /** The toggle's state; ignored while no annualised value is served. */
  readonly annualised: boolean;
}

export function PredictedReadout({ readout, annualised }: PredictedReadoutProps): JSX.Element {
  const formulaId = useId();
  if (readout.kind === "na") {
    return (
      <span className="cv-funding-readout" data-state="na">
        <span>{copy.PREDICTED_NA}</span>
        <span className="cv-visually-hidden">{copy.PREDICTED_NA_DESCRIPTION}</span>
      </span>
    );
  }
  const ann = annualisedOf(readout);
  const asked = annualised && ann !== null;
  const interval =
    readout.intervalMinutes === null ? "" : `/ ${intervalWords(readout.intervalMinutes)}`;
  const rate = ratePercent(readout.rate);
  // CMP-126 shows the primary figure; this is the other one, carrying the formula when it can be stated
  const other = asked
    ? `${rate.text} ${interval}`.trim()
    : ann === null
      ? interval
      : `${interval} · ${ann.text}`; // `ann` non-null means an interval is served (BQ-6)
  return (
    <span className="cv-funding-readout" data-state="predicted">
      {other === "" ? null : ann === null ? (
        <span className="cv-funding-readout__figure">{other}</span>
      ) : (
        <>
          {/* no tab stop: the formula is the figure's description, read with it (a hover tooltip is not offered) */}
          <span className="cv-funding-readout__figure" aria-describedby={formulaId}>
            {other}
          </span>
          <span id={formulaId} className="cv-visually-hidden">
            {ann.formula}
          </span>
        </>
      )}
      <span className="cv-funding-readout__word">{copy.PREDICTED_WORD}</span>
      <EstimatedBadge
        detector="funding"
        variant="inline"
        size="sm"
        name="Funding rate"
        tooltip={copy.PREDICTED_PROVENANCE}
      />
    </span>
  );
}
