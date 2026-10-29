import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DEFAULTS,
  compareToBaseline,
  comparability,
  findReport,
  metrics,
  renderSummary,
  run,
} from "../../../bench/matrix/ci-compare.mjs";
import { REPORT_SCHEMA } from "../../../bench/matrix/matrix-lib.mjs";

type Obj = Record<string, unknown>;

const frame = (scenario: string, p95: number): Obj => ({
  scenario,
  status: "ok",
  repetitions: 3,
  admissibleForAdrEvidence: true,
  p95,
});

function report(cells: Obj[], over: Obj = {}): Obj {
  return {
    schema: REPORT_SCHEMA,
    dryRun: false,
    runtime: "chromium",
    manifest: {
      schema: "cv-version-manifest/1",
      runtime: "chromium",
      machine: { cpu: "c", os: "linux", osBuild: "6", gpu: "g", driver: "d" },
      versions: { chromium: "156" },
      flagSet: { name: "pinned", flags: [] },
    },
    manifestIncomplete: [],
    seed: "1",
    fixture: { sha256: "f" },
    driverScriptSha256: "s",
    config: { reps: 3, durationMs: 20000, soakMs: 1, bars: 100000 },
    cells,
    runError: null,
    ...over,
  };
}

const B7 = {
  scenario: "B7",
  status: "ok",
  modes: { inline: { decodeP95Ms: 0.1 }, worker: { decodeP95Ms: 0.2 } },
};

function io() {
  const out = { log: [] as string[], error: [] as string[], appended: [] as string[] };
  return {
    out,
    io: {
      log: (s: string) => out.log.push(s),
      error: (s: string) => out.error.push(s),
      append: (_f: unknown, s: unknown) => void out.appended.push(String(s)),
    },
  };
}

function dirWith(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), "ci-compare-"));
  for (const [n, s] of Object.entries(files)) writeFileSync(join(dir, n), s);
  return dir;
}

describe("metrics and comparability", () => {
  it("collects frame p95, B7 decode per mode (never pooled) and B9 cold init", () => {
    const m = metrics(
      report([
        frame("B1", 1),
        B7,
        { scenario: "B9", status: "ok", coldInitToFirstFrameMs: 5 },
        { scenario: "B2", status: "not-runnable" },
      ]),
    );
    expect(m).toEqual({
      "B1 frame p95": 1,
      "B7 inline decode p95": 0.1,
      "B7 worker decode p95": 0.2,
      "B9 cold init": 5,
    });
  });
  it("names every like-for-like difference", () => {
    const a = report([]);
    const b = report([], {
      seed: "2",
      fixture: { sha256: "x" },
      driverScriptSha256: "y",
      config: { reps: 1 },
      manifest: { machine: { cpu: "c", cpuCount: 2 }, flagSet: { name: "z" } },
    });
    expect(comparability(a, a)).toEqual([]);
    const why = comparability(a, b).join("|");
    for (const w of ["fixture", "seed", "driver", "config.reps", "flag set", "hardware class"])
      expect(why).toContain(w);
  });
  it("ignores a hosted runner's CPU model string when cores, arch and GPU match", () => {
    const machine = { cpuCount: 4, arch: "x64", gpu: "SwiftShader" };
    const flagSet = { name: "pinned", flags: [] };
    const a = report([], { manifest: { machine: { ...machine, cpu: "model A" }, flagSet } });
    const b = report([], { manifest: { machine: { ...machine, cpu: "model B" }, flagSet } });
    expect(comparability(a, b)).toEqual([]);
  });
});

