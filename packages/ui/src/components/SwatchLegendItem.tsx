import type { CSSProperties, JSX } from "react";
import { NumericText, Text, type NumericFormat } from "./Typography.js";

/** A swatch colour that encodes direction (buy / sell, up / down): the glyph is then required (§5 E16). */
export type DirectionalSwatchColor =
  | `var(--color-${"buy" | "sell"}-${string})`
  | `var(--color-cvd-${"buy" | "sell"})`
  | `var(--color-candle-${"up" | "down"})`;

interface SwatchLegendItemBase<C extends string> {
  /** A token custom property, e.g. `var(--color-heatmap-bid-3)`: the keyed data colour. */
  color: C;
  /** States the meaning; the swatch and glyph only reinforce it. */
  label: string;
  /** Display-only, through CMP-020 NumericText (`type.num.sm`); an abbreviation reads in full. */
  value?: number;
  /** NumericText format of `value`; `notional` ("1.2M") by default. */
  format?: Exclude<NumericFormat, "pnl">;
  precision?: number;
}

/** `glyph` (`aria-hidden`, e.g. "▲") is the non-colour channel, required for a directional colour. */
export type SwatchLegendItemProps<C extends string = string> = SwatchLegendItemBase<C> &
  (C extends DirectionalSwatchColor ? { glyph: string } : { glyph?: string });

/**
 * CMP-037: one legend row, an `li` of its legend's list. The `size.icon` swatch keeps its real colour
 * in forced colours (it must match the chart, which they do not repaint); the label carries the meaning.
 */
export function SwatchLegendItem<C extends string>(props: SwatchLegendItemProps<C>): JSX.Element {
  const { color, label, value, format = "notional", precision, glyph } = props;
  const swatch = { "--cv-legend-swatch": color } as CSSProperties;
  return (
    <li className="cv-legend-item" data-cmp="CMP-037">
      <span
        aria-hidden="true"
        className="cv-legend-item__swatch"
        data-testid="legend-swatch"
        style={swatch}
      />
      {glyph === undefined ? null : (
        <span aria-hidden="true" className="cv-legend-item__glyph">
          {glyph}
        </span>
      )}
      <Text variant="caption" tone="secondary" className="cv-legend-item__label">
        {label}
      </Text>
      {value === undefined ? null : (
        <NumericText
          className="cv-legend-item__value"
          value={value}
          format={format}
          size="sm"
          {...(precision === undefined ? {} : { precision })}
        />
      )}
    </li>
  );
}
