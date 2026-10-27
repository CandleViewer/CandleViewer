import type { JSX } from "react";
import { ICONS, type IconName } from "../icons/registry.js";

/** CMP-019's sizes, the `size.icon.sm|md|lg` tokens (12/16/20 px as shipped); `md` is `size.icon`. */
export type IconSize = "sm" | "md" | "lg";

/** CMP-019 Icon: decorative by default (`aria-hidden`); `decorative={false}` needs a `label` and
 * renders `role="img"` + `aria-label` (05-accessibility-standard.md §4). */
export type IconProps = { name: IconName; size?: IconSize } & (
  { decorative?: true; label?: never } | { decorative: false; label: string }
);

/** CMP-019, the interface-first contract (#271): E05-T06's slices keep this signature. */
export function Icon(props: IconProps): JSX.Element {
  const Glyph = ICONS[props.name];
  const box = `var(--size-icon-${props.size ?? "md"})`;
  const a11y =
    props.decorative === false
      ? { role: "img", "aria-label": props.label }
      : { "aria-hidden": true as const };
  return <Glyph data-cmp="CMP-019" style={{ width: box, height: box }} {...a11y} />;
}
