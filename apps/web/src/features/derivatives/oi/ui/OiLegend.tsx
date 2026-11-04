// E24-S02 (#777) slice 2: the OI legend's mode toggle (legend row 0) and the key row
// (D03 S54-10, S54-14, S54-16). The key row names each quadrant with its count, in words and glyphs, so the
// classification never rides on colour (greyscale, D03 §4). Presentational: the counts come from `countBars`.
import type { JSX } from "react";
import { Toggle } from "@candleviewer/ui";
import { QUADRANT_ORDER, QUADRANT_STYLE } from "../quadrant/quadrant";
import type { QuadrantCounts } from "../quadrant/bars";
import * as copy from "./copy";

export type OiMode = "absolute" | "delta";

export interface OiModeToggleProps {
  readonly mode: OiMode;
  readonly onModeChange: (mode: OiMode) => void;
  readonly density: "comfortable" | "compact";
}

/**
 * Legend row 0's mode switch (CN-7; E24-D04 A-08): one CMP-004 `switch`, off = absolute, on = delta per bar.
 * Colouring has no control here: it is the `deriv` settings popover's (D02 §10), so it only arrives as a prop.
 */
export function OiModeToggle({ mode, onModeChange, density }: OiModeToggleProps): JSX.Element {
  return (
    <span className="cv-oi-pane__modes">
      <Toggle
        label={copy.MODE_SWITCH}
        checked={mode === "delta"}
        onChange={(c) => onModeChange(c ? "delta" : "absolute")}
        density={density}
      />
    </span>
  );
}

export interface OiKeyRowProps {
  readonly colouring: boolean;
  readonly counts: QuadrantCounts;
}

export function OiKeyRow({ colouring, counts }: OiKeyRowProps): JSX.Element {
  return (
    <p className="cv-oi-pane__keyrow">
      {colouring ? (
        <>
          {copy.KEY_PREFIX}{" "}
          {QUADRANT_ORDER.map((q, i) => (
            <span key={q}>
              {i === 0 ? "" : " · "}
              <span aria-hidden="true">{QUADRANT_STYLE[q].glyphs} </span>
              {copy.keyCount(QUADRANT_STYLE[q].words, counts.byQuadrant[q])}
            </span>
          ))}
          {counts.noSample > 0 ? ` · ${copy.unclassifiedCount(counts.noSample, true)}` : ""}
          {counts.unclassified > 0
            ? ` · ${copy.unclassifiedCount(counts.unclassified, false)}`
            : ""}
        </>
      ) : (
        copy.QUADRANTS_OFF
      )}
    </p>
  );
}
