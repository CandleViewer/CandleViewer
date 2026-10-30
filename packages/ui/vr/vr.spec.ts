/**
 * The visual-regression suite (E05-T04, ADR-0019): one test per matrix cell, titled by its key, comparing
 * the story's capture with `baselines/{key}.png`, plus the audit that every cell has a baseline and every
 * baseline a cell. Run it with `vr` (compare) or `vr:update` (packages/ui/README.md, Visual regression).
 */
import { existsSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { expect, test as base, type Page, type Request } from "playwright/test";
import { clipFor, collectPaint, stableClip, type Clip } from "./clip.js";
import {
  auditBaselines,
  cellGlobals,
  expectedMotion,
  readMatrix,
  readShard,
  shardCells,
  storyPath,
} from "./matrix.js";
import {
  describeFaces,
  fontProblems,
  fontSample,
  readTokenFamilies,
  type DrawnFace,
} from "./fonts.js";
import { cellProblem, NOT_CAPTURED, settleForCapture, storyState } from "./page.js";
import { freezeCell, installProbe, nextFrames, settleCell } from "./probe.js";
import {
  BASELINE_DIR,
  CONTEXT,
  FROZEN_TIME,
  ORIGIN,
  REDUCED_MOTION,
  SETTLE,
  STORYBOOK_INDEX,
  TOKEN_SOURCE,
} from "./settings.js";

const matrix = readMatrix(STORYBOOK_INDEX);
/** This run's shard (the vr job's `VR_SHARD`), or none: the whole matrix (the update dispatch, a local run). */
const shard = readShard(process.env["VR_SHARD"]);

/** Same-origin, inline or blank: anything else would be a fetch from outside the local Storybook. */
const local = (url: string): boolean =>
  url.startsWith(`${ORIGIN}/`) || /^(?:data|blob|about):/.test(url);

/**
 * One context per worker, so the HTTP cache stays warm across cells; each cell is a fresh navigation, and
 * every document starts with the page probe (probe.ts): empty storage, the frozen `Date`, its timers tracked.
 */
const test = base.extend<object, { storyPage: Page }>({
  storyPage: [
    async ({ browser }, use) => {
      const context = await browser.newContext(CONTEXT);
      await context.addInitScript(installProbe, { now: Date.parse(FROZEN_TIME) });
      await use(await context.newPage());
      await context.close();
    },
    { scope: "worker" },
  ],
});

/** Fails the cell before its capture, naming why; the job summary lists it apart from the diffs. */
function notCaptured(reason: string): never {
  test.info().annotations.push({ type: NOT_CAPTURED, description: reason });
  throw new Error(reason);
}

/**
 * The pinned fonts, once per shard: Chromium draws a sample of each token family and reports, through the
 * DevTools protocol, the faces it used. Anything but exactly Inter and JetBrains Mono (a fontconfig
 * substitute, a fallback face) fails here by name, before a cell is blamed (CI-A11Y-008).
 */
test("Chromium draws the token families in their own faces", async ({ storyPage: page }) => {
  const families = readTokenFamilies(TOKEN_SOURCE);
  await page.setContent(fontSample(families));
  const cdp = await page.context().newCDPSession(page);
  try {
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    const { root } = await cdp.send("DOM.getDocument");
    const drawn: Record<string, DrawnFace[]> = {};
    for (const [index, token] of Object.keys(families).entries()) {
      const selector = `#family-${String(index)}`;
      const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector });
      drawn[token] = (await cdp.send("CSS.getPlatformFontsForNode", { nodeId })).fonts;
    }
    test.info().annotations.push({ type: "fonts", description: describeFaces(drawn) });
    expect(fontProblems(families, drawn), "the pinned fonts draw, not a substitute").toEqual([]);
  } finally {
    await cdp.detach();
  }
});

/** A capture area as a failure names it. */
const area = ({ x, y, width, height }: Clip): string => `${width}x${height} at ${x},${y}`;

