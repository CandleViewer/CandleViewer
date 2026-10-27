import type { JSX } from "react";
import { ICON_COMPONENTS } from "./generated/components.js";
import type { IconSize } from "./IconSvg.js";
import type { IconName } from "./registry.js";

interface IconBase {
  /** The registry name of the glyph (`icons/registry.ts`). */
  readonly name: IconName;
  /** Optical size, the `size.icon.sm|md|lg` token; omitted, the semantic `size.icon` (md). */
  readonly size?: IconSize;
}

/** Decorative (the default): hidden from assistive technology, so it takes no label. */
interface DecorativeIcon extends IconBase {
  readonly decorative?: true;
  readonly label?: never;
}

/** Meaningful: `decorative={false}` names the icon, so `label` is required (`role="img"`). */
interface MeaningfulIcon extends IconBase {
  readonly decorative: false;
  readonly label: string;
}

export type IconProps = DecorativeIcon | MeaningfulIcon;

/**
 * CMP-019 Icon (16-design-system-brief.md §5): a registry glyph by name, at a token size, in
 * `currentColor`. Decorative by default (`aria-hidden`); `decorative={false}` with a `label`
 * makes it a named image. The `icon-label-required` lint rule backs the types for JavaScript
 * and spread callers.
 */
export function Icon({ name, size, decorative = true, label }: IconProps): JSX.Element {
  const Glyph = ICON_COMPONENTS[name];
  const sized = size === undefined ? {} : { size };
  return decorative ? <Glyph {...sized} /> : <Glyph {...sized} aria-label={label} />;
}
