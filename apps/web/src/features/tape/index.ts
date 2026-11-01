// E22-S01 (#714): the tape feature's public surface. `TapePanel` (SCR-053) mounts behind
// `TAPE_ENABLED` only; E15 docks it beside SCR-030 (BQ-206). Rows bypass React (C-70).
export { TapePanel, type TapePanelProps } from "./view/TapePanel";
export type { TapeEvent } from "./view/tapeController";
export { TAPE_ENABLED } from "./flag";
