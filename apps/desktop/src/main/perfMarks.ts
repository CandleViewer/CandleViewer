/**
 * Shell cold-start stage marks of the Electron main process (E10-Q04, budget #10 in `06` §2).
 *
 * Each stage is one `performance.mark` on Node's global timeline, whose `timeOrigin` is process
 * start, so a mark's `startTime` is the stage's time from launch. A harness reads them with
 * `electronApp.evaluate(() => performance.getEntriesByType("mark"))`: no IPC channel, no preload.
 * The renderer's stages are apps/web's `shell/perfMarks.ts`, a separate name set (this app may not
 * import apps/web, and main ships without node_modules). Nothing but the standard API is added.
 */

/**
 * The main-process stage names, in the order a launch reaches them. The strings are verbatim
 * BQ-Q04-02 (proposed), suffixes and case included; a harness reads entries by exact name.
 */
export const MAIN_PERF_MARKS = {
  /** `index.ts` evaluated: the shell's own code starts running. */
  mainStart: "shell_main_start_ms",
  /** `app.whenReady()` resolved. */
  whenReady: "whenReady",
  /** The main window constructed and its page load issued. */
  windowCreated: "window_created",
  /** `ready-to-show`: the window's first paint, when it is shown. */
  firstPaint: "shell_first_paint_ms",
} as const;

export type MainPerfMark = (typeof MAIN_PERF_MARKS)[keyof typeof MAIN_PERF_MARKS];

/** The one call the marks need from `performance`. */
export interface MarkSink {
  mark(name: string): unknown;
}

/**
 * A marker that records each stage once per process: a second window or a repeated event never
 * moves a stage's time.
 */
export function createMainPerfMarks(sink: MarkSink): (stage: MainPerfMark) => void {
  const marked = new Set<MainPerfMark>();
  return (stage) => {
    if (marked.has(stage)) {
      return;
    }
    marked.add(stage);
    sink.mark(stage);
  };
}

/** Marks a main-process stage on the process's global timeline. */
export const markMainStage = createMainPerfMarks(performance);
