// E11-T06: the real-engine bench scenarios, their 26 §13 gates and the pure arithmetic the page,
// the runner (`run-matrix.mjs --page engine`) and `ci-compare.mjs` share. No DOM, no Node APIs.
import { medianOfP95, percentile } from "../stats.mjs";
import { median } from "../matrix/matrix-lib.mjs";

/** 06 §4.3's nine stages, the names `src/scene/frame-scheduler.ts` times (a test pins them). */
export const ENGINE_STAGES = Object.freeze([
  "inputHandling",
  "dataWindowRecompute",
  "candleGeometry",
  "footprintTextGeometry",
  "heatmapUpload",
  "paneRedraw",
  "overlayRedraw",
  "domMirrorSync",
  "compositePresent",
]);
/** `src/scene/stage-marks.ts`'s names (pinned by a test): boundary i < 9 ends stage i. */
export const STAGE_PREFIX = "cv.stage.";
export const FRAME_START = "cv.frame.start";

/** C-9.1 #16: the gate compares the median of five repetitions' p95s. */
export const ENGINE_REPS = 5;
/** 26 §13: each scenario replays its fixture for 20 s; B10 is the 30-minute soak. */
export const ENGINE_DURATION_MS = 20_000;
export const SOAK_MS = 30 * 60_000;

/**
 * What B5 and B6 lack on today's engine: `pane.addOverlay` and `pane.addIndicator` are no-op stubs
 * (src/api/pane.ts) and the footprint and heatmap series get no data, so both measure candles only.
 */
export const PARTIAL_CONTENT =
  "partial: footprint (E18), heatmap (E21) and the 3 indicators + 50 order lines (E12) are not " +
  "rendered yet; the cell measures candles only";

/**
 * 26 §13's table. `gates` are the absolute budgets (`max`, inclusive); `metric` names the report
 * cell field. A `stub` scenario's layer has not landed: it is recorded "not implemented", naming
 * the Epic that brings it, never silently left out. `nightly`: never part of a per-PR run.
 */
export const ENGINE_SCENARIOS = Object.freeze({
  B1: {
    what: "100k candles, continuous pan at 1000 px/s",
    gates: [
      { metric: "p95", label: "frame p95", unit: "ms", max: 12 },
      { metric: "drawCalls", label: "draw calls", unit: "", max: 8 },
    ],
  },
  B2: {
    what: "100k candles, wheel zoom sweep 0.1 to 50 px/bar",
    gates: [
      { metric: "p95", label: "frame p95", unit: "ms", max: 14 },
      { metric: "lodChanges", label: "LOD changes", unit: "", max: 6 },
    ],
  },
  B3: { stub: "E18", what: "Footprint, 2,500 visible cells with text" },
  B4: { stub: "E21", what: "Heatmap, 100 ms columns, 4 h trail, panning" },
  B5: {
    what: "candles + footprint + heatmap + 3 indicators + 50 order lines",
    // The real engine has candles only so far: recorded partial, never passed off as full B5.
    partial: PARTIAL_CONTENT,
    gates: [
      { metric: "p95", label: "frame p95", unit: "ms", max: 16.7 },
      { metric: "drawCalls", label: "total draw calls", unit: "", max: 40 },
    ],
  },
  B6: {
    what: "4 synchronised charts (B5 content, half density)",
    partial: PARTIAL_CONTENT,
    gates: [
      { metric: "p95", label: "aggregate frame p95", unit: "ms", max: 16.7 },
      // Recorded on software GL (SwiftShader burns the CPU itself); enforced on a GPU runner.
      { metric: "workerCpuPct", label: "worker CPU % of one core", unit: "%", max: 70 },
    ],
  },
  B7: { stub: "E17", what: "Live update storm: 20 data messages/s x 6 stores" },
  B8: { stub: "E14", what: "Drawing interaction: 200 drawings, drag one" },
  B9: {
    what: "Cold init to first frame with 100k bars",
    gates: [
      { metric: "coldInitToFirstFrameMs", label: "cold init", unit: "ms", max: 900 },
      // Needs E11-S11's atlas counters on the bench page: "not measured" until they are.
      { metric: "atlasFromCacheMs", label: "SDF atlas from cache", unit: "ms", max: 5 },
    ],
  },
  B10: {
    nightly: true,
    what: "Memory soak: 30 min live feed",
    gates: [
      { metric: "peakMemoryMb", label: "peak memory", unit: "MB", max: 600 },
      { metric: "growthPct", label: "growth over the soak", unit: "%", max: 5 },
    ],
  },
});

export const ENGINE_SCENARIO_IDS = Object.freeze(Object.keys(ENGINE_SCENARIOS));
const isRun = (id) => !ENGINE_SCENARIOS[id]?.stub;
/** The per-PR set: every implemented scenario but the nightly soak. */
export const PER_PR_SCENARIOS = Object.freeze(
  ENGINE_SCENARIO_IDS.filter((id) => isRun(id) && !ENGINE_SCENARIOS[id].nightly),
);
export const STUB_SCENARIOS = Object.freeze(ENGINE_SCENARIO_IDS.filter((id) => !isRun(id)));