for (const cell of shardCells(matrix.cells, shard)) {
  test(cell.key, async ({ storyPage: page }) => {
    const offsite: string[] = [];
    const record = (request: Request): void => {
      if (!local(request.url())) offsite.push(request.url());
    };
    page.on("request", record);
    try {
      // The play runs as in the storybook job: no reduced-motion preference (the last cell asked for one).
      await page.emulateMedia({ reducedMotion: REDUCED_MOTION.play });
      await page.goto(ORIGIN + storyPath(cell));
      const handle = await page.waitForFunction(storyState, undefined, { polling: 50 });
      const state = await handle.jsonValue();
      if (state === null) throw new Error("waitForFunction resolved on no state"); // it waits for one
      // A play that threw still reaches Storybook's `finished`: the cell fails by name, never shot.
      const problem = cellProblem(state);
      if (problem !== undefined) notCaptured(problem);
      const asked = cellGlobals(cell);
      const { theme, density, motion } = state.globals;
      if (theme !== asked.theme || density !== asked.density || motion !== asked.motion) {
        notCaptured(`Storybook did not take the cell's globals: ${JSON.stringify(state.globals)}`);
      }
      // The shot is taken under reduced motion: E05-T02's runtime writes `data-motion="reduce"` from the
      // OS preference. Overlays and tooltips open late: their timers fire and the page holds still, then
      // it is frozen.
      await page.emulateMedia({ reducedMotion: REDUCED_MOTION.capture });
      await page.evaluate(settleForCapture);
      const settled = await page.evaluate(settleCell, SETTLE);
      if (!settled.ok) notCaptured(`did not settle: ${settled.reason}`);
      await page.evaluate(freezeCell);
      const root = await page.evaluate(settleForCapture);
      const reduced = expectedMotion(state.pinned);
      if (root.motion !== reduced) {
        notCaptured(`E05-T02's runtime wrote data-motion="${root.motion}", not "${reduced}"`);
      }
      if (root.theme !== cell.theme || root.density !== cell.density) {
        // A story that pins its own globals, or whose play function switches them, shows what it sets.
        const description = `renders theme=${root.theme}, density=${root.density}`;
        test.info().annotations.push({ type: "own-globals", description });
      }
      // Nothing is fetched from outside the local Storybook, fonts included.
      if (offsite.length > 0) {
        const more = offsite.length > 1 ? ` and ${offsite.length - 1} more` : "";
        notCaptured(`fetched from outside the local Storybook: ${String(offsite[0])}${more}`);
      }
      // The clip from two measures two frames apart that agree, so a box still moving is never shot.
      const { clip, moving } = await stableClip(
        async () => clipFor(await page.evaluate(collectPaint)),
        () => page.evaluate(nextFrames, 2),
        3,
      );
      if (moving.length > 0)
        notCaptured(`the capture area kept moving: ${moving.map(area).join(", ")}`);
      await expect(page).toHaveScreenshot(`${cell.key}.png`, { clip, fullPage: true });
    } finally {
      page.off("request", record);
    }
  });
}

/** The first names of a list, then a count of the rest. */
const some = (names: readonly string[]): string =>
  names.slice(0, 20).join(", ") + (names.length > 20 ? `, and ${names.length - 20} more` : "");

// The audit runs once: in the first shard, or in an unsharded run.
if (shard === undefined || shard.current === 1) {
  test("every cell has a baseline and every baseline a cell", () => {
    const files = existsSync(BASELINE_DIR) ? readdirSync(BASELINE_DIR) : [];
    const { missing, orphaned } = auditBaselines(matrix.cells, files);
    if (test.info().config.updateSnapshots !== "none") {
      // An update run writes the missing cells as it goes, and deletes what no cell owns.
      for (const file of orphaned) rmSync(join(BASELINE_DIR, file));
      test.info().annotations.push({ type: "pruned", description: some(orphaned) || "none" });
      return;
    }
    expect(missing.length, `cells with no baseline: ${some(missing)}`).toBe(0);
    expect(orphaned.length, `baselines no cell owns: ${some(orphaned)}`).toBe(0);
  });
}
