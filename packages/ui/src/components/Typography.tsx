import type { ComponentPropsWithoutRef, JSX } from "react";
import { cx } from "./internal/cx.js";
import {
  formatDisplayNumber,
  type NumericFormat,
  type SignDisplay,
} from "./internal/numberDisplay.js";

export type { NumericFormat, SignDisplay } from "./internal/numberDisplay.js";
export type TextVariant = "caption" | "body" | "body-strong" | "label";
export type HeadingVariant = "heading-sm" | "heading-md" | "heading-lg" | "display";
export type NumSize = "xs" | "sm" | "base" | "md" | "lg" | "xl";
export type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

export interface TextProps extends Omit<ComponentPropsWithoutRef<"span">, "style" | "color"> {
  /** The `type.ui.*` role. */
  variant?: TextVariant;
  /** Instance colour (E05-D02 §5 E14): `color.text.primary` by default. */
  tone?: "primary" | "secondary";
  /** A paragraph or an inline span (generic, no role). */
  as?: "span" | "p";
}

/** CMP-020 Text: body copy bound to `type.ui.caption|body|body-strong|label`. */
export function Text({
  variant = "body",
  tone = "primary",
  as: Tag = "span",
  className,
  ...rest
}: TextProps): JSX.Element {
  return (
    <Tag
      {...rest}
      className={cx("cv-text", className)}
      data-cmp="CMP-020"
      data-variant={variant}
      data-tone={tone}
    />
  );
}

export interface HeadingProps extends Omit<ComponentPropsWithoutRef<"h2">, "style" | "color"> {
  /** The semantic level: renders `h1`..`h6`, independent of `variant`. */
  level: HeadingLevel;
  /** The visual style (`type.ui.heading-*|display`), independent of `level`. */
  variant?: HeadingVariant;
}

/** CMP-020 Heading: `level` sets the outline, `variant` the look; neither implies the other. */
export function Heading({
  level,
  variant = "heading-md",
  className,
  ...rest
}: HeadingProps): JSX.Element {
  const Tag = `h${level}` as const;
  return (
    <Tag
      {...rest}
      className={cx("cv-heading", className)}
      data-cmp="CMP-020"
      data-variant={variant}
    />
  );
}

export interface MonoTextProps extends Omit<ComponentPropsWithoutRef<"span">, "style" | "color"> {
  /** The `type.num.*` step. */
  size?: NumSize;
  /** `code` when the content is code; ids and hashes stay a span. */
  as?: "span" | "code";
}

/** CMP-020 MonoText: ids, hashes and codes in `type.num.*` (fixed-width digits). */
export function MonoText({
  size = "base",
  as: Tag = "span",
  className,
  ...rest
}: MonoTextProps): JSX.Element {
  return <Tag {...rest} className={cx("cv-mono", className)} data-cmp="CMP-020" data-size={size} />;
}

interface NumericTextBase extends Omit<
  ComponentPropsWithoutRef<"span">,
  "style" | "color" | "children" | "role" | "aria-label" | "aria-labelledby"
> {
  /** Display-only: never parse it back for an order. `pct` takes percentage points. */
  value: number;
  /** Decimals; defaults per format (price 2, qty 3, pct 2, pnl 2, notional 1). */
  precision?: number;
  /** The `type.num.*` step. */
  size?: NumSize;
}

/** `pnl` and `colorBySign` require an explicit `signDisplay="always"` (05 §4.1, §5 E14). */
type SignRule =
  | { format: "pnl"; signDisplay: "always"; colorBySign?: boolean }
  | { format?: Exclude<NumericFormat, "pnl">; colorBySign: true; signDisplay: "always" }
  | { format?: Exclude<NumericFormat, "pnl">; colorBySign?: false; signDisplay?: SignDisplay };

export type NumericTextProps = NumericTextBase & SignRule;

/**
 * CMP-020 NumericText: tabular numerics are the component's, never the consumer's (`.cv-num` sets
 * `font-variant-numeric: tabular-nums` and `type.num.*`). Zero is never signed. An abbreviated value
 * shows "1.2M" `aria-hidden` and reads the visually hidden "1,200,000" (§5 E15).
 */
export function NumericText({
  value,
  format = "price",
  precision,
  signDisplay,
  colorBySign = false,
  size = "base",
  className,
  ...rest
}: NumericTextProps): JSX.Element {
  // The types forbid a softer sign; an untyped caller still gets the sign, never colour alone.
  const sign = format === "pnl" || colorBySign ? "always" : (signDisplay ?? "auto");
  const shown = formatDisplayNumber(value, format, {
    ...(precision === undefined ? {} : { precision }),
    signDisplay: sign,
  });
  return (
    <span
      {...rest}
      className={cx("cv-num", className)}
      data-cmp="CMP-020"
      data-size={size}
      data-format={format}
      data-sign={shown.sign}
      data-color-by-sign={colorBySign ? "" : undefined}
    >
      {shown.expanded === undefined ? (
        shown.text
      ) : (
        <>
          <span aria-hidden="true">{shown.text}</span>
          <span className="cv-visually-hidden">{shown.expanded}</span>
        </>
      )}
    </span>
  );
}
