import type { JSX } from "react";
import { formatDecimal } from "./internal/decimalText.js";

/** `abs` the signed digits (the column header carries the unit), `currency` the digits and the unit, `pct` percentage
 * points, `r` an R multiple. */
export type PnLFormat = "abs" | "currency" | "pct" | "r";

/** The spoken reading of an R with no stop on the row (E29-D02:185). */
const R_UNAVAILABLE = "R unavailable: no stop price";
/** CMP-020's reading of a value it cannot show ("—"). */
const NO_VALUE = "no value";

interface PnLBadgeBase {
  /**
   * The server's figure as a decimal string (`cv://ws/v1/common.schema.json` `decimal`), never a JS number: the
   * badge formats it and computes nothing (E29-D04 §2.3). `null`, or a string that is not a decimal, shows "—".
   */
  readonly value: string | null;
  /** Decimal places shown: the instrument's (E29-D02 D-7); omitted, the string's own. Half away from zero. */
  readonly places?: number;
  /** What a "—" reads as; omitted, "R unavailable: no stop price" for `r` (E29-D02:185), else "no value". */
  readonly nullReading?: string;
  /** The digits' step: `type.num.sm`, `type.num.base` (default `md`) or `type.num.md`. */
  readonly size?: "sm" | "md" | "lg";
}

/** `currency` shows its unit, so it needs one; `abs` speaks the unit it is given; `pct` and `r` carry their own. */
type PnLFormatProps =
  | { readonly format?: "abs"; readonly currency?: string }
  | { readonly format: "currency"; readonly currency: string }
  | { readonly format: "pct" | "r"; readonly currency?: never };

export type PnLBadgeProps = PnLBadgeBase & PnLFormatProps;

/** The sign in words, read before the magnitude: "profit 8.00 USDT", "loss 121.50 USDT"; zero has no word. */
const WORDS = { positive: "profit ", negative: "loss ", zero: "" } as const;

/**
 * CMP-116 PnLBadge (E29-D04 §2.3, D04H §C.3; E29-S01 builds `abs`, `currency`, `pct` and `r` in the `bar` variant):
 * the digits stay `color.text.primary` and the sign is text ("+" or U+2212, zero unsigned), so the hue rides only
 * on a `border.thick` accent bar before them (E29-D02 D-6). Assistive technology reads one visually hidden sentence,
 * the sign in words with the magnitude and its unit ("profit 8.00 USDT"), never an `aria-label` on the span; the
 * visible digits and the bar are `aria-hidden`. Not interactive, no live region (the host's), no motion of its own.
 */
export function PnLBadge(props: PnLBadgeProps): JSX.Element {
  const { value, places, nullReading, size = "md" } = props;
  const format = props.format ?? "abs";
  const shown =
    value === null
      ? null
      : formatDecimal(value, { ...(places === undefined ? {} : { places }), plus: true });
  const unit = format === "r" ? "R" : format === "pct" ? undefined : props.currency;
  const percent = format === "pct" ? "%" : "";
  const visibleUnit = format === "currency" && unit !== undefined ? ` ${unit}` : percent;
  const spokenUnit = unit === undefined ? percent : ` ${unit}`;
  return (
    <span
      className="cv-pnl-badge"
      data-cmp="CMP-116"
      data-format={format}
      data-size={size}
      data-sign={shown?.sign}
    >
      {shown === null ? null : <span className="cv-pnl-badge__bar" aria-hidden="true" />}
      <span className="cv-pnl-badge__value" aria-hidden="true">
        {shown === null ? "—" : `${shown.text}${visibleUnit}`}
      </span>
      <span className="cv-visually-hidden">
        {shown === null
          ? (nullReading ?? (format === "r" ? R_UNAVAILABLE : NO_VALUE))
          : `${WORDS[shown.sign]}${shown.magnitude}${spokenUnit}`}
      </span>
    </span>
  );
}