/**
 * Chromium flags the engine page adds to the pinned set: without this one `performance.memory` is
 * quantised and its 5 % rule would be blind or flip at bucket edges.
 */
export const ENGINE_CHROMIUM_FLAGS = Object.freeze(["--enable-precise-memory-info"]);

/** The `FrameStats` fields (src/api/types.ts) the page reads from each `frameStats` event. */
export const FRAME_STATS_FIELDS = Object.freeze(["drawCalls", "lodCandles", "frameTimeMsP95"]);

/**
 * One `frameStats` event as the page records it. Throws when a field is missing or not finite, so
 * a renamed field makes the cell not runnable (which fails an enforced run) instead of NaN.
 * @param {any} s a `FrameStats` event (or anything, when the API drifts)
 */
export function frameStatsSample(s) {
  for (const k of FRAME_STATS_FIELDS) {
    const v = s?.[k];
    if (typeof v !== "number" || !Number.isFinite(v))
      throw new Error(`frameStats.${k} is missing or not finite (${String(v)})`);
  }
  return { drawCalls: s.drawCalls, lod: s.lodCandles, frameMs: s.frameTimeMsP95 };
}

/**
 * Main-thread heap in MB, or null when the reading is quantised (`precise` false: the runner did
 * not add `--enable-precise-memory-info`) or absent. An imprecise figure is never compared.
 * @param {{ usedJSHeapSize: number } | undefined} memory `performance.memory`
 * @param {boolean} precise
 */
export function heapReadingMb(memory, precise) {
  if (!precise || !memory || !Number.isFinite(memory.usedJSHeapSize)) return null;
  return memory.usedJSHeapSize / 1048576;
}

/**
 * A rep's memory figure: the peak heap above the reading taken before the charts mounted (the
 * fixture is allocated before that, so it is excluded). Null when nothing was read.
 * @param {number | null} baseMb
 * @param {(number | null)[]} samples
 */
export function memoryDeltaMb(baseMb, samples) {
  const xs = samples.filter((v) => typeof v === "number" && Number.isFinite(v));
  if (baseMb == null || !xs.length) return null;
  return Math.max(0, Math.max(...xs) - baseMb);
}

/** The report cell for a scenario whose layer has not landed. */
export function stubCell(id) {
  const s = ENGINE_SCENARIOS[id];
  return {
    scenario: id,
    status: "stub",
    owner: s.stub,
    reason: `not implemented: ${s.what} needs ${s.stub}'s layer`,
  };
}

/**
 * Splits a timeline's marks (time order) into frames: per frame the total (start to the last
 * stage end) and each stage's duration (from the boundary before it, the layout end included).
 * @param {{ name: string, startTime: number }[]} marks
 */
export function framesFromMarks(marks) {
  const frameMs = [];
  const stageMs = Object.fromEntries(ENGINE_STAGES.map((s) => [s, []]));
  let start = null;
  let prev = 0;
  let open = null;
  for (const m of marks) {
    if (m.name === FRAME_START) {
      start = prev = m.startTime;
      open = Object.fromEntries(ENGINE_STAGES.map((s) => [s, 0]));
      continue;
    }
    if (start === null || !m.name.startsWith(STAGE_PREFIX)) continue;
    const stage = m.name.slice(STAGE_PREFIX.length);
    if (stage in open) open[stage] += m.startTime - prev;
    prev = m.startTime;
    if (stage === ENGINE_STAGES[ENGINE_STAGES.length - 1]) {
      frameMs.push(prev - start);
      for (const s of ENGINE_STAGES) stageMs[s].push(open[s]);
      start = null;
    }
  }
  return { frameMs, stageMs };
}

/** Max minus min over the median, in percent: published (AC2), never a failure (ruling BQ-08). */
export function spreadPct(xs) {
  const m = median(xs);
  if (!(m > 0)) return null;
  return ((Math.max(...xs) - Math.min(...xs)) / m) * 100;
}

/** Soak growth: the last tenth's median over the first tenth's, in percent. */
export function growthPct(series) {
  if (series.length < 2) return null;
  const n = Math.max(1, Math.floor(series.length / 10));
  const first = median(series.slice(0, n));
  const last = median(series.slice(-n));
  return first > 0 ? ((last - first) / first) * 100 : null;
}

/** LOD level changes over a run of per-frame levels. */
export function lodChanges(levels) {
  let n = 0;
  for (let i = 1; i < levels.length; i += 1) if (levels[i] !== levels[i - 1]) n += 1;
  return n;
}

const numbers = (xs) => xs.filter((v) => typeof v === "number" && Number.isFinite(v));
const medianOf = (xs) => (numbers(xs).length ? median(numbers(xs)) : null);
const maxOf = (xs) => (numbers(xs).length ? Math.max(...numbers(xs)) : null);

/**
 * What the heap figure cannot see: `performance.memory.usedJSHeapSize` is the V8 heap, and V8 keeps
 * ArrayBuffer backing stores outside it as external memory, so typed-array growth is not counted.
 */
export const MEMORY_LIMIT =
  "usedJSHeapSize only: ArrayBuffer backing stores (typed arrays) are V8 external memory, not counted";

