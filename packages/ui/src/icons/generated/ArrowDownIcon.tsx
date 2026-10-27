// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `arrow-down` icon: its meaning is its entry in `../registry.ts`. */
export function ArrowDownIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="arrow-down">
      <path d="M12 5v14" vectorEffect="non-scaling-stroke" />
      <path d="m19 12-7 7-7-7" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
