// The bench-mode stage marks (E11-T06, 06 §4.3 / §7.2): a `performance.mark` per boundary. The
// timeline is injected (C-2.16: no global read here); the names are built once at module load, so
// a marked frame builds no string. Production frames never reach this: the scheduler's `marks`
// is null unless the chart was opened in bench mode (`src/api/bench.ts`).
import {
  FRAME_STAGES,
  MARK_FRAME_START,
  MARK_LAYOUT_END,
  type StageMarker,
} from "./frame-scheduler.js";

/** The mark names by boundary index: the nine stage ends, then the frame start and layout end. */
export const STAGE_MARK_NAMES: readonly string[] = Object.freeze([
  ...FRAME_STAGES.map((s) => `cv.stage.${s}`),
  "cv.frame.start",
  "cv.stage.layout",
]);
export const FRAME_START_MARK = STAGE_MARK_NAMES[MARK_FRAME_START] as string;
export const LAYOUT_END_MARK = STAGE_MARK_NAMES[MARK_LAYOUT_END] as string;

/** The `Performance` member used (typed structurally: the core program has no DOM lib). */
export interface PerformanceTimeline {
  mark(name: string): unknown;
}

/** A `StageMarker` writing to `timeline`. */
export function performanceStageMarker(timeline: PerformanceTimeline): StageMarker {
  return {
    mark(boundary: number): void {
      timeline.mark(STAGE_MARK_NAMES[boundary] as string);
    },
  };
}
