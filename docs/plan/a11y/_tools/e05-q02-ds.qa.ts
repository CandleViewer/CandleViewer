// E05-Q02 (#262) design-system v0 axe matrix. The Storybook gate (E05-T03) runs axe at one cell (dark,
// compact) and the VR matrix (E05-T04) is pixel-only, so light and high-contrast, comfortable density and
// both motion states were never axe-checked. This driver runs axe over every story of a built Storybook
// x 3 themes x 2 densities x the motion states the story does not pin (`system` under
// prefers-reduced-motion no-preference and reduce; a story that pins `motion` runs that one only).
// Stories tagged `perf` are left out, as in VR. Ordering is by story id, then theme, density, motion.
//
// Build, then run from apps/web (its Playwright and @axe-core/playwright are the runners; the tsconfig in
// this directory maps them, no new dependency). One Playwright test per story plus a negative control that
// runs first (project `control`; the run fails as A11Y-INFRA if it does not trip):
//   pnpm --filter @candleviewer/ui run storybook:build
//   cd apps/web && A11Y_SHA=$(git rev-parse HEAD) A11Y_WORKERS=4 \
//     npx playwright test -c ../../docs/plan/a11y/_tools/e05-q02-ds.config.ts
//   node ../../docs/plan/a11y/_tools/e05-q02-merge.mjs   # stories/*.json -> results.json + summary.md
// Local: A11Y_WORKERS 2-4 (default 2). CI: split with Playwright's `--shard=i/n`, one A11Y_OUT per shard,
// then `e05-q02-merge.mjs [--strict] <out1> <out2> ...` merges them. One A11Y_OUT per shard, never shared:
// the control wipes <A11Y_OUT>/stories/ on start. The merge fails on a missing or duplicate story file,
// a wrong cell count, shards that disagree on sha or story list, and off-site requests or errored cells;
// --strict also fails on any serious/critical violation (without it violations are only reported).
// Typecheck: cd apps/web && npx tsc -p ../../docs/plan/a11y/_tools/tsconfig.json
//
// Environment: A11Y_SHA (recorded), A11Y_ONLY (comma-separated story-id substrings), A11Y_THEMES,
// A11Y_DENSITIES (comma-separated subsets), A11Y_PORT (default 4175), A11Y_WORKERS, A11Y_OUT (default
// <os temp>/e05-q02-ds). Per story writes <A11Y_OUT>/stories/<id>.json (per cell: counts by impact, rule
// ids, nodes). Network: any request to a non-loopback host is aborted and counted; the story then fails.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { test, type Browser, type Page } from "@playwright/test";

const THEMES = ["dark", "light", "high-contrast"] as const;
const DENSITIES = ["compact", "comfortable"] as const;
const MOTIONS = ["no-preference", "reduce"] as const;
const IMPACTS = ["critical", "serious", "moderate", "minor"] as const;
type Impact = (typeof IMPACTS)[number];
// The same tag set as apps/web/e2e/a11y/tags.ts (AXE_GATE_TAGS).
const AXE_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22a",
  "wcag22aa",
  "best-practice",
];
// Page-level best-practice rules that a lone component in the isolated iframe cannot satisfy (no main
// landmark, no h1, content outside a region); the screens sweep (E47) covers them.
const PAGE_LEVEL_RULES = ["landmark-one-main", "page-has-heading-one", "region"];
const STORY_TIMEOUT_MS = 20_000;
const OUT = process.env["A11Y_OUT"] ?? join(tmpdir(), "e05-q02-ds");

const subset = <T extends string>(all: readonly T[], env: string | undefined): readonly T[] => {
  const asked = (env ?? "").split(",").filter((x) => x !== "");
  return asked.length === 0 ? all : all.filter((x) => asked.includes(x));
};

