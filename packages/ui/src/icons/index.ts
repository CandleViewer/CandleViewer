// The icon set (E05-T06, 16-design-system-brief.md §5): the registry, the props every icon takes and
// one component per icon. Import the component an element draws (`CloseIcon`): each lives in its own
// module, so a bundle carries only the icons it imports.
export { ICONS } from "./registry.js";
export type { IconCategory, IconEntry, IconName, IconSource } from "./registry.js";
export { ICON_SIZES } from "./IconSvg.js";
export type { IconProps, IconSize } from "./IconSvg.js";
export * from "./generated/index.js";
