// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `arrow-up` icon: its meaning is its entry in `../registry.ts`. */
export function ArrowUpIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="arrow-up">
      <path d="m5 12 7-7 7 7" vectorEffect="non-scaling-stroke" />
      <path d="M12 19V5" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
