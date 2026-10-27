// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `check` icon: its meaning is its entry in `../registry.ts`. */
export function CheckIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="check">
      <path d="M20 6 9 17l-5-5" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
