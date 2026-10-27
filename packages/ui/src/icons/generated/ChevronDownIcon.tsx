// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `chevron-down` icon: its meaning is its entry in `../registry.ts`. */
export function ChevronDownIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="chevron-down">
      <path d="m6 9 6 6 6-6" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
