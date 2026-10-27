import type { JSX } from "react";
import { ICON_COMPONENTS, ICON_FORMS } from "./generated/components.js";
import type { GlyphProps, IconSize } from "./IconSvg.js";
import type { IconName, MinimumSixteenName } from "./registry.js";

type Glyph = (props: GlyphProps) => JSX.Element;
/**
 * INTERNAL: each name's size forms by size, the reduced drawings a glyph has where its 24-unit
 * master closes up (E05-D02 §6 J24: `estimated` at `sm`). A form is never a name of its own.
 * Keyed to the `sm` token, 12 px as shipped: if slice 1 A10 (16 / 20 / 24 px) is approved, re-key
 * the forms and `IconSizeFor` to the 12 px size.
 */
const FORMS: Partial<Record<IconName, Partial<Record<IconSize, Glyph>>>> = ICON_FORMS;

/**
 * The optical sizes a glyph may be drawn at: all three, but never `sm` for a "16 px minimum" one
 * (`minimumPx: 16`; E05-D02 §6 J24). A name the caller leaves open, the whole `IconName` union as
 * in a map over the registry, keeps all three: the guard reads the names a call site fixes.
 */
export type IconSizeFor<N extends IconName> = N extends MinimumSixteenName
  ? Exclude<IconSize, "sm">
  : IconSize;

interface IconBase<N extends IconName> {
  /** The registry name of the glyph (`icons/registry.ts`). */
  readonly name: N;
  /** Optical size, the `size.icon.sm|md|lg` token; omitted, the semantic `size.icon` (md). */
  readonly size?: IconSizeFor<N>;
}

/** Decorative (the default): hidden from assistive technology, so it takes no label. */
interface DecorativeIcon<N extends IconName> extends IconBase<N> {
  readonly decorative?: true;
  readonly label?: never;
}

/** Meaningful: `decorative={false}` names the icon, so `label` is required (`role="img"`). */
interface MeaningfulIcon<N extends IconName> extends IconBase<N> {
  readonly decorative: false;
  readonly label: string;
}

/** Generic in the name, so a "16 px minimum" name refuses `sm`; unparameterised, any name. */
export type IconProps<N extends IconName = IconName> = DecorativeIcon<N> | MeaningfulIcon<N>;

/**
 * CMP-019 Icon (16-design-system-brief.md §5): a registry glyph by name, at a token size, in
 * `currentColor`. Decorative by default (`aria-hidden`); `decorative={false}` with a `label`
 * makes it a named image. The `icon-label-required` lint rule backs the types for JavaScript
 * and spread callers. At a size where the glyph has a reduced form, that form is drawn instead.
 */
export function Icon<N extends IconName>(props: IconProps<N>): JSX.Element {
  // The guard is the call site's: past it, any name draws at any size.
  const { name, size, decorative = true, label }: IconProps = props;
  const Glyph = (size === undefined ? undefined : FORMS[name]?.[size]) ?? ICON_COMPONENTS[name];
  const sized = size === undefined ? {} : { size };
  return decorative ? <Glyph {...sized} /> : <Glyph {...sized} aria-label={label} />;
}
