import type { FunctionComponent, SVGProps } from "react";

/** One registry glyph (E05-T06): a 24-unit grid, a 1.5 stroke in `currentColor`, no fill. */
export type IconGlyph = FunctionComponent<SVGProps<SVGSVGElement>>;

const glyph = (name: string, d: string): IconGlyph => {
  const Glyph: IconGlyph = (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} {...props}>
      <path d={d} />
    </svg>
  );
  Glyph.displayName = `Icon(${name})`;
  return Glyph;
};

/** The icon registry, one glyph per `IconName`. This interface-first stub (#271) holds two
 * placeholder glyphs; E05-T06's set replaces them, and its names widen `IconName`. */
export const ICONS = {
  check: glyph("check", "M5 12l5 5L19 7"),
  lock: glyph("lock", "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z"),
} as const satisfies Record<string, IconGlyph>;

/** CMP-019's `name`: a registry key, never raw SVG in component code (16-design-system-brief.md §5). */
export type IconName = keyof typeof ICONS;
