// E06-T01 matrix: pure helpers (no DOM, no process control) shared by run-matrix.mjs,
// compare-matrix.mjs and the unit tests.
import { medianOfP95, MIN_ADMISSIBLE_REPETITIONS } from "../stats.mjs";
import { assertDescriptorComplete, missingManifestFields } from "../machine.mjs";

export const MATRIX_SCENARIOS = Object.freeze(["B1", "B2", "B3", "B4", "B5", "B7", "B9", "B10"]);
export const RUNTIMES = Object.freeze(["chromium", "electron", "tauri"]);
export const REPORT_SCHEMA = "cv-matrix-report/1";

/**
 * How long the driver waits for the page's `/done` once every requested cell has arrived. On the
 * hosted runner's SwiftShader the page posted every cell and then never sent `/done` (the context
 * teardown after the last cell), so the run sat until its budget and wrote a "timeout" report.
 */
export const DONE_GRACE_MS = 30_000;

/** True once `results` holds a cell for every requested scenario. */
export function cellsComplete(results, scenarios) {
  const got = new Set(results.filter((r) => r && r.kind === "cell").map((r) => r.scenario));
  return scenarios.length > 0 && scenarios.every((s) => got.has(s));
}

/** ADR-0011 decision criteria thresholds (binding text in the ADR). */
export const ADR_0011 = Object.freeze({
  /** criterion 1: B5 p95 in WebView2 within 10 % of Electron. */
  b5ParityPct: 10,
  /** criterion 2: frame-time outlier threshold (ms) during the B10 soak. */
  outlierMs: 33,
  /**
   * criterion 3 ("no progressive degradation"): the ADR gives no number. This analyst
   * tolerance (last third vs first third of 1-minute soak buckets, median texSubImage2D
   * time) is OUR assumption, defaulted to the same 10 % as criterion 1 and overridable
   * with `compare-matrix --degradation-tolerance`. It is printed next to the result.
   */
  degradationTolerancePct: 10,
});

