import { mkdirSync, writeFileSync } from "node:fs";
import { test } from "@playwright/test";
import { bounded, openScreen, STEP_TIMEOUT_MS, sweep } from "./open";
import { REPORT_DIR, SCREENS } from "./screens";

const FPS = 30;
const FRAMES = 90; // 3 s window

// Gate 5 collector: relative-luminance series per frame. Each screen's <main>
// is a component; any element marked data-flash-audit="<name>" (heatmap,
// big-trade bubble, price flash - added by their tickets) is captured too.
// Screens open as the other collectors open them (open.ts), each step bounded (#5151).
test("collect flash luminance", async ({ page }) => {
  const components: Record<string, number[]> = {};
  await sweep("flash", SCREENS, async (s) => {
    await openScreen(page, s);
    const capture = page.evaluate(
      async ({ frames, fps }) => {
        const lin = (c: number): number => {
          const v = c / 255;
          return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
        };
        const lum = (el: Element): number => {
          const m = /rgba?\((\d+)[ ,]+(\d+)[ ,]+(\d+)/.exec(getComputedStyle(el).backgroundColor);
          if (!m) return 0;
          return (
            0.2126 * lin(Number(m[1])) + 0.7152 * lin(Number(m[2])) + 0.0722 * lin(Number(m[3]))
          );
        };
        const main = document.querySelector("main") ?? document.body;
        const marked = Array.from(document.querySelectorAll("[data-flash-audit]"));
        const out: Record<string, number[]> = { __main: [] };
        for (const m of marked) out[m.getAttribute("data-flash-audit") ?? "unnamed"] = [];
        for (let i = 0; i < frames; i++) {
          out["__main"]?.push(lum(main));
          for (const m of marked)
            out[m.getAttribute("data-flash-audit") ?? "unnamed"]?.push(lum(m));
          await new Promise((r) => setTimeout(r, 1000 / fps));
        }
        return out;
      },
      { frames: FRAMES, fps: FPS },
    );
    const windowMs = (FRAMES / FPS) * 1000;
    const what = `the ${FRAMES}-frame luminance capture`;
    const series = await bounded(what, windowMs + STEP_TIMEOUT_MS, capture);
    for (const [k, v] of Object.entries(series)) {
      components[k === "__main" ? `screen:${s.id}` : `component:${k}`] = v;
    }
  });
  mkdirSync(REPORT_DIR, { recursive: true });
  writeFileSync(`${REPORT_DIR}/flash.json`, JSON.stringify({ fps: FPS, components }));
});
