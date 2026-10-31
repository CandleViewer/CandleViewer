// E05-Q02 (#262) design-system v0 axe matrix. The Storybook gate (E05-T03) runs axe at one cell (dark,
// compact) and the VR matrix (E05-T04) is pixel-only, so light and high-contrast, comfortable density and
// both motion states were never axe-checked. This driver runs axe over every story of a built Storybook
// x 3 themes x 2 densities x the motion states the story does not pin (`system` under
// prefers-reduced-motion no-preference and reduce; a story that pins `motion` runs that one only).
// Stories tagged `perf` are left out, as in VR. Ordering is by story id, then theme, density, motion.
//
// Build, then run from apps/web (its Playwright and @axe-core/playwright are the runners; the tsconfig in
// this directory maps them, no new dependency):
//   pnpm --filter @candleviewer/ui run storybook:build
//   cd apps/web && A11Y_SHA=$(git rev-parse HEAD) \
//     npx playwright test -c ../../docs/plan/a11y/_tools/e05-q02-ds.config.ts
// Typecheck: cd apps/web && npx tsc -p ../../docs/plan/a11y/_tools/tsconfig.json
//
// Environment: A11Y_SHA (recorded), A11Y_ONLY (comma-separated story-id substrings), A11Y_THEMES,
// A11Y_DENSITIES (comma-separated subsets), A11Y_PORT (default 4175), A11Y_OUT (default <os temp>/
// e05-q02-ds). Writes <A11Y_OUT>/results.json (per story x cell: counts by impact, rule ids, nodes) and
// summary.md. Network: any request to a non-loopback host is aborted and counted; the run fails if any.
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { test, type Page } from "@playwright/test";

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

/** Story ids and tags from index.json, perf-tagged stories dropped, sorted by id. */
async function readStories(page: Page): Promise<{ ids: string[]; excluded: string[] }> {
  const res = await page.request.get("/index.json");
  const body: unknown = await res.json();
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
    await page.goto(
      `/iframe.html?id=${story}&viewMode=story` +
        `&globals=theme:${theme};density:${density};motion:system;a11y.manual:!true`,
      { timeout: STORY_TIMEOUT_MS },
    );
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
  await page.goto(`/iframe.html?id=${story}&viewMode=story&globals=theme:dark;density:compact`, {
    timeout: STORY_TIMEOUT_MS,
  });
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

test("E05-Q02 design-system axe matrix", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const offsite: string[] = [];
  await context.route("**/*", (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") return route.continue();
    offsite.push(route.request().url());
    return route.abort();
  });
  const page = await context.newPage();
  const { ids, excluded } = await readStories(page);
  const cells: Cell[] = [];
  const control = ids[0] === undefined ? [] : await negativeControl(page, ids[0]);
  for (const id of ids) {
    for (const theme of subset(THEMES, process.env["A11Y_THEMES"])) {
      for (const density of subset(DENSITIES, process.env["A11Y_DENSITIES"])) {
        const first = await runCell(page, id, theme, density, MOTIONS[0]);
        cells.push(first);
        // A story that pins its own motion override renders the same under both OS preferences.
        if (first.pinnedMotion === null && first.error === undefined) {
          cells.push(await runCell(page, id, theme, density, MOTIONS[1]));
        }
      }
    }
  }
  await context.close();

  const total = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  for (const c of cells) for (const i of IMPACTS) total[i] += c.counts[i];
  const failed = cells.filter((c) => c.error !== undefined);
  mkdirSync(OUT, { recursive: true });
  writeFileSync(
    join(OUT, "results.json"),
    JSON.stringify(
      {
        sha: process.env["A11Y_SHA"] ?? "unset",
        stories: ids.length,
        excluded,
        negativeControl: { tripped: control.length > 0, rules: control },
        total,
        offsite,
        cells,
      },
      null,
      2,
    ),
  );
  const rows = cells
    .filter((c) => c.error !== undefined || IMPACTS.some((i) => c.counts[i] > 0))
    .map(
      (c) =>
        `| ${c.story} | ${c.theme} | ${c.density} | ${c.motion} | ` +
        `${IMPACTS.map((i) => c.counts[i]).join(" / ")} | ` +
        `${c.error ?? [...new Set(c.violations.map((v) => v.id))].join(", ")} |`,
    );
  writeFileSync(
    join(OUT, "summary.md"),
    [
      `Stories ${ids.length} (excluded perf: ${excluded.length}), cells ${cells.length}, ` +
        `errored ${failed.length}, off-site requests ${offsite.length}`,
      `Violations: ${IMPACTS.map((i) => `${i} ${total[i]}`).join(", ")}`,
      `Negative control: tripped (${control.join(", ")})`,
      `Disabled page-level rules: ${PAGE_LEVEL_RULES.join(", ")} (a lone component in the isolated ` +
        "iframe has no main landmark, h1 or region; the screens sweep, E47, covers them)",
      "",
      "| story | theme | density | motion | crit / ser / mod / min | rules or error |",
      "|---|---|---|---|---|---|",
      ...rows,
      "",
    ].join("\n"),
  );
  test.info().annotations.push({ type: "out", description: OUT });
  if (offsite.length > 0) throw new Error(`${offsite.length} off-site request(s) were aborted`);
  if (failed.length > 0)
    throw new Error(`${failed.length} cell(s) did not render; see results.json`);
});
