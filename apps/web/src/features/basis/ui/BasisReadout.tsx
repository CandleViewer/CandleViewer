// E24-S08 (#783) slice 1: the basis header readout (D03 §3 Basis row): CMP-036 KeyValueRow pairs in one
// `<dl>` (Mark, Index, Basis), each figure with its unit in the accessible name, the sign of the basis as
// text, the source line, and the source selector as its own Tab stop (CMP-003 SegmentedControl, S54-6).
// `aria-live="off"`: ticks are never announced; the only announcement is the one polite sentence after the
// user changes the source.
import { useState, type JSX, type ReactNode } from "react";
import { FreshnessMarker, KeyValueRow, SegmentedControl } from "@candleviewer/ui";
import { basisOf } from "../basis";
import type { BasisSnapshot } from "../basisFeed";
import type { BasisSource } from "../settings";
import * as copy from "./copy";
import { basisSpoken, basisText, groupedDecimal } from "./format";
import "./basis.css";

export interface BasisReadoutProps {
  readonly symbol: string;
  readonly snapshot: BasisSnapshot;
  readonly source: BasisSource;
  readonly onSourceChange: (source: BasisSource) => void;
  /** The slice 2 freshness slot / state notes, rendered after the rows. */
  readonly children?: ReactNode;
}

/** Drawn one way, read another: the visible form hidden from AT, the spoken form visually hidden. */
const Said = ({ shown, spoken }: { shown: ReactNode; spoken: string }): JSX.Element => (
  <>
    <span aria-hidden="true">{shown}</span>
    <span className="cv-visually-hidden">{spoken}</span>
  </>
);

function price(value: string | null): JSX.Element | null {
  if (value === null) return null;
  const grouped = groupedDecimal(value);
  return (
    <Said
      shown={
        <>
          <span className="cv-basis__num">{grouped}</span> {copy.UNIT}
        </>
      }
      spoken={`${grouped} ${copy.UNIT}`}
    />
  );
}

export function BasisReadout({
  symbol,
  snapshot,
  source,
  onSourceChange,
  children,
}: BasisReadoutProps): JSX.Element {
  const [announce, setAnnounce] = useState("");
  const { latest } = snapshot;
  const reading = latest === null ? null : basisOf(latest, source);
  const { stale } = snapshot;
  const staleChip =
    stale.tier === "fresh" ? undefined : (
      <span className="cv-basis__stale">
        <FreshnessMarker
          presentation="compact"
          state="stale"
          lastUpdatedAgeMs={stale.ageMs}
          escalated={stale.tier === "t2"}
        />
        {stale.lastTsMs === null ? null : <span> · {copy.lastGood(stale.lastTsMs)}</span>}
      </span>
    );
  const choose = (value: string): void => {
    if (value !== "last" && value !== "mark") return;
    setAnnounce(copy.sourceChanged(value));
    onSourceChange(value);
  };
  return (
    <div className="cv-basis" data-cmp="CMP-036" role="group" aria-label={copy.regionName(symbol)}>
      <dl className="cv-basis__rows" aria-live="off">
        <KeyValueRow
          label={copy.MARK_LABEL}
          value={price(latest?.mark ?? null)}
          missingLabel={copy.NO_VALUE}
          freshness={staleChip}
        />
        <KeyValueRow
          label={copy.INDEX_LABEL}
          value={price(latest?.index ?? null)}
          missingLabel={copy.NO_VALUE}
        />
        <KeyValueRow
          label={copy.BASIS_LABEL}
          value={
            reading === null ? null : (
              <Said
                shown={
                  <>
                    <span className="cv-basis__num">{basisText(reading.basis, reading.pct)}</span>{" "}
                    <span className="cv-basis__qualifier">
                      {copy.UNIT} · {copy.sourceLine(source)}
                    </span>
                  </>
                }
                spoken={`${basisSpoken(reading.basis, reading.pct, copy.UNIT)}, ${copy.sourceSpoken(source)}`}
              />
            )
          }
          missingLabel={latest === null ? copy.NO_VALUE : copy.NO_BASIS}
        />
      </dl>
      <SegmentedControl
        aria-label={copy.SOURCE_GROUP}
        size="sm"
        density="compact"
        options={copy.SOURCE_OPTIONS}
        value={source}
        onChange={choose}
      />
      {children}
      <p className="cv-visually-hidden" role="status">
        {announce}
      </p>
    </div>
  );
}