/**
 * Collapses the page's raw cell (every repetition) into the report cell `ci-compare.mjs` reads:
 * the median of the per-rep p95s, the per-rep p95s and their spread, the counters, memory and
 * 06 §4.3's per-stage p95 with the stage furthest over its share.
 * @param {any} raw
 */
export function summariseEngineCell(raw) {
  if (raw.notRunnable)
    return { scenario: raw.scenario, status: "not-runnable", reason: raw.notRunnable };
  const reps = raw.reps;
  // A run that rendered nothing reads p95 = 0 ms through `percentile([])`: never a pass (B9 alone
  // measures cold init with no scripted frames).
  if (raw.scenario !== "B9") {
    const empty = reps.findIndex((r) => !(r.frameMs?.length > 0));
    if (reps.length === 0 || empty >= 0)
      return {
        scenario: raw.scenario,
        status: "not-runnable",
        reason:
          reps.length === 0 ? "no repetitions recorded" : `rep ${empty + 1} recorded no frame`,
      };
  }
  const p95PerRep = reps.map((r) => percentile(r.frameMs, 95));
  const stageP95Ms = Object.fromEntries(
    ENGINE_STAGES.map((s) => [s, medianOf(reps.map((r) => percentile(r.stageMs?.[s] ?? [], 95)))]),
  );
  const worstStage = ENGINE_STAGES.reduce((w, s) =>
    (stageP95Ms[s] ?? 0) > (stageP95Ms[w] ?? 0) ? s : w,
  );
  const soak = raw.scenario === "B10";
  const precise = reps.length > 0 && reps.every((r) => r.memoryPrecision === "precise");
  const scope = reps.find((r) => r.memoryScope)?.memoryScope;
  const partial = ENGINE_SCENARIOS[raw.scenario]?.partial;
  return {
    scenario: raw.scenario,
    status: "ok",
    repetitions: reps.length,
    admissibleForAdrEvidence: soak || reps.length >= 3,
    p50: medianOf(reps.map((r) => percentile(r.frameMs, 50))),
    p95: medianOfP95(p95PerRep),
    p99: medianOf(reps.map((r) => percentile(r.frameMs, 99))),
    p95PerRep,
    spreadPct: spreadPct(p95PerRep),
    drawCalls: medianOf(reps.map((r) => maxOf(r.drawCalls ?? []))),
    // An imprecise (quantised) heap figure is recorded as such and never compared (M3).
    memoryPrecision: precise ? "precise" : "imprecise",
    ...(scope && { memoryScope: scope }),
    memoryLimit: MEMORY_LIMIT,
    ...(partial && { partial }),
    memoryMb: precise ? medianOf(reps.map((r) => r.memoryMb)) : null,
    lodChanges: maxOf(reps.map((r) => lodChanges(r.lod ?? []))),
    workerCpuPct: medianOf(reps.map((r) => r.workerCpuPct)),
    coldInitToFirstFrameMs: medianOf(reps.map((r) => r.coldInitMs)),
    atlasFromCacheMs: medianOf(reps.map((r) => r.atlasFromCacheMs)),
    peakMemoryMb: soak && precise ? maxOf(reps.flatMap((r) => r.memorySeriesMb ?? [])) : null,
    growthPct: soak && precise ? growthPct(reps[0]?.memorySeriesMb ?? []) : null,
    stageP95Ms,
    worstStage,
  };
}

/**
 * 26 §13's absolute gates for one report cell: `within gate`, `over gate`, or `not measured`
 * when the cell has no figure for it (B9's atlas until E11-S11's counters reach the page).
 */
export function gateRows(cell) {
  const s = ENGINE_SCENARIOS[cell?.scenario];
  if (!s?.gates || cell.status !== "ok") return [];
  return s.gates.map((g) => {
    const value = cell[g.metric];
    const measured = typeof value === "number" && Number.isFinite(value);
    return {
      metric: `${cell.scenario} ${g.label} <= ${g.max}${g.unit ? ` ${g.unit}` : ""} (26 §13)${s.partial ? " [partial]" : ""}`,
      value: measured ? value : null,
      max: g.max,
      status: !measured ? "not measured" : value <= g.max + 1e-9 ? "within gate" : "over gate",
    };
  });
}

/**
 * B1's scripted pan: the visible window `[from, to)` in bar indexes at `tMs`, moving left at
 * `pxPerSec` with `spacingPx` per bar, starting at the newest bar and wrapping at the oldest.
 */
export function panWindow(tMs, { bars, widthPx, spacingPx, pxPerSec = 1000 }) {
  const visible = Math.max(1, widthPx / spacingPx);
  const span = Math.max(1, bars - visible);
  const shift = ((tMs / 1000) * pxPerSec) / spacingPx;
  const to = bars - (shift % span);
  return { from: to - visible, to };
}

/** B2's scripted sweep: bar spacing from 0.1 to 50 px/bar, geometric over `durationMs`. */
export function zoomSpacing(tMs, durationMs, lo = 0.1, hi = 50) {
  const f = Math.min(1, Math.max(0, tMs / durationMs));
  return lo * Math.pow(hi / lo, f);
}
