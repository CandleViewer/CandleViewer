/**
 * Target-size accounting for the order-flow grids (E47-S02, #1358 BQ-09; `05` §3.4.7, WCAG 2.2 SC 2.5.8). The DOM
 * rows a consumer builds on the composite grid (the E21-S01 ladder) must be at least `size.target.min` (24 CSS px) tall and wide at default zoom;
 * the footprint cells the engine draws may fall below it at maximum zoom-out, which `05` §3.4.7 allows as the
 * essential exception only with the table alternative named as the compensating control.
 */

/** `size.target.min` in CSS px (packages/ui/tokens/primitives.tokens.json). */
export const TARGET_MIN_PX = 24;

export interface TargetSizeException {
  readonly id: string;
  readonly sc: "2.5.8";
  readonly basis: "essential";
  /** Why the other SC 2.5.8 exceptions are not the basis, so the record is not read as one of them. */
  readonly notApplicable: Readonly<Record<"spacing" | "equivalent", string>>;
  readonly component: string;
  readonly screens: readonly string[];
  readonly condition: string;
  /** The compensating control: the screen a user who cannot hit the small target uses instead. */
  readonly alternative: string;
  readonly source: string;
}

/** The recorded exceptions (mirrored in `15-component-catalogue.md` CMP-109). */
export const TARGET_SIZE_EXCEPTIONS: readonly TargetSizeException[] = [
  {
    id: "E47-S02-TSE-01",
    sc: "2.5.8",
    basis: "essential",
    component: "CMP-109",
    screens: ["SCR-030"],
    condition:
      "footprint cells below 24 CSS px at maximum chart zoom-out; the cell size at default zoom is not asserted " +
      "here (no layout in jsdom; the pixel measure is a carried row)",
    notApplicable: {
      spacing: "adjacent cells abut, so a 24 px circle around a small cell overlaps its neighbours",
      equivalent: "SCR-045 is another screen, not a control on the same page",
    },
    alternative: "SCR-045",
    source: "05-accessibility-standard.md §3.4.7",
  },
];
