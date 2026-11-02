/**
 * Shell cold-start stage marks of the renderer (E10-Q04, budget #10 in `06` §2).
 *
 * Each stage is one `performance.mark`, so its `startTime` is the time from navigation start. A
 * harness reads them with `page.evaluate(() => performance.getEntriesByType("mark"))`. Shell
 * interactive (`shell_cold_start_ms`) is marked when the last of the other stages is reached. The
 * Electron main-process stages are apps/desktop's `main/perfMarks.ts`, a separate name set. Nothing
 * but the standard API is added: no global, no counter.
 */

/**
 * The renderer stage names; `interactive` is derived, never marked by a caller. The strings are
 * verbatim BQ-Q04-02 (proposed), suffixes included; a harness reads entries by exact name.
 */
export const SHELL_PERF_MARKS = {
  /** `/me`, preferences and keymap resolved and applied (bootstrap `ready`). */
  bootstrapReady: "shell_bootstrap_ms",
  /** The first live WS link of this page. */
  wsLive: "ws_live",
  /** The shell chrome and its first route element committed. */
  routeMounted: "route_mounted",
  /** Shell interactive: the latest of the three stages above. */
  interactive: "shell_cold_start_ms",
} as const;

export type ShellPerfStage = Exclude<
  (typeof SHELL_PERF_MARKS)[keyof typeof SHELL_PERF_MARKS],
  typeof SHELL_PERF_MARKS.interactive
>;

const STAGES_BEFORE_INTERACTIVE: readonly ShellPerfStage[] = [
  SHELL_PERF_MARKS.bootstrapReady,
  SHELL_PERF_MARKS.wsLive,
  SHELL_PERF_MARKS.routeMounted,
];

/** The one call the marks need from `performance`. */
export interface MarkSink {
  mark(name: string): unknown;
}

/**
 * A marker that records each stage once per page load (a re-login or a StrictMode re-run never
 * moves it) and marks shell interactive once, right after the last stage.
 */
export function createShellPerfMarks(sink: MarkSink): (stage: ShellPerfStage) => void {
  const marked = new Set<ShellPerfStage>();
  return (stage) => {
    if (marked.has(stage)) return;
    marked.add(stage);
    sink.mark(stage);
    if (marked.size === STAGES_BEFORE_INTERACTIVE.length) sink.mark(SHELL_PERF_MARKS.interactive);
  };
}

/** Marks a renderer stage on the page's timeline. */
export const markShellStage = createShellPerfMarks(performance);
