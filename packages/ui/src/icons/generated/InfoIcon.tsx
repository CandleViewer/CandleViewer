// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `info` icon: its meaning is its entry in `../registry.ts`. */
export function InfoIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="info">
      <circle cx="12" cy="12" r="10" vectorEffect="non-scaling-stroke" />
      <path d="M12 16v-4" vectorEffect="non-scaling-stroke" />
      <path d="M12 8h.01" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
