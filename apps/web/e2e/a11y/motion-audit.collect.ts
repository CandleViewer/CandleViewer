import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { test } from "@playwright/test";
import { REPORT_DIR } from "./screens";

// E47-Q05 motion/flash audit (WCAG 2.3.1), frame-capture half. Each DECLARED region (an FR-2
// 341 x 256 CSS px rectangle, never the whole viewport) is captured per frame off a canvas and
// reduced to one relative-luminance sample, with the shared color-math.mjs implementation. Frames
// are discarded as they are reduced: only the luminance series reaches the report. tools/a11y/
// motion_audit.py decides. Only the synthetic known-bad (6 Hz) and known-good (1 Hz) components are
// captured here; real surfaces are `pending <ticket>` rows there until they are built.
const FPS = 60;
const SECONDS = 5;
const VIEWPORT = [1280, 800] as const;
const RECT = [100, 80, 341, 256] as const; // x, y, w, h: D08 FR-2
// Repo root from this file (apps/web/e2e/a11y), independent of the runner's cwd.
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const COLOR_MATH = pathToFileURL(resolve(ROOT, "tools/contrast/color-math.mjs")).href;

type Histogram = Record<string, number>; // "#rrggbb" -> pixel count in the region

// Deterministic: frame i is drawn from i alone (no timers, no wall clock); `hz` full cycles/s.
async function captureRegion(
  page: import("@playwright/test").Page,
  hz: number,
): Promise<Histogram[]> {
  await page.setContent(`<canvas id="c" width="${VIEWPORT[0]}" height="${VIEWPORT[1]}"></canvas>`);
  return page.evaluate(
    ({ hz, fps, frames, rect }) => {
      const cv = document.getElementById("c") as HTMLCanvasElement;
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      if (!ctx) throw new Error("no 2d context");
      const [x, y, w, h] = rect as [number, number, number, number];
      const half = fps / hz / 2;
      const hex = (n: number): string => n.toString(16).padStart(2, "0");
      const out: Record<string, number>[] = [];
      for (let i = 0; i < frames; i++) {
        ctx.fillStyle = "#101010"; // static surround: the flash must be found inside the region
        ctx.fillRect(0, 0, cv.width, cv.height);
        ctx.fillStyle = Math.floor(i / half) % 2 ? "#ffffff" : "#000000";
        ctx.fillRect(x, y, w, h);
        const d = ctx.getImageData(x, y, w, h).data;
        const hist: Record<string, number> = {};
        for (let p = 0; p < d.length; p += 4) {
          const k = `#${hex(d[p] ?? 0)}${hex(d[p + 1] ?? 0)}${hex(d[p + 2] ?? 0)}`;
          hist[k] = (hist[k] ?? 0) + 1;
        }
        out.push(hist);
      }
      return out;
    },
    { hz, fps: FPS, frames: FPS * SECONDS, rect: RECT },
  );
}

test("collect motion-audit luminance (synthetic 6 Hz known-bad, 1 Hz known-good)", async ({
  page,
}) => {
  const { relativeLuminance } = (await import(COLOR_MATH)) as {
    relativeLuminance: (hex: string) => number;
  };
  const lumOf = (frames: Histogram[]): number[] =>
    frames.map((hist) => {
      let sum = 0;
      let n = 0;
      for (const [hex, count] of Object.entries(hist)) {
        sum += relativeLuminance(hex) * count;
        n += count;
      }
      if (n !== RECT[2] * RECT[3]) throw new Error("A11Y-INFRA region capture is not the rect");
      return sum / n;
    });
  const regions: Record<string, { rect: readonly number[]; luminance: number[] }> = {};
  for (const [id, hz] of [
    ["synthetic-6hz", 6],
    ["synthetic-1hz", 1],
  ] as const) {
    regions[id] = { rect: RECT, luminance: lumOf(await captureRegion(page, hz)) };
  }
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(
    `${REPORT_DIR}/motion-audit.json`,
    JSON.stringify({ fps: FPS, viewport: VIEWPORT, regions }),
  );
});