describe("compareToBaseline (recording only)", () => {
  const base = report([
    frame("B1", 2),
    frame("B2", 2),
    frame("B3", 2),
    frame("B4", 0.2),
    frame("B5", 2),
  ]);
  const cur = report([
    frame("B1", 2.5),
    frame("B2", 1.5),
    frame("B3", 2.05),
    frame("B4", 0.3),
    frame("B9x", 1),
  ]);
  const rows = Object.fromEntries(
    compareToBaseline(cur, base, DEFAULTS).map((r: { metric: string; status: string }) => [
      r.metric,
      r.status,
    ]),
  );
  it("flags a > 5 % slowdown of at least two timer ticks as a recorded regression", () => {
    expect(rows["B1 frame p95"]).toBe("REGRESSION (recorded)");
    expect(rows["B2 frame p95"]).toBe("improved");
    expect(rows["B3 frame p95"]).toBe("within threshold");
  });
  it("does not flag a one-tick delta however large in percent", () => {
    expect(rows["B4 frame p95"]).toBe("within threshold");
  });
  it("reports missing and new metrics, and the bootstrap case with no baseline", () => {
    expect(rows["B5 frame p95"]).toBe("missing in this run");
    expect(rows["B9x frame p95"]).toBe("new");
    expect(compareToBaseline(cur, null, DEFAULTS)[0]?.status).toBe("no baseline yet");
  });
  it("renders a summary that says it is not gating and names non-comparable runs", () => {
    const md = renderSummary({
      runtime: "chromium",
      file: "r.json",
      rows: compareToBaseline(cur, base, DEFAULTS),
      notComparable: ["seed differs"],
      baselineName: null,
      thresholds: DEFAULTS,
    });
    expect(md).toContain("recording only, not gating");
    expect(md).toContain("none committed yet");
    expect(md).toContain("**Not like-for-like with the baseline:** seed differs.");
    expect(md).toMatch(/\| B1 frame p95 \| 2\.00 \| 2\.50 \| 0\.50 \| 25\.0 \| REGRESSION/);
  });
});

describe("run(): a failure to run is surfaced, a regression is not", () => {
  it("prints usage without the required options", () => {
    expect(run([], io().io)).toBe(2);
  });
  it("fails when no report was produced, and says so in the summary", () => {
    const t = io();
    expect(
      run(["--runtime", "electron", "--report-dir", "/nonexistent-dir", "--summary", "s"], t.io),
    ).toBe(1);
    expect(t.out.error[0]).toMatch(/::error .*no electron report was produced/);
    expect(t.out.appended[0]).toContain("FAILED TO RUN");
    expect(findReport(dirWith({ "other.json": "{}" }), "electron")).toBeNull();
  });
  it("fails on invalid JSON, an invalid report and a harness run error", () => {
    const bad = (s: string) =>
      run(["--runtime", "chromium", "--report-dir", dirWith({ "chromium-1.json": s })], io().io);
    expect(bad("{")).toBe(1);
    expect(bad(JSON.stringify(report([frame("B1", 1)], { dryRun: true })))).toBe(1);
    const t = io();
    const dir = dirWith({
      "chromium-1.json": JSON.stringify(report([frame("B1", 1)], { runError: "timeout" })),
    });
    expect(run(["--runtime", "chromium", "--report-dir", dir], t.io)).toBe(1);
    expect(t.out.error[0]).toContain("harness run error: timeout");
  });
  it("exits 0 on a regression and with no baseline committed, and appends the summary", () => {
    const dir = dirWith({
      "chromium-1.json": JSON.stringify(report([frame("B1", 9)])),
      "chromium-2.json": JSON.stringify(report([frame("B1", 9)])),
      "base.json": JSON.stringify(report([frame("B1", 1)])),
    });
    const t = io();
    expect(
      run(
        [
          "--runtime",
          "chromium",
          "--report-dir",
          dir,
          "--baseline",
          join(dir, "base.json"),
          "--summary",
          "s",
        ],
        t.io,
      ),
    ).toBe(0);
    expect(t.out.appended[0]).toContain("REGRESSION (recorded)");
    expect(t.out.log[0]).toContain("`chromium-2.json`");
    const t2 = io();
    expect(
      run(
        ["--runtime", "chromium", "--report-dir", dir, "--baseline", join(dir, "absent.json")],
        t2.io,
      ),
    ).toBe(0);
    expect(t2.out.log[0]).toContain("no baseline yet");
  });
  it("fails on an invalid committed baseline", () => {
    const dir = dirWith({
      "chromium-1.json": JSON.stringify(report([frame("B1", 1)])),
      "base.json": JSON.stringify({ schema: "nope" }),
    });
    expect(
      run(
        ["--runtime", "chromium", "--report-dir", dir, "--baseline", join(dir, "base.json")],
        io().io,
      ),
    ).toBe(1);
  });
  it("fails visibly on a committed baseline that is not JSON", () => {
    const dir = dirWith({
      "chromium-1.json": JSON.stringify(report([frame("B1", 1)])),
      "base.json": "{ not json",
    });
    const t = io();
    expect(
      run(
        [
          "--runtime",
          "chromium",
          "--report-dir",
          dir,
          "--baseline",
          join(dir, "base.json"),
          "--summary",
          join(dir, "s.md"),
        ],
        t.io,
      ),
    ).toBe(1);
    expect(t.out.error[0]).toContain("base.json is not valid JSON");
    expect(t.out.appended[0]).toContain("FAILED TO RUN");
  });
});
