// The volume pane's fixed figures (E12-S08, D06 §12). `VolumeOptions` (the `addVolume` option
// shape, BQ-11) is `src/api/types.ts`; the method and its worker command land with PR 2. No DOM.

/** D06 §12: the default `heightRatio`. */
export const VOLUME_HEIGHT_RATIO = 0.2;
/** D06 §12: scale 0 → the visible maximum. The pane block's margins are 0: no top margin. */
export const VOLUME_PANE_MARGINS = { top: 0, bottom: 0 } as const;
