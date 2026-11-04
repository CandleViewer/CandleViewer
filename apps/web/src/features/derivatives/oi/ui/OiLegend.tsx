// E24-S02 (#777) slice 2: the OI legend's mode toggle (legend row 0) and the key row
// (D03 S54-10, S54-14, S54-16). The key row names each quadrant with its count, in words and glyphs, so the
// classification never rides on colour (greyscale, D03 §4). Presentational: the counts come from `countBars`.
import type { JSX } from "react";
import { Button } from "@candleviewer/ui";
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
 * Legend row 0's Absolute / Delta switch (CN-7). Colouring has no control here: it is the `deriv`
 * settings popover's (D02 §10), so it only arrives as a prop. The pressed state is the fill plus a check.
 */
export function OiModeToggle({ mode, onModeChange, density }: OiModeToggleProps): JSX.Element {
  const choice = (m: OiMode, label: string): JSX.Element => (
    <Button
      variant={mode === m ? "secondary" : "ghost"}
      size="sm"
      density={density}
      aria-pressed={mode === m}
      onClick={() => {
        if (mode !== m) onModeChange(m);
      }}
    >
      {mode === m ? <span aria-hidden="true">✓ </span> : null}
      {label}
    </Button>
  );
  return (
    <span role="group" aria-label={copy.MODE_GROUP} className="cv-oi-pane__modes">
      {choice("absolute", copy.MODE_ABSOLUTE)}
      {choice("delta", copy.MODE_DELTA)}
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
