// Derived by hand from the Lucide glyph in registry.ts (E05 #271 slice 1): the generator,
// scripts/build-icons.mjs, joins in a later slice and will emit this module.
import type { JSX } from "react";
import { IconSvg, type GlyphProps } from "../IconSvg.js";

/** The `unlock` icon: its meaning is its entry in `../registry.ts`. */
export function UnlockIcon(props: GlyphProps): JSX.Element {
  return (
    <IconSvg {...props} icon="unlock">
      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" vectorEffect="non-scaling-stroke" />
      <path d="M7 11V7a5 5 0 0 1 9.9-1" vectorEffect="non-scaling-stroke" />
    </IconSvg>
  );
}
