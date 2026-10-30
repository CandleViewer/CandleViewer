/**
 * The capture settings of the visual-regression suite (E05-T04, ADR-0019): every value a baseline depends on,
 * in one place. `test/vr/config.test.ts` pins them; changing one re-baselines the whole matrix.
 */
import { fileURLToPath } from "node:url";
import type { BrowserContextOptions } from "playwright/test";

/** packages/ui: the scripts run here and `storybook:build` writes `storybook-static/` here. */
export const PACKAGE_DIR = fileURLToPath(new URL("..", import.meta.url));
/** The built Storybook the capture serves, and its story index (the matrix's only source). */
export const STATIC_DIR = fileURLToPath(new URL("../storybook-static", import.meta.url));
export const STORYBOOK_INDEX = fileURLToPath(
  new URL("../storybook-static/index.json", import.meta.url),
);
/** The token source: its `font.family.*` values are the faces the capture must draw (fonts.ts). */
export const TOKEN_SOURCE = fileURLToPath(
  new URL("../tokens/primitives.tokens.json", import.meta.url),
);
/** One PNG per cell, `{story}--{theme}--{density}.png`, committed (no LFS in this repository). */
export const BASELINE_DIR = fileURLToPath(new URL("./baselines", import.meta.url));

/** The static Storybook is served on loopback only (C-12.9); the dev server keeps 6006. */
export const PORT = 6007;
export const ORIGIN = `http://127.0.0.1:${PORT}`;

/**
 * ADR-0019's tolerance, documented as the ticket asks: a cell fails when more pixels differ, by more than
 * pixelmatch's colour distance of 0.2 (Playwright's default, written out), than 2% of its capture or 25,
 * whichever is smaller (Playwright takes the smaller of `maxDiffPixels` and the ratio's count). The capture
 * is clipped to what the story paints (clip.ts), so the ratio is a share of the component; the cap holds a
 * capture that is still page-sized (a layout drawn edge to edge) to 25 pixels, not the 41,000 of 2% of
 * 2 Mpx. Two compare runs on an unchanged head found no cell past it, and a 1 px change still fails
 * every Button cell, overlays included (ADR-0019, Validation).
 */
export const TOLERANCE = { maxDiffPixelRatio: 0.02, maxDiffPixels: 25, threshold: 0.2 } as const;

/**
 * Date.now() and new Date() in every story, through the page probe (probe.ts): a story that shows "now"
 * renders the same digits each run. Only `Date` is held, and only outside a play function: while a play
 * runs it moves with real time from this instant, as in the storybook job, so a countdown it waits on can
 * count. Timers and frames always run as the browser runs them.
 */
export const FROZEN_TIME = "2026-10-27T14:02:00Z";

/**
 * The OS reduced-motion preference the page sees (`prefers-reduced-motion`). None while the story renders
 * and plays, as in the storybook job where each play is proven: under `reduce`, E05-T02's CSS gives every
 * style change a 0.01 ms transition, so a play that reads a style right after a step would read the old
 * value. `reduce` for the shot, which the runtime (the cells ask for motion `system`) writes as
 * `data-motion="reduce"`: animation stops through the reduced-motion attribute, not a capture hack.
 */
export const REDUCED_MOTION = { play: "no-preference", capture: "reduce" } as const;

/**
 * The settle rule, after Storybook finished a story and before the clip is measured: a timer due within
 * 1 s fires first (a tooltip's 300 ms hover delay, a search box's 500 ms settle), then the page must hold
 * still, with no DOM mutation and no such timer pending, for 2 animation frames; then it is frozen. A page
 * still changing after 3 s fails the cell, naming what moved. A later timer (a 2 s "Copied" reset, a 5 s
 * toast) is frozen before it fires, so the capture shows the state the story ends in.
 */
export const SETTLE = { horizonMs: 1000, quietFrames: 2, capMs: 3000 } as const;

/**
 * The browser context of every cell: the brief's 1920x1080 primary target at one device pixel per CSS pixel,
 * a fixed locale and time zone for number and date formats, no reduced-motion preference until the capture
 * asks for one (`REDUCED_MOTION`), and no network. Every request except the local
 * Storybook's goes to a closed loopback port, so no font (or anything else) is ever fetched from outside; the
 * spec also fails a cell that asks, naming the URL.
 */
export const CONTEXT = {
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  locale: "en-US",
  timezoneId: "UTC",
  reducedMotion: REDUCED_MOTION.play,
  proxy: { server: "http://127.0.0.1:9", bypass: "127.0.0.1" },
} as const satisfies BrowserContextOptions;
