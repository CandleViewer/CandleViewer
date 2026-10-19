import type { JSX } from "react";
import { SwatchLegendItem } from "./SwatchLegendItem.js";

export type LegendPalette = "default" | "cvd-safe";
export type LegendConvention = "standard" | "inverted";

export interface ColorConventionLegendProps {
  /** The view stating its convention (e.g. "Footprint"). */
  view: string;
  palette?: LegendPalette;
  convention?: LegendConvention;
}

/** Colour name for the buy side under a palette/convention (text, never hue alone). */
export function colourName(
  side: "buy" | "sell",
  palette: LegendPalette,
  convention: LegendConvention,
): string {
  const effective = convention === "inverted" ? (side === "buy" ? "sell" : "buy") : side;
  if (palette === "cvd-safe") return effective === "buy" ? "Blue" : "Orange";
  return effective === "buy" ? "Green" : "Red";
}

/**
 * Per-view colour-convention legend (US-SET-005 scenario 1). Swatches use the
 * directional token custom properties, which the root `data-palette` /
 * `data-convention` attributes already remap; labels state the same mapping
 * as text so the legend reflects CVD-safe and inverted modes.
 */
export function ColorConventionLegend({
  view,
  palette = "default",
  convention = "standard",
}: ColorConventionLegendProps): JSX.Element {
  const buy = colourName("buy", palette, convention);
  const sell = colourName("sell", palette, convention);
  // The group names the legend; its rows stay list items of a real list (axe `listitem`).
  return (
    <div
      role="group"
      aria-label={`${view} colour legend`}
      data-palette={palette}
      data-convention={convention}
    >
      <ul>
        <SwatchLegendItem
          color="var(--color-buy-default)"
          glyph="▲"
          label={`${buy} = buy / bid / up`}
        />
        <SwatchLegendItem
          color="var(--color-sell-default)"
          glyph="▼"
          label={`${sell} = sell / ask / down`}
        />
      </ul>
    </div>
  );
}
