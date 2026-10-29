#!/usr/bin/env node
// E06-T02 — renders the generated tables of the M0 findings report from the committed
// `cv-matrix-report/1` files, so no figure in the report is transcribed by hand.
//
//   node bench/matrix/m0-report.mjs            rewrite the generated blocks in place
//   node bench/matrix/m0-report.mjs --check    exit 1 when a committed block differs from a fresh render
//   options: --results <dir> (default: the 2026-10-29 matrix run), --report <file.md>
//
// Every input is validated first (`validateReport`, shared with the CI comparison): a missing
// machine descriptor or version field, a dry run or a frame cell under 3 repetitions fails the
// run. Only hardware class leaves the raw files: the manifest is projected onto an allow-list of
// fields and every string is scrubbed of absolute paths (STRIDE Information disclosure, 04 §5).
// Hand-written prose lives outside the `<!-- m0-report:begin NAME -->` / `<!-- m0-report:end -->`
// markers; a figure the JSON does not carry renders as "not recorded".
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { exitCriterion4 } from "./compare-matrix.mjs";
import { median, validateReport, withinNoiseBand } from "./matrix-lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../../..");
export const DEFAULT_RESULTS = join(HERE, "results/2026-10-29-win11-i7-8550u");
export const DEFAULT_REPORT = join(REPO, "docs/plan/spikes/E06-M0-report.md");

/** p95 gates, `26-chart-engine-design.md` §13; B10's frame gate is 06 §2 budget 1. */
export const FRAME_GATES = Object.freeze({
  B1: 12,
  B2: 14,
  B3: 16,
  B4: 10,
  B5: 16.7,
  B10: 16.6,
});
export const B7_DECODE_P95_MS = 4;
export const B9_COLD_INIT_MS = 900;
export const B10_MEMORY = Object.freeze({ peakMb: 600, growthPct: 5 });
/** E06-Q01 §3 documented run-to-run band, and ADR-0011's 10 % threshold. */
export const NOISE_BANDS_PCT = Object.freeze({ q01: 0.46, adr0011: 10 });
/** `06-performance-and-load-standard.md` §4.3 slices, in ms. */
export const STAGE_SLICES = Object.freeze([
  ["inputHandling", "Input handling", 1],
  ["dataWindowRecompute", "Data-window recompute", 2],
  ["candleGeometry", "Candle geometry", 2],
  ["footprintTextGeometry", "Footprint text and geometry", 4],
  ["heatmapUpload", "Heatmap upload", 2],
  ["paneRedraw", "Pane redraw", 2],
  ["overlayRedraw", "Overlay and order lines", 1],
  ["domMirrorSync", "DOM-mirror sync (modelled)", 1],
  ["compositePresent", "Composite and present", 1.6],
]);
const FRAME_SCENARIOS = ["B1", "B2", "B3", "B4", "B5", "B10"];
const MIRROR_SLICE_MS = 1;
const slice = (key) => STAGE_SLICES.find(([k]) => k === key)?.[2];
const EPS = 1e-9;

// ---------------------------------------------------------------------------
// Strip rule: hardware class only.
// ---------------------------------------------------------------------------

