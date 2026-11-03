import { describe, expect, it } from "vitest";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  BASELINE_RE,
  PENDING_FILE,
  run,
  selectBaseline,
} from "../../../bench/engine/baseline-select.mjs";

const io = () => {
  const out = { log: [] as string[], error: [] as string[], file: "" };
  return {
    out,
    io: {
      log: (m: string) => void out.log.push(m),
      error: (m: string) => void out.error.push(m),
      append: (_f: unknown, m: unknown) => {
        out.file += String(m);
      },
    },
  };
};

describe("selectBaseline: one file per runner class, behind the pending switch", () => {
  it("records only while the switch is on and no baseline exists, enforced or not", () => {
    for (const enforce of [false, true])
      expect(selectBaseline([PENDING_FILE], "gpu", enforce)).toEqual({
        baseline: null,
        pending: true,
        error: null,
      });
  });
  it("fails closed once any baseline file exists next to the switch, on every route", () => {
    for (const mode of ["gpu", "fallback"])
      for (const enforce of [false, true]) {
        const r = selectBaseline([PENDING_FILE, "chromium-hosted.json"], mode, enforce);
        expect(r.error).toMatch(/PENDING\.md is still present.*fails closed/);
        expect(r.baseline).toBeNull();
      }
  });
  it("picks only the run's own runner class, never another class's file", () => {
    const both = ["chromium-gpu.json", "chromium-hosted.json"];
    expect(selectBaseline(both, "gpu", true).baseline).toBe("chromium-gpu.json");
    expect(selectBaseline(both, "fallback").baseline).toBe("chromium-hosted.json");
    expect(selectBaseline(["chromium-gpu.json"], "fallback")).toEqual({
      baseline: null,
      pending: false,
      error: null,
    });
  });
  it("fails an enforced run with neither the switch nor its class's baseline", () => {
    expect(selectBaseline(["chromium-hosted.json"], "gpu", true).error).toMatch(
      /no chromium-gpu\.json.*fails closed/,
    );
    expect(selectBaseline([], "gpu", true).error).toMatch(/fails closed/);
  });
  it("recognises any <runtime>-<class>.json as a baseline, so a mis-named one trips the switch", () => {
    for (const f of ["chromium-gpu.json", "chromium-hosted.json", "webgpu-gpu.json"])
      expect(BASELINE_RE.test(f)).toBe(true);
    for (const f of ["chromium-ubuntu.json", "Chromium-gpu.json", "gpu.json", "chromium-gpu.md"])
      expect(BASELINE_RE.test(f)).toBe(false);
    expect(selectBaseline([PENDING_FILE, "webgpu-gpu.json"], "gpu").error).toMatch(/fails closed/);
  });
  it("refuses an unknown route mode", () => {
    expect(selectBaseline([], "cpu").error).toMatch(/unknown route mode 'cpu'/);
    expect(selectBaseline([], "__proto__").error).toMatch(/unknown route mode/);
  });
});

describe("run(): the workflow step", () => {
  const dirWith = (...names: string[]) => {
    const d = mkdtempSync(join(tmpdir(), "cv-baseline-"));
    for (const n of names) writeFileSync(join(d, n), "{}");
    return d;
  };
  it("prints usage without --dir and --mode", () => {
    expect(run([], io().io)).toBe(2);
  });
  it("writes the step outputs while pending", () => {
    const t = io();
    expect(
      run(["--dir", dirWith(PENDING_FILE), "--mode", "gpu", "--enforce", "--output", "o"], t.io),
    ).toBe(0);
    expect(t.out.file).toBe("baseline=\npending=true\n");
  });
  it("exits 1 with CI-BEN-002 on a stale switch (the committed tree's guard)", () => {
    const t = io();
    const d = dirWith(PENDING_FILE, "chromium-gpu.json");
    expect(run(["--dir", d, "--mode", "fallback"], t.io)).toBe(1);
    expect(t.out.error[0]).toMatch(/^::error title=engine-bench baseline::CI-BEN-002: /);
  });
  it("hands the class's baseline path to ci-compare", () => {
    const t = io();
    const d = dirWith("chromium-gpu.json");
    expect(run(["--dir", d, "--mode", "gpu", "--enforce", "--output", "o"], t.io)).toBe(0);
    expect(t.out.file).toBe(`baseline=${join(d, "chromium-gpu.json")}\npending=false\n`);
  });
  it("the committed baseline directory is pending and passes on both routes", () => {
    const dir = fileURLToPath(new URL("../../../bench/engine/baselines", import.meta.url));
    for (const mode of ["gpu", "fallback"])
      expect(run(["--dir", dir, "--mode", mode, "--enforce"], io().io)).toBe(0);
  });
});