const median = (xs) => {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
export { median };

/**
 * Collapses the page's raw cell (all repetitions) into the report cell. Medians of p95
 * per 06-... §7.4; B7's two run modes are summarised separately, NEVER pooled.
 * @param {any} raw
 */
export function summariseCell(raw) {
  if (raw.notRunnable) {
    return { scenario: raw.scenario, status: "not-runnable", reason: raw.notRunnable };
  }
  if (raw.scenario === "B7") {
    const modes = {};
    for (const mode of ["inline", "worker"]) {
      const reps = raw.storm?.[mode];
      if (!reps?.length) continue;
      modes[mode] = {
        repetitions: reps.length,
        decodeP95Ms: median(reps.map((r) => r.decodeP95Ms)),
        drops: reps.reduce((a, r) => a + r.drops, 0),
        duplicates: reps.reduce((a, r) => a + r.duplicates, 0),
        pass: reps.every((r) => r.pass),
        ...(mode === "worker"
          ? { offscreenWebgl2InWorker: reps.every((r) => r.offscreenWebgl2InWorker) }
          : {}),
      };
    }
    return {
      scenario: "B7",
      status: Object.keys(modes).length ? "ok" : "not-runnable",
      modes,
      workerError: raw.storm?.workerError ?? null,
      reason: Object.keys(modes).length ? undefined : "no storm mode completed",
    };
  }
  if (raw.scenario === "B9") {
    return {
      scenario: "B9",
      status: "ok",
      repetitions: raw.reps.length,
      coldInitToFirstFrameMs: median(raw.reps.map((r) => r.coldInitToFirstFrameMs)),
    };
  }
  const reps = raw.reps;
  const last = reps[reps.length - 1] ?? {};
  return {
    scenario: raw.scenario,
    status: "ok",
    repetitions: reps.length,
    admissibleForAdrEvidence: raw.scenario === "B10" ? true : reps.length >= 3,
    p50: median(reps.map((r) => r.p50)),
    p95: medianOfP95(reps.map((r) => r.p95)),
    p99: median(reps.map((r) => r.p99)),
    p95PerRep: reps.map((r) => r.p95),
    outliers33: reps.reduce((a, r) => a + r.outliers33, 0),
    maxMs: Math.max(...reps.map((r) => r.maxMs)),
    drawCalls: last.drawCalls ?? 0,
    mirrorP95Ms: median(reps.map((r) => r.mirrorP95Ms)),
    texUploadMedianMs: median(reps.map((r) => r.texUploadMedianMs).filter((v) => v != null)),
    soak: last.soak ?? null,
    composition: last.composition ?? null,
    modelledStageMs: last.modelledStageMs ?? null,
  };
}

/**
 * Same-scenario noise-band sanity gate (ticket Test plan): two medians-of-p95 from
 * back-to-back runs of one scenario must agree within `bandPct`.
 */
export function withinNoiseBand(a, b, bandPct) {
  if (!(a > 0) || !(b > 0)) return false;
  return (Math.abs(a - b) / Math.min(a, b)) * 100 <= bandPct + 1e-9;
}

/** Scenarios whose report cell is a frame-time cell (B7 and B9 are summarised differently). */
const FRAME_CELL = (c) => c?.status === "ok" && c.scenario !== "B7" && c.scenario !== "B9";

/**
 * E06-T02: validates one committed `cv-matrix-report/1` file before anything reads a number from
 * it (the M0 report generator and the CI comparison share it). Returns the problems found, empty
 * when the report is usable. A missing machine descriptor or version field, a dry run, and a
 * frame cell with fewer than 3 repetitions (06 section 7.4; the once-per-runtime B10 soak
 * excepted, as `summariseCell` rules) are all problems, never silently accepted.
 * @param {any} report
 * @returns {string[]}
 */
export function validateReport(report) {
  const problems = [];
  if (!report || typeof report !== "object") return ["not a JSON object"];
  if (report.schema !== REPORT_SCHEMA)
    problems.push(`schema is ${report.schema}, not ${REPORT_SCHEMA}`);
  if (report.dryRun !== false) problems.push("a --dry-run report carries no measurements");
  if (!RUNTIMES.includes(report.runtime)) problems.push(`unknown runtime ${report.runtime}`);
  const manifest = report.manifest;
  if (manifest?.schema !== "cv-version-manifest/1" || !manifest.machine || !manifest.versions) {
    problems.push("version manifest missing (machine descriptor and versions required)");
  } else {
    try {
      assertDescriptorComplete(manifest.machine);
    } catch (e) {
      problems.push(String(/** @type {Error} */ (e).message));
    }
    if (RUNTIMES.includes(manifest.runtime))
      for (const f of missingManifestFields(manifest)) problems.push(`missing version: ${f}`);
  }
  if (Array.isArray(report.manifestIncomplete) && report.manifestIncomplete.length)
    problems.push(`manifest marked incomplete: ${report.manifestIncomplete.join("; ")}`);
  if (!report.fixture?.sha256 || report.seed == null)
    problems.push("seed or fixture sha256 missing");
  if (!Array.isArray(report.cells) || report.cells.length === 0) {
    problems.push("no scenario cells");
    return problems;
  }
  for (const c of report.cells.filter(FRAME_CELL)) {
    const soak = c.scenario === "B10";
    if (!soak && !(c.repetitions >= MIN_ADMISSIBLE_REPETITIONS))
      problems.push(
        `${c.scenario}: inadmissible, ${c.repetitions} repetition(s) < ${MIN_ADMISSIBLE_REPETITIONS}`,
      );
    else if (c.admissibleForAdrEvidence !== true)
      problems.push(`${c.scenario}: marked inadmissible by the harness`);
    if (typeof c.p95 !== "number") problems.push(`${c.scenario}: no p95`);
  }
  return problems;
}
