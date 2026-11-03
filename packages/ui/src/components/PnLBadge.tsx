import type { JSX } from "react";
import {
  MINUS,
  formatDecimal,
  type DecimalSign,
  type DecimalText,
} from "./internal/decimalText.js";

/** `abs` the signed digits (the column header carries the unit), `currency` the digits and the unit, `pct` percentage
 * points, `r` an R multiple. */
export type PnLFormat = "abs" | "currency" | "pct" | "r";

/** Which way a fee or a funding payment moved (E29-D04 §2.3, D04H:111; E29-D03:144): out of the account or into it. */
export type PnLDirection = "paid" | "received";

/** The spoken reading of an R with no stop on the row (E29-D02:185). */
const R_UNAVAILABLE = "R unavailable: no stop price";
/** CMP-020's reading of a value it cannot show ("—"). */
const NO_VALUE = "no value";
/** The provisional tag (E29-D04:206 `CMP-116/provisional`; E29-D02:252; E29-D03:284 `fills.provisional`). */
const PROVISIONAL = "Provisional — fees pending";

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
  /**
   * Fees are still pending: the tag "Provisional — fees pending" follows the figure, updated in place when they
   * settle (E29-D02:252), and the reading says it after the figure.
   */
  readonly provisional?: boolean;
}

/**
 * `currency` shows its unit, so it needs one; `abs` speaks the unit it is given; `pct` and `r` carry their own.
 * `direction` is a money figure's alone (fees and funding, D04H:111).
 */
type PnLFormatProps =
  | { readonly format?: "abs"; readonly currency?: string; readonly direction?: PnLDirection }
  | { readonly format: "currency"; readonly currency: string; readonly direction?: PnLDirection }
  | { readonly format: "pct" | "r"; readonly currency?: never; readonly direction?: never };

export type PnLBadgeProps = PnLBadgeBase & PnLFormatProps;

/** The sign in words, read before the magnitude: "profit 8.00 USDT", "loss 121.50 USDT"; zero has no word. */
const WORDS = { positive: "profit ", negative: "loss ", zero: "" } as const;
/** A fee's or a payment's way in words, in place of profit or loss: "paid 3.49 USDT" (D04H:114, less its noun). */
const DIRECTION_WORDS = { paid: "paid ", received: "received " } as const;

/** The word before the magnitude: the way the money went when a direction is given, else profit or loss. */
const wordOf = (sign: DecimalSign, direction: PnLDirection | undefined): string =>
  direction === undefined || sign === "zero" ? WORDS[sign] : DIRECTION_WORDS[direction];

/** A figure as shown: its display (null shows "—") and the one sentence assistive technology reads for it. */
interface Figure {
  readonly shown: DecimalText | null;
  readonly reading: string;
}

/**
 * The display and the reading of a badge. With a `direction` the magnitude is signed as cash, paid with U+2212 and
 * received with "+", whatever sign the host's string carries; zero stays unsigned and wordless.
 */
function figureOf(props: PnLBadgeProps): Figure {
  const { value, places, direction } = props;
  const format = props.format ?? "abs";
  const parsed =
    value === null
      ? null
      : formatDecimal(value, { ...(places === undefined ? {} : { places }), plus: true });
  const shown: DecimalText | null =
    direction === undefined || parsed === null || parsed.sign === "zero"
      ? parsed
      : {
          text: `${direction === "paid" ? MINUS : "+"}${parsed.magnitude}`,
          magnitude: parsed.magnitude,
          sign: direction === "paid" ? "negative" : "positive",
        };
  const unit = format === "r" ? "R" : format === "pct" ? undefined : props.currency;
  const spokenUnit = unit === undefined ? (format === "pct" ? "%" : "") : ` ${unit}`;
  const figure =
    shown === null
      ? (props.nullReading ?? (format === "r" ? R_UNAVAILABLE : NO_VALUE))
      : `${wordOf(shown.sign, direction)}${shown.magnitude}${spokenUnit}`;
  return { shown, reading: props.provisional === true ? `${figure}, ${PROVISIONAL}` : figure };
}

/**
 * CMP-116's sentence for a figure, the words its hidden node reads ("profit 8.00 USDT", "loss 121.50 USDT", "R
 * unavailable: no stop price", "paid 3.49 USDT, Provisional — fees pending"), for a host's description that cannot
 * hold the badge itself (CMP-114's dock totals).
 */
export function pnlReading(props: PnLBadgeProps): string {
  return figureOf(props).reading;
}

/**
 * CMP-116 PnLBadge (E29-D04 §2.3, D04H §C.3; the `bar` variant, built by E29-S01 with `abs`, `currency`, `pct` and
 * `r`, and by E29-S04 with `direction` and `provisional`): the digits stay `color.text.primary` and the sign is text
 * ("+" or U+2212, zero unsigned), so the hue rides only on a `border.thick` accent bar before them (E29-D02 D-6).
 * Assistive technology reads one visually hidden sentence, the sign in words with the magnitude and its unit
 * ("profit 8.00 USDT", "paid 3.49 USDT"), and the provisional tag after it, never an `aria-label` on the span; every
 * visible part is `aria-hidden`. A fee's or a payment's noun ("fee paid …", D04H:114) is the host's: no prop carries
 * it (D04H:111). Not interactive, no live region (the host's), no motion of its own: the tag comes and goes as a cut.
 */
export function PnLBadge(props: PnLBadgeProps): JSX.Element {
  const { size = "md" } = props;
  const format = props.format ?? "abs";
  const { shown, reading } = figureOf(props);
  const percent = format === "pct" ? "%" : "";
  const visibleUnit =
    format === "currency" && props.currency !== undefined ? ` ${props.currency}` : percent;
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
      {props.provisional === true ? (
        <span className="cv-pnl-badge__tag" aria-hidden="true">
          {PROVISIONAL}
        </span>
      ) : null}
      <span className="cv-visually-hidden">{reading}</span>
    </span>
  );
}
