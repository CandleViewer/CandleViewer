import { expect, test } from "@playwright/test";

// E22-S01 (#714) BQ-215 (RULED): the sole proof that SCR-053 holds >= 55 fps at 2 000 prints/s
// with <= 60 rows in the DOM (US-BIG-001 NFR; D04 G-5). The harness page (flag build only) feeds
// a seeded 2 000 prints/s through the panel's real ingest, ring, writer and controller; this spec
// samples the page's own rAF intervals for 20 s after a 2 s warm-up and asserts the p95 interval
// is at most 18.2 ms (1 000 / 55), the row nodes stay at or under 60, and every injected print
// reached the ring (none dropped). It prints the numbers for the PR, with the BQ-218 ladder's rung
// at the end and the highest seen in the sample: a pass at rung 2 writes rows every 2nd frame, so
// the rung is part of the evidence. It is recorded, not asserted: the ruling lets rungs 1-2 run
// on measured overruns and asks for rung 3 only below 55 fps. E22-Q03 keeps the CI bench.

const WARM_UP_MS = 2_000;
const SAMPLE_MS = 20_000;
const P95_BUDGET_MS = 1_000 / 55;

interface Sample {
  readonly intervals: number[];
  readonly maxRows: number;
  readonly maxRung: number;
  readonly rung: number;
  readonly injected: number;
  readonly appended: number;
  readonly ringLength: number;
  readonly workP95Ms: number;
  readonly maxIngestMs: number;
}

test("SCR-053 sustains 55 fps at 2 000 prints/s with at most 60 rows", async ({ page }) => {
  await page.goto("/__dev/tape?rate=2000&seed=577");
  await expect(page.getByRole("grid", { name: "Tape BTCUSDT" })).toBeVisible();
  const sample = (await page.evaluate(
    async ({ warmUp, span }) => {
      const probe = window.__cvTapeHarness;
      if (probe === undefined) throw new Error("no tape harness on this page");
      // The warm-up is a real-time wait by design: the spec measures the browser's own frame
      // clock, which a fake timer would replace (C-13.7 covers unit tests, not this probe).
      await new Promise((r) => setTimeout(r, warmUp));
      const intervals: number[] = [];
      let maxRows = 0;
      let maxRung = 0;
      await new Promise<void>((done) => {
        let last = -1;
        const end = performance.now() + span;
        const tick = (t: number): void => {
          if (last >= 0) intervals.push(t - last);
          last = t;
          maxRows = Math.max(maxRows, probe.rows());
          maxRung = Math.max(maxRung, probe.rung());
          if (t < end) requestAnimationFrame(tick);
          else done();
        };
        requestAnimationFrame(tick);
      });
      return {
        intervals,
        maxRows,
        maxRung,
        rung: probe.rung(),
        injected: probe.injected(),
        appended: probe.appended(),
        ringLength: probe.ringLength(),
        workP95Ms: probe.workP95Ms(),
        maxIngestMs: probe.maxIngestMs(),
      };
    },
    { warmUp: WARM_UP_MS, span: SAMPLE_MS },
  )) as Sample;
  const sorted = [...sample.intervals].sort((a, b) => a - b);
  const p95 = sorted[Math.floor(sorted.length * 0.95)] ?? Infinity;
  const mean = sorted.reduce((s, v) => s + v, 0) / Math.max(1, sorted.length);
  const result = {
    frames: sorted.length,
    p95IntervalMs: Number(p95.toFixed(2)),
    meanIntervalMs: Number(mean.toFixed(2)),
    fps: Number((1_000 / mean).toFixed(1)),
    maxRows: sample.maxRows,
    rung: sample.rung,
    maxRung: sample.maxRung,
    injected: sample.injected,
    appended: sample.appended,
    ringLength: sample.ringLength,
    panelWorkP95Ms: Number(sample.workP95Ms.toFixed(2)),
    maxIngestMs: Number(sample.maxIngestMs.toFixed(2)),
  };
  console.log(`tape-2000 ${JSON.stringify(result)}`);
  expect(p95).toBeLessThanOrEqual(P95_BUDGET_MS);
  expect(sample.maxRows).toBeLessThanOrEqual(60);
  expect(sample.appended).toBe(sample.injected); // the ring took every print the feed sent
  expect(sample.ringLength).toBe(Math.min(sample.injected, 10_000));
});
