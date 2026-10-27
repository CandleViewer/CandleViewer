import type { JSX, ReactNode, SVGProps } from "react";
import type { IconName } from "./registry.js";

/** The three optical sizes (16-design-system-brief.md §5), each the `size.icon.<size>` token. */
export const ICON_SIZES = ["sm", "md", "lg"] as const;
export type IconSize = (typeof ICON_SIZES)[number];

/** What the grid fixes, so no caller can change it: the box, the paint, the stroke, the content. */
type GridAttribute =
  | "children"
  | "dangerouslySetInnerHTML"
  | "fill"
  | "focusable"
  | "height"
  | "ref"
  | "stroke"
  | "strokeLinecap"
  | "strokeLinejoin"
  | "strokeWidth"
  | "vectorEffect"
  | "viewBox"
  | "width"
  | "xmlns";

/** What every icon component takes: the SVG attributes the grid leaves open, and a size. */
export interface GlyphProps extends Omit<SVGProps<SVGSVGElement>, GridAttribute> {
  /** Optical size, `size.icon.sm|md|lg`; omitted, the semantic `size.icon` (an alias of md). */
  readonly size?: IconSize;
}

/** The token each size reads; `1em` keeps an icon text-sized where no theme bundle is loaded. */
const EXTENT: Readonly<Record<IconSize | "default", string>> = {
  sm: "var(--size-icon-sm, 1em)",
  md: "var(--size-icon-md, 1em)",
  lg: "var(--size-icon-lg, 1em)",
  default: "var(--size-icon, 1em)",
};

interface IconSvgProps extends GlyphProps {
  /** The registry name the generated module draws. */
  readonly icon: IconName;
  /** The module's geometry: path, circle, line, rect and the like, nothing else. */
  readonly children: ReactNode;
}

/** A name assistive technology can read: a blank one names nothing. */
const isName = (value: string | undefined): boolean => value !== undefined && value.trim() !== "";

/**
 * The icon grid (E05-T06) that every generated icon draws its geometry in: the 24-unit box at the
 * optical size, `currentColor` so the icon takes its context's semantic colour, and a 1.5px stroke
 * at every size (each shape's `vectorEffect="non-scaling-stroke"` keeps it from scaling with the
 * box). An icon is decorative (`aria-hidden`) unless it is named with a non-blank `aria-label` or
 * `aria-labelledby`, which makes it `role="img"` (brief §5, CMP-019). Both resolve after the
 * forwarded props, so a wrapper's `undefined` cannot undo them: an unnamed icon is always hidden,
 * and a named one is an image unless its caller sets `role` or `aria-hidden` itself.
 */
export function IconSvg({ icon, size, style, children, ...rest }: IconSvgProps): JSX.Element {
  const named = isName(rest["aria-label"]) || isName(rest["aria-labelledby"]);
  const extent = EXTENT[size ?? "default"];
  return (
    <svg
      {...rest}
      aria-hidden={named ? rest["aria-hidden"] : true}
      role={named ? (rest.role ?? "img") : rest.role}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      data-icon={icon}
      style={{ ...style, width: extent, height: extent }}
    >
      {children}
    </svg>
  );
}
