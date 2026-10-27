// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `minus` icon: its meaning is its entry in `../registry.ts`. */
export function MinusIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="minus">
      <path d="M5 12h14" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
