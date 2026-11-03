import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  COMMENT_NAMES,
  COMMENT_STATUSES,
  DEFAULTS,
  absoluteGates,
  compareToBaseline,
  comparability,
  findReport,
  metrics,
  numbersOf,
  renderSummary,
  run,
  spreads,
  unitOf,
} from "../../../bench/matrix/ci-compare.mjs";
import {
  ENGINE_SCENARIO_IDS,
  STUB_SCENARIOS,
  stubCell,
} from "../../../bench/engine/engine-lib.mjs";
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
  const out = {
    log: [] as string[],
    error: [] as string[],
    appended: [] as string[],
    written: [] as string[],
  };
  return {
    out,
    io: {
      log: (s: string) => out.log.push(s),
      error: (s: string) => out.error.push(s),
      append: (_f: unknown, s: unknown) => void out.appended.push(String(s)),
      write: (_f: unknown, s: unknown) => void out.written.push(String(s)),
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

// E03-T14: `--enforce` (GPU mode) turns a like-for-like regression above 5 % into CI-BEN-001; the
// recording mode (hosted fallback) never does.
describe("run(): --enforce", () => {
  // 1.00 -> 1.05 is exactly 5 % (not above it); 1.00 -> 1.06 is 6 %. Both clear the 0.2 ms floor
  // only when scaled, so the frames are in the tens of ms.
  const at = (ms: number, over: Obj = {}) => JSON.stringify(report([frame("B1", ms)], over));
  const args = (dir: string, ...extra: string[]) => [
    "--runtime",
    "chromium",
    "--report-dir",
    dir,
    "--baseline",
    join(dir, "base.json"),
    ...extra,
  ];

  it("exits 1 with CI-BEN-001 above 5 % and 0 at exactly 5 %", () => {
    const over = dirWith({ "chromium-1.json": at(10.6), "base.json": at(10) });
    const t = io();
    expect(run(args(over, "--enforce"), t.io)).toBe(1);
    expect(t.out.error.join("\n")).toMatch(/CI-BEN-001.*B1 frame p95/);
    expect(t.out.log[0]).toContain("REGRESSION (enforced)");
    const at5 = dirWith({ "chromium-1.json": at(10.5), "base.json": at(10) });
    expect(run(args(at5, "--enforce"), io().io)).toBe(0);
  });
  it("records the same regression without failing when --enforce is off", () => {
    const over = dirWith({ "chromium-1.json": at(10.6), "base.json": at(10) });
    const t = io();
    expect(run(args(over), t.io)).toBe(0);
    expect(t.out.log[0]).toContain("REGRESSION (recorded)");
  });
  it("does not fail a 5-rep run against a 3-rep baseline: not like-for-like, reported", () => {
    const reps = (n: number) => ({
      config: { reps: n, durationMs: 20000, soakMs: 1, bars: 100000 },
    });
    const dir = dirWith({ "chromium-1.json": at(20, reps(5)), "base.json": at(10, reps(3)) });
    for (const flags of [["--enforce"], []]) {
      const t = io();
      expect(run(args(dir, ...flags), t.io)).toBe(0);
      expect(t.out.log[0]).toContain("config.reps differs");
    }
    const t = io();
    run(args(dir, "--enforce"), t.io);
    expect(t.out.log.join("\n")).toMatch(/::warning .*CI-BEN-002.*not enforced/);
  });
  it("does not enforce with no baseline, and a missing report still exits 1 (CI-BEN-002)", () => {
    const dir = dirWith({ "chromium-1.json": at(99) });
    expect(run(["--runtime", "chromium", "--report-dir", dir, "--enforce"], io().io)).toBe(0);
    const t = io();
    expect(run(["--runtime", "chromium", "--report-dir", "/nonexistent", "--enforce"], t.io)).toBe(
      1,
    );
    expect(t.out.error[0]).toContain("CI-BEN-002");
  });
  it("compares draw calls too", () => {
    const withDraws = (n: number) => JSON.stringify(report([{ ...frame("B5", 10), drawCalls: n }]));
    const dir = dirWith({ "chromium-1.json": withDraws(43), "base.json": withDraws(40) });
    const t = io();
    expect(run(args(dir, "--enforce"), t.io)).toBe(1);
    expect(t.out.error.join("\n")).toContain("B5 draw calls");
  });
});

// E11-T06: the real-engine report (`config.page: "engine"`): frame time, draw calls and memory each
// fail above 5 % on the median of five p95s, the floor binds only under 4 ms, 26 §13's gates
// apply, and the published spread never fails.
describe("E11-T06: the real-engine gate", () => {
  const ENGINE = {
    config: { reps: 5, durationMs: 20000, soakMs: 1, bars: 100000, page: "engine" },
  };
  const cell = (scenario: string, p95: number, over: Obj = {}): Obj => ({
    ...frame(scenario, p95),
    repetitions: 5,
    p95PerRep: [p95, p95, p95, p95, p95],
    spreadPct: 0,
    ...over,
  });
  const eng = (cells: Obj[]) =>
    JSON.stringify(report([...cells, ...STUB_SCENARIOS.map((id: string) => stubCell(id))], ENGINE));
  const args = (dir: string, ...extra: string[]) => [
    "--runtime",
    "chromium",
    "--report-dir",
    dir,
    "--baseline",
    join(dir, "base.json"),
    ...extra,
  ];
  const verdict = (cur: Obj[], base: Obj[], ...flags: string[]) => {
    const dir = dirWith({ "chromium-1.json": eng(cur), "base.json": eng(base) });
    const t = io();
    return { code: run(args(dir, ...flags), t.io), t };
  };

  it("a synthetic 10 % frame-time regression trips the enforced gate (B5 15.0 -> 16.5 ms)", () => {
    const { code, t } = verdict([cell("B5", 16.5)], [cell("B5", 15)], "--enforce");
    expect(code).toBe(1);
    expect(t.out.error.join("\n")).toMatch(/CI-BEN-001.*B5 frame p95/);
  });
  it("a 4 % regression passes (B5 15.0 -> 15.6 ms)", () => {
    expect(verdict([cell("B5", 15.6)], [cell("B5", 15)], "--enforce").code).toBe(0);
  });
  it("gates on the median of the five p95s, not the cell's own p95 field", () => {
    const noisy = cell("B5", 15, { p95: 99, p95PerRep: [14, 15, 15, 15, 40] });
    expect(verdict([noisy], [cell("B5", 15)], "--enforce").code).toBe(0);
  });
  it("binds the 0.2 ms floor only below 4 ms (PROPOSED)", () => {
    const opts = { ...DEFAULTS, minDeltaMs: 1 };
    const status = (b: number, c: number) =>
      compareToBaseline(report([cell("B1", c)], ENGINE), report([cell("B1", b)], ENGINE), opts)[0]
        ?.status;
    expect(status(2, 2.6)).toBe("within threshold"); // 30 %, but under the (1 ms) floor
    expect(status(10, 10.6)).toBe("REGRESSION (recorded)"); // 6 % at >= 4 ms: no floor
    expect(DEFAULTS.floorBelowMs).toBe(4);
  });
  it("fails draw calls and memory above 5 % too, with no floor on either", () => {
    expect(unitOf("B5 draw calls")).toBe("count");
    expect(unitOf("B5 memory MB")).toBe("MB");
    expect(unitOf("B5 frame p95")).toBe("ms");
    const draws = verdict(
      [cell("B5", 15, { drawCalls: 43 })],
      [cell("B5", 15, { drawCalls: 40 })],
      "--enforce",
    );
    expect(draws.code).toBe(1);
    expect(draws.t.out.error.join("\n")).toContain("B5 draw calls");
    const mem = verdict(
      [cell("B1", 5, { memoryMb: 1.1 })],
      [cell("B1", 5, { memoryMb: 1 })],
      "--enforce",
    );
    expect(mem.code).toBe(1); // 0.1 MB, 10 %: memory is never floored
    expect(mem.t.out.error.join("\n")).toContain("B1 memory MB");
    const ok = verdict(
      [cell("B2", 5, { memoryMb: 104, drawCalls: 41 })],
      [cell("B2", 5, { memoryMb: 100, drawCalls: 40 })],
      "--enforce",
    );
    expect(ok.code).toBe(0);
  });
  it("applies 26 §13's absolute gates: recorded on a hosted run, failing under --enforce", () => {
    const over = [cell("B1", 13), cell("B9", 0, { coldInitToFirstFrameMs: 500 })];
    expect(verdict(over, over).code).toBe(0);
    const enforced = verdict(over, over, "--enforce");
    expect(enforced.code).toBe(1);
    expect(enforced.t.out.error.join("\n")).toMatch(
      /CI-BEN-001: over the 26 §13 gate: B1 frame p95 <= 12 ms/,
    );
    const gates = absoluteGates(report(over, ENGINE), false);
    expect(gates.map((g: Obj) => g["status"])).toEqual([
      "OVER GATE (recorded)",
      "not measured",
      "within gate",
      "not measured",
    ]);
    expect(absoluteGates(report(over), true)).toEqual([]); // a matrix report: no 26 §13 gates
  });
  it("publishes the spread and never fails on it, and lists the stubs by owner Epic", () => {
    const wild = cell("B1", 5, { p95PerRep: [1, 5, 5, 5, 9], spreadPct: 160 });
    const { code, t } = verdict([wild], [wild], "--enforce");
    expect(code).toBe(0);
    expect(spreads(report([wild], ENGINE))).toEqual([{ scenario: "B1", reps: 5, spreadPct: 160 }]);
    const md = t.out.log[0] ?? "";
    expect(md).toMatch(/\| B1 \| 5 \| 160\.0 \|/);
    expect(md).toContain("**Not implemented (stubs):** B3 (E18), B4 (E21), B7 (E17), B8 (E14).");
  });
  it("does not floor a baseline of exactly 4.0 ms; floors one just under it", () => {
    const opts = { ...DEFAULTS, minDeltaMs: 1 };
    const status = (b: number, c: number) =>
      compareToBaseline(report([cell("B1", c)], ENGINE), report([cell("B1", b)], ENGINE), opts)[0]
        ?.status;
    expect(status(4, 4.3)).toBe("REGRESSION (recorded)"); // 7.5 % at exactly 4 ms: not floored
    expect(status(3.99, 4.3)).toBe("within threshold"); // under 4 ms: the 1 ms floor binds
  });
  it("fails an enforced run on a NaN p95 the baseline has (M1)", () => {
    // In memory: a NaN p95 is never "within threshold".
    const direct = compareToBaseline(
      report([cell("B6", NaN, { p95PerRep: undefined })], ENGINE),
      report([cell("B6", 10)], ENGINE),
      { ...DEFAULTS, enforce: true },
    );
    expect(direct[0]).toMatchObject({ metric: "B6 frame p95", status: "MISSING (enforced)" });
    // Through JSON a NaN rep p95 becomes null: the median is not taken over the rest.
    const nan = cell("B6", 10, { p95PerRep: [10, NaN, 10, 10, 10] });
    const { code, t } = verdict([nan], [cell("B6", 10)], "--enforce");
    expect(code).toBe(1);
    expect(t.out.log[0]).toContain("| B6 frame p95 | 10.00 | - | - | - | MISSING (enforced) |");
    expect(t.out.error.join("\n")).toMatch(/CI-BEN-001: missing or non-finite.*B6 frame p95/);
    expect(verdict([nan], [cell("B6", 10)]).code).toBe(0); // recorded only without --enforce
  });
  it("fails an enforced run when a baseline metric is missing (M1)", () => {
    const { code, t } = verdict(
      [cell("B1", 5)],
      [cell("B1", 5, { drawCalls: 8 }), cell("B2", 5)],
      "--enforce",
    );
    expect(code).toBe(1);
    expect(t.out.error.join("\n")).toMatch(/missing or non-finite.*B1 draw calls, B2 frame p95/);
  });
  it("fails an enforced run when a scenario became not runnable (M1)", () => {
    const broken = { scenario: "B1", status: "not-runnable", reason: "TypeError: boom" };
    const { code, t } = verdict([broken], [cell("B1", 5)], "--enforce");
    expect(code).toBe(1);
    expect(t.out.log[0]).toContain("**Not runnable — NOT RUN (enforced):** B1");
    expect(verdict([broken], [cell("B1", 5)]).code).toBe(0);
    // Not run is never a pass under --enforce, even when the baseline never had a figure (m-1).
    const both = verdict([broken], [broken], "--enforce");
    expect(both.code).toBe(1);
    expect(both.t.out.error.join("\n")).toMatch(/CI-BEN-001: not run: B1/);
    expect(both.t.out.log[0]).toContain("NOT RUN (enforced)");
  });
  it("fails a not-runnable B1 under --enforce with no baseline at all (m-1)", () => {
    const broken = { scenario: "B1", status: "not-runnable", reason: "rep 1 recorded no frame" };
    const dir = dirWith({ "chromium-1.json": eng([broken, cell("B2", 5)]) });
    const t = io();
    expect(run(["--runtime", "chromium", "--report-dir", dir, "--enforce"], t.io)).toBe(1);
    expect(t.out.error.join("\n")).toMatch(/CI-BEN-001: not run: B1/);
    expect(run(["--runtime", "chromium", "--report-dir", dir], io().io)).toBe(0); // recorded
  });
  it("never reads a zero frame-time baseline as within threshold (Major)", () => {
    const rows = compareToBaseline(
      JSON.parse(eng([cell("B1", 9)])),
      JSON.parse(eng([cell("B1", 0)])),
      { ...DEFAULTS, enforce: true },
    );
    expect(rows.find((r) => r.metric === "B1 frame p95")).toMatchObject({
      status: "ZERO BASELINE (enforced)",
    });
    const { code, t } = verdict([cell("B1", 9)], [cell("B1", 0)], "--enforce");
    expect(code).toBe(1);
    expect(t.out.error.join("\n")).toMatch(/CI-BEN-001: zero baseline: B1 frame p95/);
    const rec = verdict([cell("B1", 9)], [cell("B1", 0)]);
    expect(rec.code).toBe(0);
    expect(rec.t.out.log[0]).toContain("zero baseline (not compared)");
  });
  it("reads a zero frame time in this run as missing, never as a pass (Major)", () => {
    const { code, t } = verdict([cell("B1", 0)], [cell("B1", 5)], "--enforce");
    expect(code).toBe(1);
    expect(t.out.log[0]).toContain("| B1 frame p95 | 5.00 | - | - | - | MISSING (enforced) |");
  });
  const imprecise = cell("B6", 10, {
    memoryPrecision: "imprecise",
    memoryMb: null,
    memoryScope: "main thread only; the render worker's heap is not counted",
  });
  it("fails an enforced run whose memory is imprecise against a precise baseline (PR-2)", () => {
    const { code, t } = verdict([imprecise], [cell("B6", 10, { memoryMb: 50 })], "--enforce");
    expect(code).toBe(1);
    expect(t.out.error.join("\n")).toMatch(/CI-BEN-001: missing or non-finite.*B6 memory MB/);
  });
  it("records an imprecise memory figure without failing, and says so (M3)", () => {
    expect(verdict([imprecise], [imprecise], "--enforce").code).toBe(0);
    const { code, t } = verdict([imprecise], [cell("B6", 10, { memoryMb: 50 })]);
    expect(code).toBe(0);
    const md = t.out.log[0] ?? "";
    expect(md).toContain("imprecise memory (not compared)");
    expect(md).toContain("B6 memory: imprecise (quantised heap), recorded and not compared.");
    expect(md).toContain("B6 memory: main thread only; the render worker's heap is not counted.");
  });
  it("refuses to enforce an engine report on fewer than five reps (m3)", () => {
    const one = { config: { ...ENGINE.config, reps: 1 } };
    const r = (p95: number) => JSON.stringify(report([cell("B1", p95)], one));
    const dir = dirWith({ "chromium-1.json": r(5), "base.json": r(5) });
    const t = io();
    expect(run(args(dir, "--enforce"), t.io)).toBe(1);
    expect(t.out.error[0]).toMatch(/CI-BEN-002: .*1 reps; an enforced engine run needs 5/);
    expect(run(args(dir), io().io)).toBe(0);
  });
  it("labels B5 and B6 partial in the gates and the summary (M2)", () => {
    const { t } = verdict([cell("B5", 10, { partial: "partial: candles only" })], []);
    const md = t.out.log[0] ?? "";
    expect(md).toContain("B5 frame p95 <= 16.7 ms (26 §13) [partial]");
    expect(md).toContain("**B5 partial: candles only.**");
  });
  it("writes the comment job's numbers with --json: names, finite numbers, statuses only", () => {
    const dir = dirWith({
      "chromium-1.json": eng([cell("B1", 6, { p95PerRep: [6, 6, NaN, 6, 6] })]),
      "base.json": eng([cell("B1", 5)]),
    });
    const t = io();
    run(args(dir, "--json", "numbers.json"), t.io);
    // Written, never appended: a stale file from an earlier run is replaced.
    expect(t.out.written).toHaveLength(1);
    expect(t.out.appended.join("")).not.toContain("cv-engine-bench-numbers/1");
    const out = JSON.parse(t.out.written[0] ?? "{}");
    expect(out.schema).toBe("cv-engine-bench-numbers/1");
    expect(out.enforce).toBe(false);
    expect(out.rows).toContainEqual({
      metric: "B1 frame p95",
      baseline: 5,
      current: null,
      deltaPct: null,
      status: "missing in this run",
    });
    expect(Object.keys(out.gates[0]).sort()).toEqual(["metric", "status", "value"]);
    const staged = report([cell("B1", 6, { spreadPct: 2, worstStage: "paneRedraw" })], ENGINE);
    const bogus = report([cell("B1", 6, { spreadPct: 2, worstStage: "<img src=x>" })], ENGINE);
    expect(numbersOf([], [], staged, false).spreads).toEqual([
      { scenario: "B1", spreadPct: 2, worstStage: "paneRedraw" },
    ]);
    expect(numbersOf([], [], bogus, false).spreads[0]?.worstStage).toBeNull();
    expect(numbersOf([], [], report([]), true)).toEqual({
      schema: "cv-engine-bench-numbers/1",
      enforce: true,
      rows: [],
      gates: [],
      spreads: [],
    });
  });
  it("never compares an engine report with a matrix one", () => {
    const why = comparability(report([], ENGINE), report([]));
    expect(why).toContain("config.page differs");
  });
});

// E11-T06 PR-2 lens Minor 1 (and the PR-1 BQ-13 carry): the comment job renders only names of a
// closed set, fixed statuses and finite numbers; its workflow carries the same lists verbatim.
describe("E11-T06: the comment job's closed allow-lists", () => {
  const ENGINE = {
    config: { reps: 5, durationMs: 20000, soakMs: 1, bars: 100000, page: "engine" },
  };
  const WORKFLOW = readFileSync(
    fileURLToPath(
      new URL("../../../../../.github/workflows/engine-bench-comment.yml", import.meta.url),
    ),
    "utf8",
  );
  const setIn = (name: string): string[] => {
    const m = new RegExp(`const ${name} = new Set\\(\\[([\\s\\S]*?)\\]\\);`).exec(WORKFLOW);
    return JSON.parse(`[${m?.[1] ?? ""}]`) as string[];
  };
  // Every figure and every gate field set, on every scenario id, plus B7's two modes.
  const full = report(
    ENGINE_SCENARIO_IDS.map((id: string) =>
      id === "B7"
        ? { ...B7 }
        : {
            ...frame(id, 20),
            p95PerRep: [20, 20, 20, 20, 20],
            drawCalls: 50,
            memoryMb: 100,
            peakMemoryMb: 700,
            lodChanges: 9,
            workerCpuPct: 80,
            coldInitToFirstFrameMs: 1000,
            atlasFromCacheMs: 9,
            growthPct: 9,
            partial: "partial: <img src=x> free text",
            memoryScope: "free text www.example.com",
            memoryLimit: 1234,
          },
    ),
    ENGINE,
  );

  it("names every metric and gate ci-compare emits, and nothing from the run", () => {
    const rows = compareToBaseline(full, full, { ...DEFAULTS, enforce: true });
    const gates = [...absoluteGates(full, false), ...absoluteGates(full, true)];
    expect(rows.length).toBeGreaterThan(0);
    expect(gates.length).toBeGreaterThan(0);
    for (const n of [...rows.map((r) => r.metric), ...gates.map((g) => g.metric)])
      expect(COMMENT_NAMES).toContain(n);
    for (const st of [...rows.map((r) => r.status), ...gates.map((g) => g.status)])
      expect(COMMENT_STATUSES).toContain(st);
    // partial, memoryScope and memoryLimit never reach the numbers file as text.
    const json = JSON.stringify(numbersOf(rows, gates, full, true));
    expect(json).not.toMatch(/img|free text|example|1234/);
  });
  it("keeps the workflow's lists identical to the exported ones", () => {
    expect(setIn("NAMES")).toEqual([...COMMENT_NAMES]);
    expect(setIn("STATUS")).toEqual([...COMMENT_STATUSES]);
    expect(WORKFLOW).not.toMatch(/const NAME = \//);
  });
});
