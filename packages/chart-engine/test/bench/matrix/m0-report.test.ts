import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_REPORT,
  DEFAULT_RESULTS,
  assignRoles,
  driftedBlocks,
  loadResults,
  ms,
  redact,
  renderBlocks,
  run,
  sanitiseManifest,
  soakMemory,
  spliceBlocks,
  table,
  triggerFires,
} from "../../../bench/matrix/m0-report.mjs";
import { REPORT_SCHEMA, validateReport } from "../../../bench/matrix/matrix-lib.mjs";

type Obj = Record<string, unknown>;

function frame(scenario: string, p95: number, reps = 3): Obj {
  return {
    scenario,
    status: "ok",
    repetitions: reps,
    admissibleForAdrEvidence: scenario === "B10" ? true : reps >= 3,
    p50: p95 / 2,
    p95,
    p99: p95 * 2,
    p95PerRep: Array.from({ length: reps }, () => p95),
    outliers33: 0,
    maxMs: p95 * 3,
    drawCalls: 4,
    mirrorP95Ms: 0.1,
    texUploadMedianMs: scenario === "B4" ? 0 : null,
    soak:
      scenario === "B10"
        ? [0, 1, 2].map((bucket) => ({ bucket, frames: 10, p95, outliers33: 0 }))
        : null,
    modelledStageMs: scenario === "B5" ? { inputHandling: 0.5, candleGeometry: 2.5 } : null,
  };
}

function report(runtime: string, cells: Obj[], over: Obj = {}): Obj {
  return {
    schema: REPORT_SCHEMA,
    dryRun: false,
    runtime,
    timestamp: "2026-01-01T00:00:00.000Z",
    manifest: {
      schema: "cv-version-manifest/1",
      runtime,
      machine: {
        cpu: "cpu",
        cpuCount: 4,
        totalMemMb: 8000,
        os: "linux",
        osBuild: "6.0",
        arch: "x64",
        gpu: "gpu",
        driver: "1.0",
        hostname: "secret-host",
        homedir: "/home/someone",
      },
      versions: {
        node: "20",
        electron: runtime === "electron" ? "45" : null,
        chromium: "156",
        playwright: null,
        tauri: null,
        webview2: null,
      },
      flagSet: { name: "tuned", flags: ["--x"] },
    },
    manifestIncomplete: [],
    seed: "1",
    fixture: { sha256: "abc", barCount: 100 },
    driverScriptSha256: "d",
    config: { reps: 3, durationMs: 1000, soakMs: 300_000, bars: 100 },
    capabilities: { webgl2: true, renderer: "ANGLE (software)" },
    cells,
    residentMemoryMb: { shellMetrics: [], peakMb: null },
    runError: null,
    ...over,
  };
}

const ALL = ["B1", "B2", "B3", "B4", "B5"].map((s) => frame(s, 1));
const B7 = {
  scenario: "B7",
  status: "ok",
  modes: {
    inline: { repetitions: 3, decodeP95Ms: 0, drops: 0, duplicates: 0, pass: true },
    worker: {
      repetitions: 3,
      decodeP95Ms: 0.1,
      drops: 0,
      duplicates: 0,
      pass: true,
      offscreenWebgl2InWorker: true,
    },
  },
};
const B9 = { scenario: "B9", status: "ok", repetitions: 3, coldInitToFirstFrameMs: 5 };

function writeDir(reports: Record<string, Obj>): string {
  const dir = mkdtempSync(join(tmpdir(), "m0-report-"));
  for (const [name, r] of Object.entries(reports))
    writeFileSync(join(dir, name), JSON.stringify(r));
  return dir;
}

const NAMES = [
  "verdict",
  "budget",
  "results",
  "b5",
  "trigger",
  "stages",
  "b10",
  "noise",
  "flagsets",
  "manifest",
];
const skeleton = (body = "") =>
  "# r\n\nprose\n\n" +
  NAMES.map((n) => `<!-- m0-report:begin ${n} -->\n${body}<!-- m0-report:end -->`).join("\n\n") +
  "\n";

