import type { ComponentPropsWithoutRef, JSX } from "react";
import { cx } from "./internal/cx.js";

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
