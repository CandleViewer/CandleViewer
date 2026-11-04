// E24-S01 (#776) slice 2: the OI header readout (D02 §3, D03 §3 OI row) — CMP-036 KeyValueRow pairs in one
// `<dl>`: the current OI with its unit in the accessible name, the per-bar delta labelled as such (BQ 2), and
// the CMP-239 chip when the ticker is stale. `aria-live="off"`: OI is never announced (D02 §13).
import type { JSX, ReactNode } from "react";
import { FreshnessMarker, KeyValueRow } from "@candleviewer/ui";
import type { OiRow } from "../series";
import type { StaleTier } from "../freshness";
import * as copy from "./copy";
import { quadrantReading, type QuadrantWire } from "../quadrant/quadrant";
import { compact, groupedDecimal, signedDecimal } from "./format";

export interface OiDelta {
  /** `metrics.{symbol}` `open_interest_delta` as served (per bar); `null` when the bar has none. */
  readonly value: string | null;
  /** The unit word, from the served descriptor; never hard-coded here. */
  readonly unit: string;
  /** E24-S02: the served quadrant for the bar; `null` = unclassified, absent = not given. */
  readonly quadrant?: QuadrantWire | null;
}

export interface OiReadoutProps {
  readonly latest: OiRow | null;
  readonly baseUnit: string;
  readonly quoteUnit: string;
  readonly delta?: OiDelta | undefined;
  /** E24-S02: quadrant colouring on (D03 S54-13: the crosshair reads the quadrant in words). */
  readonly showQuadrant?: boolean;
  readonly stale: {
    readonly tier: StaleTier;
    readonly ageMs: number;
    readonly lastTsMs: number | null;
  };
}

/** Drawn one way, read another: the visible form hidden from AT, the spoken form visually hidden. */
const Said = ({ shown, spoken }: { shown: ReactNode; spoken: string }): JSX.Element => (
  <>
    <span aria-hidden="true">{shown}</span>
    <span className="cv-visually-hidden">{spoken}</span>
  </>
);

function level(latest: OiRow, baseUnit: string, quoteUnit: string): JSX.Element {
  // BQ 1: the USDT value only from the live ticker; a REST point is in base coin
  const c =
    latest.valueUsdt === null
      ? { text: groupedDecimal(latest.base), spoken: groupedDecimal(latest.base), unit: baseUnit }
      : { ...compact(latest.valueUsdt), unit: quoteUnit };
  return (
    <Said
      shown={
        <>
          <span className="cv-oi-readout__num">{c.text}</span> {c.unit}{" "}
          <span className="cv-oi-readout__qualifier">{copy.BOTH_SIDES}</span>
        </>
      }
      spoken={`${c.spoken} ${c.unit}, both sides`}
    />
  );
}

export function OiReadout({
  latest,
  baseUnit,
  quoteUnit,
  delta,
  showQuadrant = false,
  stale,
}: OiReadoutProps): JSX.Element {
  const staleChip =
    stale.tier === "fresh" ? undefined : (
      <span className="cv-oi-readout__stale">
        <FreshnessMarker
          presentation="compact"
          state="stale"
          lastUpdatedAgeMs={stale.ageMs}
          escalated={stale.tier === "t2"}
        />
        {stale.lastTsMs === null ? null : <span> · {copy.lastGood(stale.lastTsMs)}</span>}
      </span>
    );
  return (
    <dl className="cv-oi-readout" aria-live="off">
      <KeyValueRow
        label={copy.OI_LABEL}
        value={latest === null ? null : level(latest, baseUnit, quoteUnit)}
        missingLabel="no value yet"
        freshness={staleChip}
      />
      {delta === undefined ? null : (
        <KeyValueRow
          label={<Said shown={copy.DELTA_LABEL} spoken={copy.DELTA_NAME} />}
          value={
            delta.value === null ? null : (
              <span className="cv-oi-readout__num">
                {signedDecimal(delta.value)} {delta.unit}
              </span>
            )
          }
          missingLabel="no change for this bar"
        />
      )}
      {delta === undefined || !showQuadrant || delta.quadrant === undefined ? null : (
        <KeyValueRow
          label={copy.QUADRANT_LABEL}
          value={delta.quadrant === null ? copy.UNCLASSIFIED : quadrantReading(delta.quadrant)}
        />
      )}
    </dl>
  );
}
