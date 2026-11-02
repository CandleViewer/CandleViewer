import { describe, expect, it } from "vitest";
import { MAIN_PERF_MARKS, createMainPerfMarks } from "../src/main/perfMarks";

describe("createMainPerfMarks", () => {
  it("uses the agreed names", () => {
    expect(MAIN_PERF_MARKS).toEqual({
      mainStart: "shell_main_start_ms",
      whenReady: "whenReady",
      windowCreated: "window_created",
      firstPaint: "shell_first_paint_ms",
    });
  });

  it("marks each stage once: a second window or a repeated event moves nothing", () => {
    const names: string[] = [];
    const mark = createMainPerfMarks({ mark: (name) => names.push(name) });
    mark("shell_main_start_ms");
    mark("whenReady");
    mark("window_created");
    mark("window_created");
    mark("shell_first_paint_ms");
    mark("shell_first_paint_ms");
    expect(names).toEqual([
      "shell_main_start_ms",
      "whenReady",
      "window_created",
      "shell_first_paint_ms",
    ]);
  });
});