const PATH_RES = [
  /[A-Za-z]:\\(?:[^\s"'|<>]+)/g, // C:\Users\...
  /\\\\[^\s"'|<>\\]+\\[^\s"'|<>]*/g, // \\host\share
  /(?:^|(?<=[\s("'=]))\/(?:home|Users|root|tmp|var|opt|mnt|srv|workspace|runner)(?:\/[^\s"'|<>)]*)?/g,
  /file:\/\/\S+/g,
];
/** Replaces absolute paths (and anything that embeds a user or host name through one). */
export function redact(value) {
  let s = String(value);
  for (const re of PATH_RES) s = s.replace(re, "<path>");
  return s;
}

const MACHINE_FIELDS = ["cpu", "cpuCount", "totalMemMb", "os", "osBuild", "arch", "gpu", "driver"];
const VERSION_FIELDS = ["electron", "chromium", "node", "playwright", "tauri", "webview2"];

/** Projects a version manifest onto the hardware-class allow-list; every other field is dropped. */
export function sanitiseManifest(manifest) {
  const pick = (src, keys) =>
    Object.fromEntries(
      keys.map((k) => [
        k,
        src?.[k] == null ? null : typeof src[k] === "number" ? src[k] : redact(src[k]),
      ]),
    );
  return {
    machine: pick(manifest?.machine, MACHINE_FIELDS),
    versions: pick(manifest?.versions, VERSION_FIELDS),
    flagSet: {
      name: redact(manifest?.flagSet?.name ?? "unspecified"),
      flags: (manifest?.flagSet?.flags ?? []).map(redact),
    },
  };
}

// ---------------------------------------------------------------------------
// Loading and roles.
// ---------------------------------------------------------------------------

/**
 * Reads and validates every `*.json` report in `dir`. Throws, naming each file and problem,
 * when any report fails `validateReport`.
 * @returns {Array<{ file: string, sha256: string, report: any }>}
 */
export function loadResults(dir) {
  const files = readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort();
  if (files.length === 0) throw new Error(`no matrix reports in ${basename(dir)}`);
  const problems = [];
  const out = files.map((f) => {
    const raw = readFileSync(join(dir, f));
    let report;
    try {
      report = JSON.parse(raw.toString("utf8"));
    } catch {
      problems.push(`${f}: not valid JSON`);
      return null;
    }
    for (const p of validateReport(report)) problems.push(`${f}: ${p}`);
    return { file: f, sha256: createHash("sha256").update(raw).digest("hex"), report };
  });
  if (problems.length) throw new Error(`invalid matrix report(s):\n  - ${problems.join("\n  - ")}`);
  return /** @type {Array<{ file: string, sha256: string, report: any }>} */ (out).sort((a, b) =>
    String(a.report.timestamp).localeCompare(String(b.report.timestamp)),
  );
}

const cellOf = (entry, s) => entry?.report.cells.find((c) => c.scenario === s && c.status === "ok");

/**
 * Role rule (stated so a reader can check it): per runtime, the primary run is the one with the
 * most scenario cells (earliest on a tie); a scenario the primary lacks is taken from the
 * earliest other run of that runtime with the same flag set. Electron's other run with the
 * primary's flag set is the A/B/A repeat; a run with another flag set is the flag-set control.
 * @param {Array<{ file: string, sha256: string, report: any }>} entries
 * @returns {{ electron?: Role, chromium?: Role }}
 * @typedef {{ primary: any, cells: Record<string, { cell: any, file: string }>, repeat: any, control: any }} Role
 */
export function assignRoles(entries) {
  const roles = {};
  for (const runtime of ["electron", "chromium"]) {
    const mine = entries.filter((e) => e.report.runtime === runtime);
    if (!mine.length) continue;
    const primary = mine.reduce((a, b) => (b.report.cells.length > a.report.cells.length ? b : a));
    const flag = (e) => e.report.manifest.flagSet.name;
    const sameFlag = mine.filter((e) => e !== primary && flag(e) === flag(primary));
    const cells = {};
    for (const s of ["B1", "B2", "B3", "B4", "B5", "B7", "B9", "B10"]) {
      const src = cellOf(primary, s) ? primary : sameFlag.find((e) => cellOf(e, s));
      if (src) cells[s] = { cell: cellOf(src, s), file: src.file };
    }
    roles[runtime] = {
      primary,
      cells,
      repeat:
        runtime === "electron"
          ? (sameFlag.find((e) => !cellOf(e, "B10") && e.report.cells.length > 1) ?? null)
          : null,
      control: mine.find((e) => flag(e) !== flag(primary)) ?? null,
    };
  }
  return roles;
}

// ---------------------------------------------------------------------------
// Formatting.
// ---------------------------------------------------------------------------

/** Two decimals; a quantised zero is "< 0.1" (the page's 0.1 ms timer resolution). */
export function ms(v, d = 2) {
  if (typeof v !== "number" || !Number.isFinite(v)) return "not recorded";
  if (Math.abs(v) < EPS) return "< 0.1";
  return v.toFixed(d);
}

/** A markdown table, padded the way prettier pads one; `\` and then `|` in a cell are escaped. */
export function table(header, rows) {
  const esc = (c) => String(c).replace(/\\/g, "\\\\").replace(/\|/g, "\\|");
  const all = [header, ...rows].map((r) => r.map(esc));
  const w = header.map((_, i) => Math.max(3, ...all.map((r) => [...(r[i] ?? "")].length)));
  const line = (r) => `| ${r.map((c, i) => c + " ".repeat(w[i] - [...c].length)).join(" | ")} |`;
  return [
    line(all[0]),
    `| ${w.map((n) => "-".repeat(n)).join(" | ")} |`,
    ...all.slice(1).map(line),
  ].join("\n");
}

const verdict = (ok) => (ok ? "met" : "missed — inconclusive on this class");
const signed = (v, d = 2) => `${v >= 0 ? "+" : ""}${v.toFixed(d)}`;

// ---------------------------------------------------------------------------
// Blocks.
// ---------------------------------------------------------------------------

function frameRows(role) {
  return FRAME_SCENARIOS.map((s) => {
    const c = role?.cells[s]?.cell;
    if (!c) return [s, `p95 ≤ ${FRAME_GATES[s]} ms`, "not run", "", "", "", "", "", "", "n/a"];
    return [
      s,
      `p95 ≤ ${FRAME_GATES[s]} ms`,
      String(c.repetitions),
      ms(c.p50),
      ms(c.p95),
      ms(c.p99),
      c.p95PerRep.map((v) => ms(v, 1)).join(" / "),
      ms(c.maxMs),
      String(c.drawCalls),
      verdict(c.p95 <= FRAME_GATES[s] + EPS),
    ];
  });
}

function blockResults(roles) {
  const head = [
    "Scenario",
    "Gate",
    "Reps",
    "p50",
    "p95",
    "p99",
    "p95 per rep",
    "max",
    "Draws",
    "Verdict",
  ];
  const out = [];
  for (const [rt, label] of [
    ["electron", "Electron (primary run)"],
    ["chromium", "Headless Chromium (primary run)"],
  ]) {
    const r = roles[rt];
    out.push(
      `**${label}** — ${r ? `\`${r.primary.file}\`` : "no report"}; ms, medians over repetitions (p95: median of per-repetition p95, 06 §7.4).`,
      "",
    );
    out.push(table(head, frameRows(r)), "");
    const b7 = r?.cells.B7?.cell;
    const b9 = r?.cells.B9?.cell;
    out.push(
      table(
        ["Scenario", "Gate", "Figure", "Verdict"],
        [
          [
            "B7 frame",
            "p95 ≤ 16.7 ms",
            "not recorded (the harness keeps decode and drop figures only)",
            "n/a",
          ],
          ...["inline", "worker"].map((m) => {
            const x = b7?.modes?.[m];
            return x
              ? [
                  `B7 decode, ${m}`,
                  `p95 ≤ ${B7_DECODE_P95_MS} ms, 0 dropped`,
                  `p95 ${ms(x.decodeP95Ms)}, ${x.drops} dropped, ${x.duplicates} duplicated, ${x.repetitions} reps${r.cells.B7.file === r.primary.file ? "" : ` (\`${r.cells.B7.file}\`)`}`,
                  verdict(x.decodeP95Ms <= B7_DECODE_P95_MS && x.drops === 0),
                ]
              : [`B7 decode, ${m}`, `p95 ≤ ${B7_DECODE_P95_MS} ms`, "not recorded", "n/a"];
          }),
          b9
            ? [
                "B9 cold init",
                `≤ ${B9_COLD_INIT_MS} ms (median of ${b9.repetitions})`,
                ms(b9.coldInitToFirstFrameMs),
                verdict(b9.coldInitToFirstFrameMs <= B9_COLD_INIT_MS),
              ]
            : ["B9 cold init", `≤ ${B9_COLD_INIT_MS} ms`, "not recorded", "n/a"],
        ],
      ),
      "",
    );
  }
  return out.join("\n").trimEnd();
}

function blockB5(roles) {
  const rows = [];
  for (const [rt, e] of [
    ["Electron", roles.electron?.primary],
    ["Electron repeat", roles.electron?.repeat],
    ["Electron default flags", roles.electron?.control],
    ["Chromium", roles.chromium?.primary],
  ]) {
    const c = cellOf(e, "B5");
    if (!c) continue;
    const x = exitCriterion4(e.report);
    rows.push([
      rt,
      ms(c.p50),
      ms(c.p95),
      String(c.drawCalls),
      ms(c.p99),
      String(c.outliers33),
      ms(c.maxMs),
      x.status === "pass" && x.b5GateP95 && x.b5GateDrawCalls ? "PASS" : "FAIL",
    ]);
  }
  return table(
    [
      "B5 run",
      "p50 ms (≤ 16.67)",
      "p95 ms (≤ 16.7)",
      "Draws (≤ 40)",
      "p99 ms",
      "Frames > 33 ms",
      "max ms",
      "Criterion 4 and B5 gates",
    ],
    rows,
  );
}

const TRIGGER_SCENARIOS = ["B1", "B3", "B4", "B5"];

/** ADR-0002's measured half: B1, B3, B4 and B5 meet their p95 gates in both runtimes. */
export function triggerFires(roles) {
  return TRIGGER_SCENARIOS.some((s) =>
    ["electron", "chromium"].some((rt) => {
      const x = roles[rt]?.cells[s]?.cell;
      return !x || x.p95 > FRAME_GATES[s] + EPS;
    }),
  );
}

function blockTrigger(roles) {
  const rows = TRIGGER_SCENARIOS.map((s) => {
    const e = roles.electron?.cells[s]?.cell;
    const c = roles.chromium?.cells[s]?.cell;
    const v = (x) =>
      x ? `${ms(x.p95)}; ${verdict(x.p95 <= FRAME_GATES[s] + EPS)}` : "not recorded";
    return [s, `p95 ≤ ${FRAME_GATES[s]} ms`, v(e), v(c)];
  });
  const fires = triggerFires(roles);
  rows.push([
    "Trigger half 1",
    "all four met in both runtimes",
    fires ? "fires or inconclusive" : "does not fire",
    fires ? "fires or inconclusive" : "does not fire",
  ]);
  return table(["Gate", "Budget", "Electron p95 ms", "Chromium p95 ms"], rows);
}

function blockStages(roles) {
  const rows = FRAME_SCENARIOS.map((s) => {
    const e = roles.electron?.cells[s]?.cell;
    const c = roles.chromium?.cells[s]?.cell;
    const up = (x) => (x?.texUploadMedianMs == null ? "not recorded" : ms(x.texUploadMedianMs));
    const sl = (x) => (x ? (x.mirrorP95Ms <= MIRROR_SLICE_MS + EPS ? "within" : "over") : "n/a");
    return [
      s,
      e ? ms(e.mirrorP95Ms) : "not run",
      c ? ms(c.mirrorP95Ms) : "not run",
      `${sl(e)} / ${sl(c)}`,
      up(e),
      up(c),
    ];
  });
  const measured = table(
    [
      "Scenario",
      "DOM mirror p95, Electron",
      "DOM mirror p95, Chromium",
      `Mirror vs its ${MIRROR_SLICE_MS} ms slice (Electron / Chromium)`,
      "`texSubImage2D` median, Electron",
      "`texSubImage2D` median, Chromium",
    ],
    rows,
  );
  const eb = roles.electron?.cells.B5?.cell?.modelledStageMs;
  const cb = roles.chromium?.cells.B5?.cell?.modelledStageMs;
  const stageRows = STAGE_SLICES.map(([k, label, slice]) => {
    const fv = (o) => (o && typeof o[k] === "number" ? o[k].toFixed(2) : "not recorded");
    const over = [eb, cb].some((o) => o && o[k] > slice + EPS);
    return [label, fv(eb), fv(cb), `≤ ${slice}`, over ? "over slice (model output)" : "within"];
  });
  const tot = (o) => (o ? modelledTotal(o).toFixed(2) : "not recorded");
  stageRows.push(["Total", tot(eb), tot(cb), "≤ 16.6", ""]);
  return [
    "Measured (ms, medians over repetitions):",
    "",
    measured,
    "",
    "Modelled per-stage cost of B5 (`modelledStageMs`; a scene-model output, not a measurement):",
    "",
    table(["Stage (06 §4.3)", "Electron", "Chromium", "Slice", "Note"], stageRows),
  ].join("\n");
}

/**
 * Electron soak-window memory from `app.getAppMetrics()` samples (one per 15 s): the window peak,
 * start to end (5-sample medians) and first to last third (medians of each third) — the `26` §13
 * growth gate's two readings — plus the whole-run peaks (app metrics, and the OS-sample `peakMb`).
 */
export function soakMemory(report) {
  const samples = (report.residentMemoryMb?.shellMetrics ?? [])
    .map((m) => m.workingSetMb)
    .filter((v) => typeof v === "number");
  const n = Math.round((report.config?.soakMs ?? 0) / 15_000);
  if (!samples.length || n < 10 || samples.length < n) return null;
  const w = samples.slice(-n);
  const start = median(w.slice(0, 5));
  const end = median(w.slice(-5));
  const third = Math.floor(n / 3);
  const thirdStart = median(w.slice(0, third));
  const thirdEnd = median(w.slice(-third));
  return {
    peak: Math.max(...w),
    start,
    end,
    growthPct: ((end - start) / start) * 100,
    thirdStart,
    thirdEnd,
    thirdGrowthPct: ((thirdEnd - thirdStart) / thirdStart) * 100,
    appRunPeak: Math.max(...samples),
    runPeak: report.residentMemoryMb.peakMb,
  };
}

function blockB10(roles) {
  const rows = [];
  for (const [rt, label] of [
    ["electron", "Electron"],
    ["chromium", "Chromium"],
  ]) {
    const src = roles[rt]?.cells.B10;
    if (!src) {
      rows.push([label, "not run", "", "", "", "", "", "", ""]);
      continue;
    }
    const c = src.cell;
    const per = (c.soak ?? []).map((b) => b.p95);
    const entry = roles[rt].primary;
    const mem = soakMemory(entry.report);
    const runErr = entry.report.runError
      ? ` (run ended with \`${redact(entry.report.runError)}\`)`
      : "";
    rows.push([
      label,
      String((c.soak ?? []).reduce((a, b) => a + b.frames, 0)),
      `${ms(c.p95)}; ${verdict(c.p95 <= FRAME_GATES.B10 + EPS)}${runErr}`,
      per.length ? `${ms(Math.min(...per), 1)} to ${ms(Math.max(...per), 1)}` : "not recorded",
      `${c.outliers33} (max ${ms(c.maxMs, 1)})`,
      mem ? `${mem.peak}; ${verdict(mem.peak <= B10_MEMORY.peakMb)}` : "not attributable",
      mem
        ? `${mem.start} to ${mem.end} = ${signed(mem.growthPct, 1)} %; ${verdict(mem.growthPct <= B10_MEMORY.growthPct + EPS)}`
        : "not attributable",
      mem
        ? `${mem.thirdStart} to ${mem.thirdEnd} = ${signed(mem.thirdGrowthPct, 1)} %; ${verdict(mem.thirdGrowthPct <= B10_MEMORY.growthPct + EPS)}`
        : "not attributable",
      mem ? `${mem.appRunPeak} / ${mem.runPeak ?? "not recorded"}` : "not attributable",
    ]);
  }
  return table(
    [
      "B10 run",
      "Frames",
      `Frame p95 ms (gate ≤ ${FRAME_GATES.B10})`,
      "Per-minute p95 ms",
      "Frames > 33 ms",
      `Soak-window peak MB (≤ ${B10_MEMORY.peakMb})`,
      `Soak growth, start to end (≤ ${B10_MEMORY.growthPct} %)`,
      `Soak growth, first to last third (≤ ${B10_MEMORY.growthPct} %)`,
      "Whole-run peak MB (app metrics / OS sample)",
    ],
    rows,
  );
}

function pairRows(a, b) {
  return ["B1", "B2", "B3", "B4", "B5", "B9"].map((s) => {
    const x = cellOf(a, s);
    const y = cellOf(b, s);
    const val = (c) => (c ? (s === "B9" ? c.coldInitToFirstFrameMs : c.p95) : null);
    const va = val(x);
    const vb = val(y);
    const d = va != null && vb != null ? vb - va : null;
    return [
      s === "B9" ? "B9 (median cold init)" : s,
      ms(va),
      ms(vb),
      d == null ? "not recorded" : signed(d),
    ];
  });
}

function blockNoise(roles) {
  const e = roles.electron;
  if (!e?.repeat) return "No A/B/A repeat run in the results.";
  const a = cellOf(e.primary, "B5")?.p95;
  const b = cellOf(e.repeat, "B5")?.p95;
  return [
    table(
      ["Scenario", `Electron \`${e.primary.file}\``, `Repeat \`${e.repeat.file}\``, "Delta ms"],
      pairRows(e.primary, e.repeat),
    ),
    "",
    `B5 within the E06-Q01 band (${NOISE_BANDS_PCT.q01} %): **${withinNoiseBand(a, b, NOISE_BANDS_PCT.q01) ? "yes" : "no"}**; within ADR-0011's ${NOISE_BANDS_PCT.adr0011} %: **${withinNoiseBand(a, b, NOISE_BANDS_PCT.adr0011) ? "yes" : "no"}**.`,
  ].join("\n");
}

function blockFlagsets(roles) {
  const e = roles.electron;
  if (!e?.repeat || !e.control) return "No flag-set control run in the results.";
  const fa = e.repeat.report.manifest.flagSet.name;
  const fb = e.control.report.manifest.flagSet.name;
  return table(
    ["Scenario", `\`${fa}\` (ms)`, `\`${fb}\` (ms)`, "Delta ms"],
    pairRows(e.repeat, e.control),
  );
}

function blockManifest(entries) {
  const rows = entries.map(({ file, sha256, report }) => {
    const m = sanitiseManifest(report.manifest);
    const v = m.versions;
    return [
      `\`${file}\``,
      report.runtime,
      m.flagSet.name,
      (report.cells ?? []).map((c) => c.scenario).join(" "),
      v.electron ?? "-",
      v.chromium ?? "-",
      v.node ?? "-",
      v.playwright ?? "-",
      v.webview2 ?? "not applicable (no WebView2 arm)",
      report.runError ? redact(report.runError) : "none",
      `\`${sha256.slice(0, 16)}…\``,
    ];
  });
  const first = sanitiseManifest(entries[0].report.manifest).machine;
  const same = entries.every(
    (x) => JSON.stringify(sanitiseManifest(x.report.manifest).machine) === JSON.stringify(first),
  );
  const inputs = entries[0].report;
  const capRows = Object.entries(assignRoles(entries)).map(([rt, r]) => {
    const c = r.primary.report.capabilities ?? {};
    const yn = (v) => (v === true ? "yes" : v === false ? "no" : "not recorded");
    const worker = cellOf(r.primary, "B7") ?? r.cells.B7?.cell;
    return [
      rt,
      redact(c.renderer ?? "not recorded"),
      yn(c.webgl2),
      yn(c.EXT_color_buffer_float),
      yn(c.r16fSampling),
      yn(c.instancing),
      yn(c.offscreenCanvas),
      yn(worker?.modes?.worker?.offscreenWebgl2InWorker),
      String(c.maxTextureSize ?? "not recorded"),
    ];
  });
  return [
    `Machine (hardware class only${same ? ", identical in every report" : "; REPORTS DIFFER"}): ${first.cpu}, ${first.cpuCount} logical CPUs, ${first.totalMemMb} MB RAM, ${first.gpu} (driver ${first.driver}), ${first.os} ${first.osBuild} ${first.arch}.`,
    "",
    `Inputs: seed \`${inputs.seed}\`, ${inputs.fixture.barCount} bars, fixture sha256 \`${inputs.fixture.sha256}\`, driver-script sha256 \`${inputs.driverScriptSha256}\`, ${inputs.config.reps} repetitions × ${inputs.config.durationMs / 1000} s, soak ${inputs.config.soakMs / 60_000} min.`,
    "",
    table(
      [
        "Report",
        "Runtime",
        "Flag set",
        "Scenarios",
        "Electron",
        "Chromium",
        "Node",
        "Playwright",
        "WebView2",
        "Run error",
        "sha256",
      ],
      rows,
    ),
    "",
    "Flag sets: " +
      [
        ...new Map(
          entries.map((x) => [
            x.report.manifest.flagSet.name,
            sanitiseManifest(x.report.manifest).flagSet,
          ]),
        ).values(),
      ]
        .map(
          (f) =>
            `\`${f.name}\` = ${f.flags.length ? f.flags.map((x) => `\`${x}\``).join(" ") : "no switches"}`,
        )
        .join("; ") +
      ".",
    "",
    table(
      [
        "Runtime",
        "WebGL renderer",
        "WebGL2",
        "`EXT_color_buffer_float`",
        "R16F sampling",
        "Instancing",
        "OffscreenCanvas",
        "WebGL2 in a worker (B7)",
        "Max texture",
      ],
      capRows,
    ),
  ].join("\n");
}

// The §2 verdict table and the §10 budget table are generated whole, so every figure in them
// comes from the raw reports and every claim that rests on a figure is recomputed from it.

const modelledTotal = (o) =>
  o ? Object.values(o).reduce((a, b) => a + (typeof b === "number" ? b : 0), 0) : null;
const stageVsSlice = (o, key) => {
  const v = o?.[key];
  if (typeof v !== "number") return "not recorded";
  return `${v.toFixed(2)} ms against its ${slice(key)} ms slice, ${v > slice(key) + EPS ? "over" : "within"}`;
};
const b5Runs = (roles) =>
  [
    roles.electron?.primary,
    roles.electron?.repeat,
    roles.electron?.control,
    roles.chromium?.primary,
  ].filter((e) => cellOf(e, "B5"));

function blockVerdict(roles) {
  const e = roles.electron;
  const b5 = e?.cells.B5?.cell;
  const x = e ? exitCriterion4(e.primary.report) : { status: "no-data" };
  const pass = x.status === "pass" && x.b5GateP95 && x.b5GateDrawCalls;
  const fires = triggerFires(roles);
  const model = modelledTotal(b5?.modelledStageMs);
  const withModel = b5 && model != null ? b5.p95 + model : null;
  const v1 = b5
    ? `${pass && !fires ? "**Custom engine: GO.**" : "**Custom engine: not established.**"} R0 exit criterion 4 (roadmap §4.3, ≥ 60 fps p50 and ≥ 55 fps p95 on the combined scene in Electron) **${pass ? "passes" : "does not pass"}** (conservative, §1): B5 p50 ${ms(b5.p50)} ms, p95 ${ms(b5.p95)} ms, ${b5.drawCalls} draws. ${withModel == null ? "The modelled scene cost is not recorded." : `Adding the scene models' modelled B5 cost (${model.toFixed(2)} ms, §3.4), which the headline excludes, gives about ${withModel.toFixed(1)} ms: ${withModel <= FRAME_GATES.B5 + EPS ? "still within" : "over"} the ${FRAME_GATES.B5} ms B5 gate.`}`
    : "**Custom engine: not established.** No Electron B5 cell in the results.";
  const v2 = fires
    ? "**ADR-0002's fallback trigger fires or is inconclusive on the measured half**: at least one of B1, B3, B4 and B5 misses its p95 gate (or is missing) in Chromium or Electron."
    : "**ADR-0002's fallback trigger does not fire on the measured half**: B1, B3, B4 and B5 meet their p95 gates in both Chromium and Electron. The other half (M1 overrun) is a schedule fact.";
  const cap = e?.primary.report.capabilities ?? {};
  const workerGl = e?.cells.B7?.cell?.modes?.worker?.offscreenWebgl2InWorker;
  const parity =
    ["webgl2", "EXT_color_buffer_float", "r16fSampling", "instancing", "offscreenCanvas"].every(
      (k) => cap[k] === true,
    ) && workerGl === true;
  const mem = e?.cells.B10 ? soakMemory(e.primary.report) : null;
  const missed = mem
    ? [
        mem.peak > B10_MEMORY.peakMb && "its soak-window peak gate",
        mem.growthPct > B10_MEMORY.growthPct + EPS && "its growth gate read start to end",
        mem.thirdGrowthPct > B10_MEMORY.growthPct + EPS &&
          "its growth gate read first to last third",
      ].filter(Boolean)
    : [];
  const runs = b5Runs(roles).map((r) => cellOf(r, "B5"));
  const same = runs.length > 1 && runs.every((c) => c.outliers33 === runs[0].outliers33);
  const v6 = !b5
    ? "B5 not recorded."
    : b5.outliers33 === 0
      ? `B5 has no frames over 33 ms (p99 ${ms(b5.p99)} ms).`
      : `**A hitch that p95 hides:** B5 has ${b5.outliers33} frames over 33 ms (p99 ${ms(b5.p99)} ms)${same ? " in every run, runtime and flag set" : ""} — the 500 ms footprint rebuild (\`SUMMARY.md\` "B5 and R0 exit criterion 4"). M3 must chunk it.`;
  return table(
    ["#", "Verdict", "Traces to"],
    [
      ["V1", v1, '§3.2, row "Electron"; §3.4 "Total"'],
      ["V2", v2, '§3.3, row "Trigger half 1"'],
      [
        "V3",
        "Both verdicts are **conservative** (met on a below-class host) and rest on a harness page, not the engine: E11 must re-establish them on the real engine (§10, §13).",
        "§1, §5",
      ],
      [
        "V4",
        `**Shell: Electron, confirmed.** ADR-0011 criteria 1–4 are not measured and are decided on criterion 5, which Tauri fails (E10-K01 §4). Electron has ${parity ? "full WebGL2 capability parity" : "gaps in WebGL2 capability (see §5)"}.`,
        "§4; §5 capability rows",
      ],
      [
        "V5",
        missed.length
          ? `**Inconclusive, re-measure:** B10 resident memory missed ${missed.join(" and ")} (§3.5). Memory does not scale with GPU class the way frame time does, so E11 treats it as real.`
          : mem
            ? "B10 resident memory met its gates (§3.5), conservatively."
            : "B10 resident memory is not recorded (§3.5).",
        '§3.5, row "Electron"',
      ],
      ["V6", v6, '§3.2, column "Frames > 33 ms"; §10 M3'],
      [
        "V7",
        'The CI job (Chromium per PR, Electron nightly) records the matrix and never gates in R0 (roadmap §4.4 "not yet gating").',
        "§12",
      ],
    ],
  );
}

function blockBudget(roles) {
  const eo = roles.electron?.cells.B5?.cell?.modelledStageMs;
  const b9 = (rt) => roles[rt]?.cells.B9?.cell?.coldInitToFirstFrameMs;
  const mem = roles.electron?.cells.B10 ? soakMemory(roles.electron.primary.report) : null;
  const eb5 = b5Runs(roles)
    .filter((r) => r.report.runtime === "electron")
    .map((r) => cellOf(r, "B5").maxMs);
  const draws = roles.electron?.cells.B5?.cell?.drawCalls;
  return table(
    ["M", "What the findings say to budget (evidence)"],
    [
      [
        "M1",
        `Re-baseline B1 / B2 on the real engine in the CI job (§12); record the \`06\` §4.3 stage split the harness lacks (U4); candle geometry was modelled at ${stageVsSlice(eo, "candleGeometry")} (§3.4). Capability probe and context-loss handling must serialise lost → restore (§7, F1).`,
      ],
      [
        "M2",
        `Worker + \`RunMode.inline\` with a shared LOD trace hook so Q02's equivalence protocol runs (C-Q02-1, §9); keep B7's frame p95 in the report cell (U3); the D9 mirror row payload (§8, U9). B9: ${ms(b9("electron"))} ms Electron / ${ms(b9("chromium"))} ms Chromium against ${B9_COLD_INIT_MS} ms (§3.1) — a JavaScript cold init over the generated fixture, not an engine or process cold start, so M2 re-measures it. Memory governor: B10's Electron page peaked at ${mem ? `${mem.peak} MB` : "a figure not recorded"} in the soak window (§3.5, V5).`,
      ],
      [
        "M3",
        `Chunk the footprint rebuild across frames — the matrix shows a 500 ms rebuild costing up to ${eb5.length ? ms(Math.max(...eb5)) : "an unrecorded"} ms in Electron (§3.2 "max ms", V6) and K03 measured a 5.7 ms reformat (\`E06-K03.md\` "Reformat cost"); real WebGL2 B3 with glyphs, DPR 1.0 / 1.5 / 2.0 goldens, IndexedDB atlas ≤ 5 ms (\`E06-K03.md\` "What M3 must budget").`,
      ],
      [
        "M4",
        'Upload headroom is 1 KB/s of 12 (§7, `E06-K04.md` "Experiments"); amortise price-origin shifts; confirm O3 at the real-GPU 4 h soak; 16.06 MB GPU per symbol (§7).',
      ],
      [
        "M5",
        `Pane redraw was modelled at ${stageVsSlice(eo, "paneRedraw")} (§3.4); B5 re-measured with real layers in Electron, ≤ 40 draws (${draws ?? "not recorded"} today, §3.2).`,
      ],
      [
        "M6",
        `B5 with 50 real order lines; the overlay stage was modelled at ${stageVsSlice(eo, "overlayRedraw")} (§3.4). Its order-line and position updates are never shed (\`06\` §4.4); the stage's drawing tools are not protected.`,
      ],
      ["M7", "B8 (not in the matrix): no M0 evidence; budget from `26` §13 only."],
      [
        "M8",
        "B10 memory re-measured on reference hardware (V5) and on the real engine; DOM-mirror cost at the 200-row cap and in a fling is over 1 ms (§8, U9); B6 (not in the matrix) has no M0 evidence.",
      ],
    ],
  );
}

/** Renders every generated block from validated entries. */
export function renderBlocks(entries) {
  const roles = assignRoles(entries);
  return {
    verdict: blockVerdict(roles),
    budget: blockBudget(roles),
    results: blockResults(roles),
    b5: blockB5(roles),
    trigger: blockTrigger(roles),
    stages: blockStages(roles),
    b10: blockB10(roles),
    noise: blockNoise(roles),
    flagsets: blockFlagsets(roles),
    manifest: blockManifest(entries),
  };
}

// ---------------------------------------------------------------------------
// Marker splicing and --check.
// ---------------------------------------------------------------------------

// `\x3C` is `<`: a literal `<!--` in a regex is legacy HTML-comment syntax some parsers reject.
const BLOCK_RE = /\x3C!-- m0-report:begin ([a-z0-9-]+) -->\n[\s\S]*?\x3C!-- m0-report:end -->/g;

/** Replaces each marked block's body; an unknown block name or a missing block is an error. */
export function spliceBlocks(markdown, blocks) {
  const seen = new Set();
  const out = markdown.replace(BLOCK_RE, (_, name) => {
    if (!(name in blocks)) throw new Error(`unknown generated block "${name}"`);
    seen.add(name);
    return `<!-- m0-report:begin ${name} -->\n<!-- prettier-ignore-start -->\n${blocks[name]}\n<!-- prettier-ignore-end -->\n<!-- m0-report:end -->`;
  });
  const missing = Object.keys(blocks).filter((k) => !seen.has(k));
  if (missing.length) throw new Error(`report lacks generated block(s): ${missing.join(", ")}`);
  return out;
}

/** Names of the blocks whose committed text differs from a fresh render. */
export function driftedBlocks(markdown, blocks) {
  const fresh = spliceBlocks(markdown, blocks);
  const grab = (md) => Object.fromEntries([...md.matchAll(BLOCK_RE)].map((m) => [m[1], m[0]]));
  const a = grab(markdown);
  const b = grab(fresh);
  return Object.keys(b).filter((k) => a[k] !== b[k]);
}

/** CLI body; returns the exit code. */
export function run(argv, io = { log: console.log, error: console.error }) {
  const get = (flag, dflt) => {
    const i = argv.indexOf(flag);
    return i >= 0 && argv[i + 1] ? resolve(argv[i + 1]) : dflt;
  };
  const results = get("--results", DEFAULT_RESULTS);
  const reportPath = get("--report", DEFAULT_REPORT);
  let blocks;
  let md;
  try {
    blocks = renderBlocks(loadResults(results));
    md = readFileSync(reportPath, "utf8");
    if (argv.includes("--check")) {
      const drift = driftedBlocks(md, blocks);
      if (drift.length) {
        io.error(
          `[m0-report] generated block(s) out of date: ${drift.join(", ")}; run node bench/matrix/m0-report.mjs`,
        );
        return 1;
      }
      io.log("[m0-report] generated blocks match the committed reports");
      return 0;
    }
    writeFileSync(reportPath, spliceBlocks(md, blocks));
  } catch (e) {
    io.error(`[m0-report] ${/** @type {Error} */ (e).message}`);
    return 1;
  }
  io.log(
    `[m0-report] wrote ${Object.keys(blocks).length} generated blocks into ${basename(reportPath)}`,
  );
  return 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(run(process.argv.slice(2)));
}