describe("validateReport (shared with the CI comparison)", () => {
  it("accepts a complete report", () => {
    expect(validateReport(report("chromium", ALL))).toEqual([]);
  });
  it("fails on a missing machine descriptor field", () => {
    const r = report("chromium", ALL);
    (r["manifest"] as { machine: Obj }).machine["gpu"] = "unknown-gpu";
    expect(validateReport(r).join()).toMatch(/machine descriptor incomplete.*gpu/);
  });
  it("fails on a missing manifest, a missing runtime version and a marked-incomplete manifest", () => {
    expect(validateReport(report("chromium", ALL, { manifest: null })).join()).toMatch(
      /version manifest missing/,
    );
    const r = report("electron", ALL);
    (r["manifest"] as { versions: Obj }).versions["electron"] = null;
    expect(validateReport(r)).toContain("missing version: electron");
    expect(validateReport(report("chromium", ALL, { manifestIncomplete: ["x"] })).join()).toMatch(
      /marked incomplete: x/,
    );
  });
  it("fails on a frame cell under 3 repetitions, but not on the once-only B10 soak", () => {
    const bad = validateReport(report("chromium", [frame("B1", 1, 2), frame("B10", 1, 1)]));
    expect(bad).toEqual(["B1: inadmissible, 2 repetition(s) < 3"]);
  });
  it("fails on a harness-inadmissible cell and a cell without p95", () => {
    const c = { ...frame("B2", 1), admissibleForAdrEvidence: false, p95: undefined };
    expect(validateReport(report("chromium", [c]))).toEqual([
      "B2: marked inadmissible by the harness",
      "B2: no p95",
    ]);
  });
  it("fails on schema, dry run, runtime, fixture and empty cells", () => {
    const p = validateReport(
      report("nope", [], { schema: "x/1", dryRun: true, fixture: null }),
    ).join("|");
    for (const want of ["schema is x/1", "dry-run", "unknown runtime", "fixture", "no scenario"])
      expect(p).toContain(want);
    expect(validateReport(null)).toEqual(["not a JSON object"]);
  });
});

describe("strip rule: hardware class only", () => {
  it("drops every field outside the allow-list (hostname, home directory)", () => {
    const m = sanitiseManifest((report("electron", ALL) as { manifest: unknown }).manifest);
    expect(Object.keys(m.machine)).not.toContain("hostname");
    expect(JSON.stringify(m)).not.toMatch(/secret-host|someone/);
    expect(m.machine["cpuCount"]).toBe(4);
  });
  it("redacts absolute paths in any string that is kept", () => {
    expect(redact("gpu at C:\\Users\\alice\\x.dll ok")).toBe("gpu at <path> ok");
    expect(redact("see /home/bob/run.log")).toBe("see <path>");
    expect(redact("--x=/Users/carol/p")).toBe("--x=<path>");
    expect(redact("\\\\host\\share\\f and file:///tmp/a")).toBe("<path> and <path>");
    expect(redact("--use-gl=angle")).toBe("--use-gl=angle");
    const m = sanitiseManifest({ machine: { gpu: "/root/gpu" }, flagSet: { flags: ["/tmp/x"] } });
    expect(m.machine["gpu"]).toBe("<path>");
    expect(m.flagSet.flags).toEqual(["<path>"]);
    expect(m.flagSet.name).toBe("unspecified");
  });
  it("renders no path, user or host name from the committed reports", () => {
    const md = Object.values(renderBlocks(loadResults(DEFAULT_RESULTS))).join("\n");
    expect(md).not.toMatch(/[A-Za-z]:\\|\/home\/|\/Users\/|secret/);
  });
});

