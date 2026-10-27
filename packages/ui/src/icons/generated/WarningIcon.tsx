// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `warning` icon: its meaning is its entry in `../registry.ts`. */
export function WarningIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="warning">
      <path
        d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"
        vectorEffect="non-scaling-stroke"
      />
      <path d="M12 9v4" vectorEffect="non-scaling-stroke" />
      <path d="M12 17h.01" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