interface Cell {
  readonly story: string;
  readonly theme: string;
  readonly density: string;
  readonly motion: string;
  readonly pinnedMotion: string | null;
  readonly counts: Record<Impact, number>;
  readonly violations: readonly { id: string; impact: string; nodes: number; targets: string[] }[];
  readonly incomplete: number;
  readonly error?: string;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** The story URL for one cell; the control and the matrix share it (motion left to the OS preference). */
const storyUrl = (story: string, theme: string, density: string): string =>
  `/iframe.html?id=${story}&viewMode=story` +
  `&globals=theme:${theme};density:${density};motion:system;a11y.manual:!true`;

/** Story ids from the built Storybook's index.json (read at load), perf-tagged dropped, sorted by id. */
const STATIC =
  process.env["A11Y_STATIC"] ?? resolve(process.cwd(), "../../packages/ui/storybook-static");
function readStories(): { ids: string[]; excluded: string[] } {
  const body: unknown = JSON.parse(readFileSync(join(STATIC, "index.json"), "utf8"));
  const entries = isRecord(body) && isRecord(body["entries"]) ? body["entries"] : {};
  const ids: string[] = [];
  const excluded: string[] = [];
  for (const [id, entry] of Object.entries(entries)) {
    if (!isRecord(entry) || entry["type"] !== "story") continue;
    const tags = Array.isArray(entry["tags"]) ? entry["tags"] : [];
    (tags.includes("perf") ? excluded : ids).push(id);
  }
  const only = (process.env["A11Y_ONLY"] ?? "").split(",").filter((x) => x !== "");
  const keep = (id: string): boolean => only.length === 0 || only.some((o) => id.includes(o));
  return { ids: ids.filter(keep).sort(), excluded: excluded.sort() };
}

/** The globals the story pins itself, once its render has finished (null while it has not). */
const pinnedGlobals = (): Record<string, unknown> | null => {
  const preview = (window as unknown as { __STORYBOOK_PREVIEW__?: { currentRender?: unknown } })
    .__STORYBOOK_PREVIEW__;
  const render = preview?.currentRender as
    { phase?: string; story?: { storyGlobals?: Record<string, unknown> } } | undefined;
  return render?.phase === "finished" ? (render.story?.storyGlobals ?? {}) : null;
};

async function runCell(
  page: Page,
  story: string,
  theme: string,
  density: string,
  motion: string,
): Promise<Cell> {
  const base = { story, theme, density, motion };
  const empty = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  try {
    await page.emulateMedia({ reducedMotion: motion as "reduce" | "no-preference" });
    await page.goto(storyUrl(story, theme, density), { timeout: STORY_TIMEOUT_MS });
    const handle = await page.waitForFunction(pinnedGlobals, undefined, {
      polling: 50,
      timeout: STORY_TIMEOUT_MS,
    });
    const pinned = await handle.jsonValue();
    const pin = typeof pinned?.["motion"] === "string" ? pinned["motion"] : null;
    const result = await new AxeBuilder({ page })
      .withTags(AXE_TAGS)
      .disableRules(PAGE_LEVEL_RULES)
      .analyze();
    const counts = { ...empty };
    for (const v of result.violations) {
      if (IMPACTS.includes(v.impact as Impact)) counts[v.impact as Impact] += 1;
    }
    return {
      ...base,
      pinnedMotion: pin,
      counts,
      incomplete: result.incomplete.length,
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact ?? "unknown",
        nodes: v.nodes.length,
        targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
      })),
    };
  } catch (error) {
    const message =
      error instanceof Error ? (error.message.split("\n")[0] ?? "error") : String(error);
    return {
      ...base,
      pinnedMotion: null,
      counts: empty,
      violations: [],
      incomplete: 0,
      error: message,
    };
  }
}

/** Must-trip negative control: axe has to flag a violation injected into a known story, else infra. */
async function negativeControl(page: Page, story: string): Promise<string[]> {
  const expected = ["image-alt", "button-name"];
  await page.goto(storyUrl(story, "dark", "compact"), { timeout: STORY_TIMEOUT_MS });
  await page.waitForFunction(pinnedGlobals, undefined, { polling: 50, timeout: STORY_TIMEOUT_MS });
  await page.evaluate(() => {
    const root = document.querySelector("#storybook-root") ?? document.body;
    root.insertAdjacentHTML("beforeend", '<img src="data:,"><button></button>');
  });
  const result = await new AxeBuilder({ page })
    .withTags(AXE_TAGS)
    .disableRules(PAGE_LEVEL_RULES)
    .analyze();
  const hit = result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => v.id);
  const missing = expected.filter((id) => !hit.includes(id));
  if (missing.length > 0) {
    throw new Error(`A11Y-INFRA: negative control did not trip (missing ${missing.join(", ")})`);
  }
  return expected;
}

/** A context that aborts and records every non-loopback request. */
async function isolatedPage(browser: Browser, offsite: string[]): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await context.route("**/*", (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") return route.continue();
    offsite.push(route.request().url());
    return route.abort();
  });
  return context.newPage();
}

const { ids, excluded } = readStories();
const themes = subset(THEMES, process.env["A11Y_THEMES"]);
const densities = subset(DENSITIES, process.env["A11Y_DENSITIES"]);

test("negative control", async ({ browser }) => {
  rmSync(join(OUT, "stories"), { recursive: true, force: true });
  mkdirSync(join(OUT, "stories"), { recursive: true });
  const page = await isolatedPage(browser, []);
  const first = ids[0];
  if (first === undefined)
    throw new Error("A11Y-INFRA: no stories selected; the control cannot run");
  const rules = await negativeControl(page, first);
  await page.context().close();
  const sha = process.env["A11Y_SHA"] ?? "unset";
  const manifest = {
    sha,
    stories: ids,
    excluded,
    themes,
    densities,
    motions: MOTIONS,
    negativeControl: { tripped: true, rules },
  };
  writeFileSync(join(OUT, "manifest.json"), JSON.stringify(manifest, null, 2));
});

for (const id of ids) {
  test(`story ${id}`, async ({ browser }) => {
    const offsite: string[] = [];
    const page = await isolatedPage(browser, offsite);
    const cells: Cell[] = [];
    for (const theme of themes) {
      for (const density of densities) {
        const first = await runCell(page, id, theme, density, MOTIONS[0]);
        cells.push(first);
        // A story that pins its own motion override renders the same under both OS preferences.
        if (first.pinnedMotion === null && first.error === undefined) {
          cells.push(await runCell(page, id, theme, density, MOTIONS[1]));
        }
      }
    }
    await page.context().close();
    mkdirSync(join(OUT, "stories"), { recursive: true });
    writeFileSync(
      join(OUT, "stories", `${id}.json`),
      JSON.stringify(
        { id, offsite, pinned: cells.some((c) => c.pinnedMotion !== null), cells },
        null,
        2,
      ),
    );
    const failed = cells.filter((c) => c.error !== undefined);
    if (offsite.length > 0) throw new Error(`${offsite.length} off-site request(s) were aborted`);
    if (failed.length > 0)
      throw new Error(`${failed.length} cell(s) did not render; see ${id}.json`);
  });
}
