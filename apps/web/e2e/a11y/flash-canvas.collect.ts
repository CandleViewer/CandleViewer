import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "@playwright/test";
import { REPORT_DIR } from "./screens";

// Gate 5, realistic fixture (WCAG 2.3.1): replays the chart-engine bench
// synthetic heatmap tape (seeded, 200 depth levels) plus big-trade bubbles at
// >= 20 updates/s for >= 5 s onto a canvas and samples the CANVAS region's mean
// relative luminance (not <main>). A deliberately strobing scene is captured
// separately as a negative fixture; the job asserts the gate trips on it.
const UPDATES_PER_S = 20;
const SECONDS = 6;
const SAMPLE_HZ = 60;
// Playwright runs with cwd = apps/web.
const FIXTURE = pathToFileURL(
  resolve(process.cwd(), "../../packages/chart-engine/bench/fixtures/heatmap.mjs"),
).href;

type Scene = "heatmap" | "bubbles" | "strobe";

async function capture(
  page: import("@playwright/test").Page,
  scene: Scene,
  columns: number[][],
): Promise<{ lum: number[]; updates: number; seconds: number }> {
  await page.setContent('<canvas id="c" width="320" height="200"></canvas>');
  return page.evaluate(
    async ({ scene, columns, ups, secs, hz }) => {
      const cv = document.getElementById("c") as HTMLCanvasElement;
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      if (!ctx) throw new Error("no 2d context");
      const lin = (c: number): number => {
        const v = c / 255;
        return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      };
      const meanLum = (): number => {
        const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
        let s = 0;
        for (let i = 0; i < d.length; i += 16) {
          s += 0.2126 * lin(d[i] ?? 0) + 0.7152 * lin(d[i + 1] ?? 0) + 0.0722 * lin(d[i + 2] ?? 0);
        }
        return s / (d.length / 16);
      };
      let seed = 12345;
      const rnd = (): number => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
      let update = 0;
      const paint = (): void => {
        if (scene === "strobe") {
          ctx.fillStyle = update % 2 === 0 ? "#000" : "#fff";
          ctx.fillRect(0, 0, cv.width, cv.height);
        } else if (scene === "heatmap") {
          const col = columns[update % columns.length] ?? [];
          ctx.drawImage(cv, -2, 0); // scroll left, new column on the right
          for (let y = 0; y < cv.height; y++) {
            const v = col[Math.floor((y / cv.height) * col.length)] ?? 0;
            const a = Math.min(1, Math.abs(v) / 60);
            ctx.fillStyle =
              v >= 0
                ? `rgb(0,${Math.round(40 + 160 * a)},${Math.round(80 * a)})`
                : `rgb(${Math.round(40 + 160 * a)},0,${Math.round(40 * a)})`;
            ctx.fillRect(cv.width - 2, y, 2, 1);
          }
        } else {
          ctx.fillStyle = "rgba(10,10,20,0.25)";
          ctx.fillRect(0, 0, cv.width, cv.height);
          for (let i = 0; i < 6; i++) {
            ctx.beginPath();
            ctx.fillStyle = rnd() > 0.5 ? "#26a69a" : "#ef5350";
            ctx.arc(rnd() * cv.width, rnd() * cv.height, 4 + rnd() * 16, 0, 6.283);
            ctx.fill();
          }
        }
        update++;
      };
      ctx.fillStyle = "#0b0e14";
      ctx.fillRect(0, 0, cv.width, cv.height);
      const lum: number[] = [];
      const t0 = performance.now();
      const upTimer = setInterval(paint, 1000 / ups);
      await new Promise<void>((resolve) => {
        const sample = (): void => {
          lum.push(meanLum());
          if (performance.now() - t0 >= secs * 1000) resolve();
          else setTimeout(sample, 1000 / hz);
        };
        sample();
      });
      clearInterval(upTimer);
      return { lum, updates: update, seconds: (performance.now() - t0) / 1000 };
    },
    { scene, columns, ups: UPDATES_PER_S, secs: SECONDS, hz: SAMPLE_HZ },
  );
}

test("collect canvas flash luminance (realistic replay + negative)", async ({ page }) => {
  const mod = (await import(FIXTURE)) as {
    generateHeatmapColumns: (o: { seed: number; durationMs: number }) => { levels: Int32Array }[];
  };
  const tape = mod.generateHeatmapColumns({ seed: 47, durationMs: 20_000 });
  const columns = tape.map((c) => Array.from(c.levels));
  const out: Record<string, number[]> = {};
  let fps = SAMPLE_HZ;
  for (const scene of ["heatmap", "bubbles"] as const) {
    const r = await capture(page, scene, columns);
    if (r.updates / r.seconds < UPDATES_PER_S * 0.8 || r.seconds < 5)
      throw new Error(`A11Y-INFRA replay too slow: ${r.updates} updates in ${r.seconds}s`);
    out[`canvas:${scene}`] = r.lum;
    fps = r.lum.length / r.seconds;
  }
  const neg = await capture(page, "strobe", columns);
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(`${REPORT_DIR}/flash-canvas.json`, JSON.stringify({ fps, components: out }));
  writeFileSync(
    `${REPORT_DIR}/flash-negative.json`,
    JSON.stringify({ fps: neg.lum.length / neg.seconds, components: { "canvas:strobe": neg.lum } }),
  );
});