describe("rendering", () => {
  it("renders the committed matrix figures (sample rows traced to the raw JSON)", () => {
    const b = renderBlocks(loadResults(DEFAULT_RESULTS));
    expect(b.results).toMatch(/\| B5 +\| p95 ≤ 16\.7 ms \| 3 +\| 0\.20 \| 0\.50 \| 81\.60/);
    expect(b.b5).toMatch(/\| Electron +\| 0\.20 .*\| 0\.50 .*\| 15 .*PASS/);
    expect(b.trigger).toMatch(/Trigger half 1 .*does not fire/);
    expect(b.b10).toMatch(/1003; missed — inconclusive on this class/);
    expect(b.b10).toMatch(/747 to 859 = \+15\.0 %/);
    expect(b.noise).toMatch(/E06-Q01 band \(0\.46 %\): \*\*yes\*\*/);
    expect(b.flagsets).toContain("`electron-default` (ms)");
    expect(b.b10).toMatch(/955 to 990 = \+3\.7 %; met/);
    expect(b.b10).toMatch(/\| 1217 \/ 1378 +\|/);
    expect(b.stages).toMatch(/\| B5 .*\| within \/ over /);
    expect(b.verdict).toMatch(
      /V1 +\| \*\*Custom engine: GO\.\*\* .*\*\*passes\*\*.*p95 0\.50 ms, 15 draws/,
    );
    expect(b.verdict).toContain(
      "(6.39 ms, §3.4), which the headline excludes, gives about 6.9 ms: still within",
    );
    expect(b.verdict).toMatch(/V2 +\| \*\*ADR-0002's fallback trigger does not fire/);
    expect(b.verdict).toContain("full WebGL2 capability parity");
    expect(b.verdict).toMatch(
      /V5 .*missed its soak-window peak gate and its growth gate read start to end \(/,
    );
    expect(b.verdict).toMatch(
      /V6 .*114 frames over 33 ms \(p99 81\.60 ms\) in every run, runtime and flag set/,
    );
    expect(b.budget).toMatch(/M1 .*2\.21 ms against its 2 ms slice, over/);
    expect(b.budget).toMatch(/M2 .*B9: 7\.00 ms Electron \/ 4\.70 ms Chromium .*peaked at 1003 MB/);
    expect(b.budget).toContain("up to 143.60 ms in Electron");
    expect(b.budget).toMatch(/M6 .*0\.32 ms against its 1 ms slice, within/);
    expect(b.manifest).toContain("Intel(R) UHD Graphics 620");
    expect(b.stages).toMatch(/Candle geometry +\| 2\.21 .*over slice/);
  });
  it("marks a missed gate inconclusive and degrades gracefully without optional runs", () => {
    const e = report("electron", [
      frame("B1", 20),
      { ...frame("B5", 30), modelledStageMs: null },
      B9,
    ]);
    const b = renderBlocks([{ file: "e.json", sha256: "0".repeat(64), report: e }]);
    expect(b.results).toMatch(/\| B1 .*missed — inconclusive on this class/);
    expect(b.results).toContain("not run");
    expect(b.results).toContain("Headless Chromium (primary run)** — no report");
    expect(b.b5).toContain("FAIL");
    expect(b.trigger).toContain("fires or inconclusive");
    expect(b.noise).toBe("No A/B/A repeat run in the results.");
    expect(b.flagsets).toBe("No flag-set control run in the results.");
    expect(b.b10).toMatch(/\| Electron \| not run/);
    expect(b.results).toMatch(/B7 decode, inline .*not recorded/);
    expect(b.verdict).toContain("**Custom engine: not established.**");
    expect(b.verdict).toContain("**does not pass**");
    expect(b.verdict).toContain("fires or is inconclusive");
    expect(b.verdict).toContain("gaps in WebGL2 capability");
    expect(b.verdict).toContain("B10 resident memory is not recorded");
    expect(b.verdict).toContain("The modelled scene cost is not recorded.");
    expect(b.budget).toContain("modelled at not recorded");
    expect(b.budget).toContain("a figure not recorded");
    expect(b.verdict).toContain("B5 has no frames over 33 ms");
    expect(triggerFires({})).toBe(true);
    const none = renderBlocks([
      { file: "c.json", sha256: "0".repeat(64), report: report("chromium", ALL) },
    ]);
    expect(none.verdict).toContain("No Electron B5 cell in the results.");
    expect(none.verdict).toContain("B5 not recorded.");
    expect(none.budget).toContain("an unrecorded ms");
  });
  it("assigns roles: primary, supplement, repeat and flag-set control", () => {
    const mk = (rt: string, cells: Obj[], flag: string, ts: string) => {
      const r = report(rt, cells, { timestamp: ts });
      (r["manifest"] as { flagSet: Obj }).flagSet["name"] = flag;
      return r;
    };
    const entries = [
      { file: "e1", sha256: "a", report: mk("electron", [...ALL, B9, frame("B10", 2)], "t", "1") },
      { file: "e2", sha256: "b", report: mk("electron", [...ALL, B9], "t", "2") },
      { file: "e3", sha256: "c", report: mk("electron", [...ALL, B9], "d", "3") },
      { file: "c1", sha256: "d", report: mk("chromium", [...ALL, frame("B10", 3)], "k", "4") },
      { file: "c2", sha256: "e", report: mk("chromium", [B7], "k", "5") },
    ];
    const roles = assignRoles(entries);
    expect(roles.electron?.primary.file).toBe("e1");
    expect(roles.electron?.repeat.file).toBe("e2");
    expect(roles.electron?.control.file).toBe("e3");
    expect(roles.chromium?.cells["B7"]?.file).toBe("c2");
    const b = renderBlocks(entries);
    expect(b.results).toContain("(`c2`)");
    expect(b.flagsets).toContain("`t` (ms)");
    expect(b.b10).toMatch(/\| Chromium \| 30 .*not attributable/);
  });
  it("computes Electron soak-window memory from the shell samples", () => {
    const samples = [...Array(5).fill(100), ...Array(10).fill(150), ...Array(5).fill(110)].map(
      (workingSetMb) => ({ workingSetMb }),
    );
    const r = report("electron", ALL, {
      residentMemoryMb: { shellMetrics: [{ workingSetMb: 999 }, ...samples], peakMb: 999 },
    });
    expect(soakMemory(r)).toEqual({
      peak: 150,
      start: 100,
      end: 110,
      growthPct: 10,
      thirdStart: 100,
      thirdEnd: 110,
      thirdGrowthPct: 10,
      appRunPeak: 999,
      runPeak: 999,
    });
    const flat = report("electron", [...ALL, B9, frame("B10", 2)], {
      residentMemoryMb: { shellMetrics: Array(20).fill({ workingSetMb: 100 }), peakMb: 120 },
    });
    const fb = renderBlocks([{ file: "f.json", sha256: "0".repeat(64), report: flat }]);
    expect(fb.verdict).toContain("B10 resident memory met its gates (§3.5), conservatively.");
    expect(fb.b10).toMatch(/100 to 100 = \+0\.0 %; met .*\| 100 \/ 120 /);
    expect(soakMemory(report("electron", ALL, { config: { soakMs: 60_000 } }))).toBeNull();
    expect(soakMemory(report("electron", ALL))).toBeNull();
  });
  it("formats quantised zeros, missing figures and table cells", () => {
    expect(ms(0)).toBe("< 0.1");
    expect(ms(undefined)).toBe("not recorded");
    expect(ms(1.234, 1)).toBe("1.2");
    expect(table(["a"], [["x|y"]])).toBe("| a    |\n| ---- |\n| x\\|y |");
    // A backslash is escaped first, so a cell ending in `\` cannot swallow the next pipe.
    expect(table(["a"], [["x\\|y"]])).toBe("| a      |\n| ------ |\n| x\\\\\\|y |");
  });
});

describe("loading", () => {
  it("names every invalid file and problem", () => {
    const dir = writeDir({
      "a.json": report("chromium", [frame("B1", 1, 1)]),
      "b.json": { schema: "x" },
    });
    writeFileSync(join(dir, "c.json"), "{not json");
    expect(() => loadResults(dir)).toThrow(
      /a\.json: B1: inadmissible[\s\S]*b\.json[\s\S]*c\.json: not valid JSON/,
    );
  });
  it("refuses an empty results directory", () => {
    expect(() => loadResults(writeDir({}))).toThrow(/no matrix reports/);
  });
});

describe("marker splicing and --check", () => {
  const blocks = Object.fromEntries(NAMES.map((n) => [n, `table ${n}`]));
  it("replaces only marked bodies and keeps prose", () => {
    const out = spliceBlocks(skeleton("stale\n"), blocks);
    expect(out).toContain("prose");
    expect(out).toContain("<!-- prettier-ignore-start -->\ntable b5\n<!-- prettier-ignore-end -->");
    expect(out).not.toContain("stale");
    expect(driftedBlocks(out, blocks)).toEqual([]);
    expect(driftedBlocks(skeleton("stale\n"), blocks)).toEqual(NAMES);
  });
  it("rejects an unknown or a missing block", () => {
    expect(() =>
      spliceBlocks(skeleton() + "<!-- m0-report:begin zzz -->\n<!-- m0-report:end -->", blocks),
    ).toThrow(/unknown generated block "zzz"/);
    expect(() => spliceBlocks("# none\n", blocks)).toThrow(/lacks generated block/);
  });
  it("run(): writes, then --check passes; drift and bad inputs exit 1", () => {
    const dir = writeDir({ "e.json": report("electron", [...ALL, B9]) });
    const md = join(mkdtempSync(join(tmpdir(), "m0-md-")), "r.md");
    writeFileSync(md, skeleton("STALE-BODY\n"));
    const logs: string[] = [];
    const io = { log: (s: string) => logs.push(s), error: (s: string) => logs.push(s) };
    expect(run(["--results", dir, "--report", md, "--check"], io)).toBe(1);
    expect(logs.pop()).toMatch(/out of date: verdict, budget, results/);
    expect(run(["--results", dir, "--report", md], io)).toBe(0);
    expect(readFileSync(md, "utf8")).not.toContain("STALE-BODY");
    expect(run(["--results", dir, "--report", md, "--check"], io)).toBe(0);
    expect(run(["--results", writeDir({}), "--report", md], io)).toBe(1);
    expect(logs.pop()).toMatch(/no matrix reports/);
  });
  it("the committed report's generated blocks match a fresh render", () => {
    const io = { log: () => undefined, error: (s: string) => expect.fail(s) };
    expect(run(["--check"], io)).toBe(0);
  });
});

// A matrix figure in hand prose drifts silently when the raw data or the rendering changes, so
// prose points at a generated row instead. This guard fails if a prose number (outside the
// generated blocks) equals a measured figure in a generated data block. Scope: numbers with a
// decimal point or of 100 and more (small integers are section, repetition and score counts);
// the gate, slice and timer constants are not measurements; headings are skipped; a paragraph, bullet or table row that cites
// a spike document quotes that document's own figures, which are not matrix figures.
describe("no matrix figure is transcribed into prose", () => {
  const DATA_BLOCKS = ["results", "b5", "trigger", "stages", "b10", "noise", "flagsets"];
  const NUM = /(?<![\w§.\-:/])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?!\.?\d|[\w\-:])/g;
  const SPIKE_CITE = /E06-K03\.md|E06-K04\.md|E06-Q02\.md|E06-D03\.md|E10-K01\.md/;
  const CONSTANT_PHRASES = [/≥ 0\.2 ms, this job's two-tick floor/g];
  // 0.1 is the page's timer resolution ("< 0.1" is a quantisation marker, not a reading).
  const CONSTANTS = new Set([0.1, 16.7, 16.67, 16.6, 0.46, 900, 600, 100, 1.6]);
  const significant = (v: number, raw: string) => raw.includes(".") || v >= 100;

  const generated = (() => {
    const b = renderBlocks(loadResults(DEFAULT_RESULTS)) as Record<string, string>;
    const set = new Set<number>();
    for (const k of DATA_BLOCKS)
      for (const m of (b[k] ?? "").matchAll(NUM)) {
        const v = Number((m[1] ?? "").replace(/,/g, "") + (m[2] ?? ""));
        if (significant(v, m[0]) && !CONSTANTS.has(v) && v !== 0) set.add(v);
      }
    return set;
  })();

  /** Splits prose into paragraphs, bullets and table rows (continuation lines join their unit). */
  function units(md: string): string[] {
    const prose = md.replace(/\x3C!-- m0-report:begin [\s\S]*?\x3C!-- m0-report:end -->/g, "\n");
    const out: string[] = [];
    let cur = "";
    for (const line of prose.split("\n")) {
      const starts = line.trim() === "" || /^(\s*[-*] |\||#|\d+\. )/.test(line);
      if (starts && cur) {
        out.push(cur);
        cur = "";
      }
      if (line.trim()) cur += (cur ? " " : "") + line;
    }
    if (cur) out.push(cur);
    return out;
  }

  function offenders(md: string): string[] {
    const bad: string[] = [];
    for (const u of units(md)) {
      if (u.startsWith("#") || SPIKE_CITE.test(u)) continue;
      let t = u;
      for (const re of CONSTANT_PHRASES) t = t.replace(re, "");
      for (const m of t.matchAll(NUM)) {
        const v = Number((m[1] ?? "").replace(/,/g, "") + (m[2] ?? ""));
        if (significant(v, m[0]) && generated.has(v)) bad.push(`${m[0]} in: ${u.slice(0, 120)}`);
      }
    }
    return bad;
  }

  it("collects the measured figures from the generated data blocks", () => {
    for (const v of [0.5, 81.6, 114, 1003, 2.21, 632481.8, 143.6])
      expect(generated.has(v)).toBe(true);
    expect(generated.has(16.7)).toBe(false);
  });
  it("catches a transcribed figure, and ignores spike citations, constants and block bodies", () => {
    expect(offenders("Electron B5 p95 was 0.50 ms.\n")).toHaveLength(1);
    expect(offenders("- a stall of 632,481.8 ms\n  continued here\n")).toHaveLength(1);
    expect(offenders("| V1 | 114 frames |\n")).toHaveLength(1);
    expect(offenders("K03 measured 1.4 ms (`E06-D03.md` §3).\n")).toEqual([]);
    expect(offenders("The 0.1 ms timer; gate 16.7 ms; §3.5; 2026-10-29 08:40Z; B10.\n")).toEqual(
      [],
    );
    expect(offenders("<!-- m0-report:begin b5 -->\n0.50\n<!-- m0-report:end -->\nprose\n")).toEqual(
      [],
    );
  });
  it("the committed report's prose repeats no generated matrix figure", () => {
    expect(offenders(readFileSync(DEFAULT_REPORT, "utf8"))).toEqual([]);
  });
  it("the risk register's E06-T02 review lines repeat no generated matrix figure", () => {
    const reg = readFileSync(join(DEFAULT_REPORT, "../../32-risk-register.md"), "utf8");
    const reviews = reg
      .split("\n")
      .filter((l) => l.startsWith("- **Review** — 2026-10-29, E06-T02"));
    expect(reviews.length).toBe(3);
    expect(offenders(reviews.join("\n\n"))).toEqual([]);
  });
});
