// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `close` icon: its meaning is its entry in `../registry.ts`. */
export function CloseIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="close">
      <path d="M18 6 6 18" vectorEffect="non-scaling-stroke" />
      <path d="m6 6 12 12" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
