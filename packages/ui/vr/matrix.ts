/**
 * The visual-regression matrix (E05-T04): every story of the built Storybook x 3 themes x 2 densities, each
 * cell keyed `{story}--{theme}--{density}` so that a missing baseline is named, never skipped silently.
 */
import { existsSync, readFileSync } from "node:fs";
import { DENSITIES, THEMES, type DensityName, type ThemeName } from "../src/theme/store.js";

/** A story entry of `index.json` (`type: "story"`; a docs entry is a page, not a story). */
export interface Story {
  readonly id: string;
  readonly tags: readonly string[];
}

/** A story the matrix leaves out, and why (the job summary prints both). */
export interface Exclusion {
  readonly id: string;
  readonly reason: string;
}

export interface Cell {
  readonly key: string;
  readonly story: string;
  readonly theme: ThemeName;
  readonly density: DensityName;
}

export interface Matrix {
  readonly stories: readonly Story[];
  readonly excluded: readonly Exclusion[];
  readonly cells: readonly Cell[];
}

/** The E05-T03 toolbar globals a cell sets. */
export interface CellGlobals {
  readonly theme: ThemeName;
  readonly density: DensityName;
  readonly motion: "system";
}

/** Story tags the matrix leaves out, each with its reason. Nothing else is ever left out. */
export const EXCLUDED_TAGS: Readonly<Record<string, string>> = {
  perf: "a wall-clock benchmark, which the storybook gate skips too",
};

/**
 * Storybook's sanitised `{title}--{name}`: lower-case words joined by single hyphens on each side of `--`.
 * Anything else could not name a PNG portably, or would make a cell key ambiguous, so it fails loudly.
 */
const STORY_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*--[a-z0-9]+(?:-[a-z0-9]+)*$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** The stories of a parsed `index.json`, sorted by id. Throws, naming the entry, on anything unexpected. */
export function parseStoryIndex(index: unknown): Story[] {
  const entries = isRecord(index) ? index["entries"] : undefined;
  if (!isRecord(entries)) throw new Error("index.json has no `entries` object");
  const stories: Story[] = [];
  for (const [id, entry] of Object.entries(entries)) {
    if (!isRecord(entry) || entry["id"] !== id)
      throw new Error(`index.json entry ${id} is malformed`);
    if (entry["type"] === "docs") continue;
    if (entry["type"] !== "story") throw new Error(`index.json entry ${id} has an unknown type`);
    if (!STORY_ID.test(id)) throw new Error(`story ${id}: its id cannot key a snapshot file`);
    const tags = entry["tags"] ?? [];
    if (!Array.isArray(tags) || !tags.every((tag) => typeof tag === "string")) {
      throw new Error(`story ${id}: its tags are not a list of strings`);
    }
    stories.push({ id, tags });
  }
  if (stories.length === 0)
    throw new Error("index.json lists no story: the matrix would check nothing");
  return stories.sort((a, b) => (a.id < b.id ? -1 : 1));
}

export const cellKey = (story: string, theme: ThemeName, density: DensityName): string =>
  `${story}--${theme}--${density}`;

/** Every story that carries no excluded tag x every theme x every density, in that order. */
export function buildMatrix(stories: readonly Story[]): Matrix {
  const excluded: Exclusion[] = [];
  const kept: Story[] = [];
  for (const story of stories) {
    const tag = story.tags.find((name) => Object.hasOwn(EXCLUDED_TAGS, name));
    if (tag === undefined) kept.push(story);
    else excluded.push({ id: story.id, reason: `${tag}: ${EXCLUDED_TAGS[tag]}` });
  }
  const cells = kept.flatMap(({ id }) =>
    THEMES.flatMap((theme) =>
      DENSITIES.map((density) => ({ key: cellKey(id, theme, density), story: id, theme, density })),
    ),
  );
  return { stories: kept, excluded, cells };
}

/** One shard of the matrix, `current` of `total` (the vr job's `VR_SHARD`, "k/n"). */
export interface Shard {
  readonly current: number;
  readonly total: number;
}

/** `VR_SHARD` as "k/n" with 1 <= k <= n; unset or empty is the whole matrix. Anything else throws, naming it. */
export function readShard(value: string | undefined): Shard | undefined {
  if (value === undefined || value === "") return undefined;
  const match = /^(\d+)\/(\d+)$/.exec(value);
  const current = Number(match?.[1]);
  const total = Number(match?.[2]);
  if (match === null || total < 1 || current < 1 || current > total) {
    throw new Error(`VR_SHARD="${value}" is not k/n with 1 <= k <= n`);
  }
  return { current, total };
}

/**
 * A shard's cells: every `total`-th cell of the matrix, from the `current`-th, so each shard samples every
 * story family and a story's six cells go to six shards. Playwright's own `--shard` cuts contiguous ranges of
 * the sorted matrix, which put a whole slow family in one shard (the skeletons' finite sweep, which
 * Storybook waits out before `finished`) and held that shard over its budget.
 */
export function shardCells(cells: readonly Cell[], shard: Shard | undefined): Cell[] {
  if (shard === undefined) return [...cells];
  return cells.filter((_, index) => index % shard.total === shard.current - 1);
}

/** The matrix of a built Storybook, from its `index.json`. */
export function readMatrix(indexPath: string): Matrix {
  if (!existsSync(indexPath)) {
    throw new Error(
      `${indexPath} is missing: run build:tokens, then storybook:build, in packages/ui`,
    );
  }
  return buildMatrix(parseStoryIndex(JSON.parse(readFileSync(indexPath, "utf-8"))));
}

/**
 * The toolbar globals a cell asks for: its theme and density, and motion `system`, so E05-T02's runtime
 * follows the OS preference the capture emulates: none while the play runs, `reduce` for the shot.
 */
export const cellGlobals = ({ theme, density }: Cell): CellGlobals => ({
  theme,
  density,
  motion: "system",
});

/**
 * A cell's story in the isolated iframe (no Storybook chrome), its globals set the way E05-T03's toolbars
 * set them, in the URL. With `motion:system`, E05-T02's runtime writes `data-motion` from the OS
 * preference: the play runs as in the storybook job, and once the capture emulates `reduce` the runtime
 * writes `data-motion="reduce"` and its CSS stops animation. `a11y.manual` keeps the a11y addon from
 * running axe in the page while it is captured (the storybook job runs axe).
 */
export function storyPath(cell: Cell): string {
  const { theme, density, motion } = cellGlobals(cell);
  return (
    `/iframe.html?id=${cell.story}&viewMode=story` +
    `&globals=theme:${theme};density:${density};motion:${motion};a11y.manual:!true`
  );
}

/**
 * The `data-motion` the runtime must write for the shot: "reduce", the OS preference the capture emulates,
 * unless the story pins the override "off" ("on" and "system" both reduce then).
 */
export const expectedMotion = (pinned: Readonly<Record<string, unknown>>): string =>
  pinned["motion"] === "off" ? "safe" : "reduce";

/** The baselines a matrix lacks, and the PNGs no cell owns (left by a renamed or deleted story). */
export function auditBaselines(
  cells: readonly Cell[],
  files: readonly string[],
): { missing: string[]; orphaned: string[] } {
  const present = new Set(files.filter((file) => file.endsWith(".png")));
  const expected = new Set(cells.map(({ key }) => `${key}.png`));
  return {
    missing: cells.filter(({ key }) => !present.has(`${key}.png`)).map(({ key }) => key),
    orphaned: [...present].filter((file) => !expected.has(file)).sort(),
  };
}
