import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  auditBaselines,
  buildMatrix,
  cellGlobals,
  cellKey,
  expectedMotion,
  parseStoryIndex,
  readMatrix,
  readShard,
  shardCells,
  storyPath,
} from "../../vr/matrix.js";

/** A Storybook 10 index.json: two stories, a perf story and a docs page. */
const INDEX = {
  v: 5,
  entries: {
    "atoms-button--primary": { id: "atoms-button--primary", type: "story", tags: ["dev", "test"] },
    "atoms-button--docs": { id: "atoms-button--docs", type: "docs", tags: ["autodocs"] },
    "atoms-badge--default": { id: "atoms-badge--default", type: "story", tags: [] },
    "molecules-table--perf-200-rows": {
      id: "molecules-table--perf-200-rows",
      type: "story",
      tags: ["dev", "perf"],
    },
  },
};

const indexWith = (id: string, entry: Record<string, unknown>) => ({ entries: { [id]: entry } });

describe("story enumeration", () => {
  it("lists the index's stories by id and leaves its docs pages out", () => {
    expect(parseStoryIndex(INDEX).map(({ id }) => id)).toEqual([
      "atoms-badge--default",
      "atoms-button--primary",
      "molecules-table--perf-200-rows",
    ]);
  });

  it.each([
    ["no entries object", { v: 5 }, /no `entries` object/],
    [
      "an entry under another id",
      indexWith("a--b", { id: "a--c", type: "story" }),
      /a--b is malformed/,
    ],
    [
      "an unknown entry type",
      indexWith("a--b", { id: "a--b", type: "test" }),
      /a--b has an unknown type/,
    ],
    [
      "an id that cannot name a file",
      indexWith("a--B/c", { id: "a--B/c", type: "story" }),
      /a--B\/c: its id/,
    ],
    ["a key-ambiguous id", indexWith("a----b", { id: "a----b", type: "story" }), /a----b: its id/],
    [
      "tags that are not strings",
      indexWith("a--b", { id: "a--b", type: "story", tags: [1] }),
      /a--b: its tags/,
    ],
    ["no story at all", indexWith("a--docs", { id: "a--docs", type: "docs" }), /lists no story/],
  ])("fails loudly on %s", (_case, index, error) => {
    expect(() => parseStoryIndex(index)).toThrow(error);
  });

  it("reads a built index.json, and names the missing build", () => {
    const dir = mkdtempSync(join(tmpdir(), "vr-index-"));
    writeFileSync(join(dir, "index.json"), JSON.stringify(INDEX));
    expect(readMatrix(join(dir, "index.json")).cells).toHaveLength(12);
    expect(() => readMatrix(join(dir, "absent.json"))).toThrow(
      /run build:tokens, then storybook:build/,
    );
  });
});

describe("the matrix", () => {
  const matrix = buildMatrix(parseStoryIndex(INDEX));

  it("crosses every kept story with the 3 themes and the 2 densities, keyed story--theme--density", () => {
    expect(matrix.cells.map(({ key }) => key)).toEqual(
      ["atoms-badge--default", "atoms-button--primary"].flatMap((story) =>
        ["dark", "light", "high-contrast"].flatMap((theme) =>
          ["compact", "comfortable"].map((density) => `${story}--${theme}--${density}`),
        ),
      ),
    );
    expect(cellKey("atoms-badge--default", "high-contrast", "comfortable")).toBe(
      "atoms-badge--default--high-contrast--comfortable",
    );
    expect(new Set(matrix.cells.map(({ key }) => key)).size).toBe(matrix.cells.length);
  });

  it("leaves a story out only by an excluded tag, and names it with the reason", () => {
    expect(matrix.excluded).toEqual([
      {
        id: "molecules-table--perf-200-rows",
        reason: expect.stringMatching(/^perf: a wall-clock/),
      },
    ]);
    expect(matrix.stories.length + matrix.excluded.length).toBe(parseStoryIndex(INDEX).length);
  });

  it("opens each cell in the isolated iframe with its globals, motion as the OS asks and no in-page axe", () => {
    const [cell] = matrix.cells.filter(
      ({ theme, density }) => theme === "high-contrast" && density === "comfortable",
    );
    expect(cell && storyPath(cell)).toBe(
      "/iframe.html?id=atoms-badge--default&viewMode=story" +
        "&globals=theme:high-contrast;density:comfortable;motion:system;a11y.manual:!true",
    );
  });

  it("plays as the storybook job does, then expects reduced motion unless the story pins it off", () => {
    const cell = matrix.cells[0];
    if (cell === undefined) throw new Error("no cell");
    // `system` follows the OS preference: none while the play runs, `reduce` once the capture asks for it.
    expect(cellGlobals(cell)).toEqual({ theme: "dark", density: "compact", motion: "system" });
    expect(
      [{}, { theme: "light" }, { motion: "on" }, { motion: "system" }].map(expectedMotion),
    ).toEqual(["reduce", "reduce", "reduce", "reduce"]);
    expect(expectedMotion({ motion: "off" })).toBe("safe");
  });
});

describe("baseline audit", () => {
  const cells = buildMatrix(parseStoryIndex(INDEX)).cells;
  const all = cells.map(({ key }) => `${key}.png`);

  it("passes a complete baseline set, whatever else sits beside it", () => {
    expect(auditBaselines(cells, [...all, ".gitkeep"])).toEqual({ missing: [], orphaned: [] });
  });

  it("names each missing cell and each baseline no cell owns", () => {
    const files = all
      .filter((file) => !file.startsWith("atoms-badge--default--light--"))
      .concat("atoms-badge--renamed--dark--compact.png");
    expect(auditBaselines(cells, files)).toEqual({
      missing: ["atoms-badge--default--light--compact", "atoms-badge--default--light--comfortable"],
      orphaned: ["atoms-badge--renamed--dark--compact.png"],
    });
  });
});

describe("shards", () => {
  /** 9 stories, 54 cells: enough to see each shard sample the whole matrix. */
  const cells = buildMatrix(
    Array.from({ length: 9 }, (_, i) => ({ id: `atoms-s${String(i)}--default`, tags: [] })),
  ).cells;
  const of = (total: number) =>
    Array.from({ length: total }, (_, i) => shardCells(cells, { current: i + 1, total }));

  it("reads VR_SHARD as k of n, the whole matrix when it is unset, and refuses anything else", () => {
    expect(readShard("3/10")).toEqual({ current: 3, total: 10 });
    expect([readShard(undefined), readShard("")]).toEqual([undefined, undefined]);
    for (const bad of ["0/10", "11/10", "3", "3/0", "a/b", " 3/10", "3/10/1"]) {
      expect(() => readShard(bad), bad).toThrow(/VR_SHARD/);
    }
  });

  it("splits the matrix into shards that hold each cell once, within one cell of each other", () => {
    for (const total of [1, 4, 10]) {
      const shards = of(total);
      expect(
        shards
          .flat()
          .map(({ key }) => key)
          .sort(),
      ).toEqual(cells.map(({ key }) => key).sort());
      const sizes = shards.map((shard) => shard.length);
      expect(Math.max(...sizes) - Math.min(...sizes)).toBeLessThanOrEqual(1);
    }
    expect(shardCells(cells, undefined)).toEqual(cells);
  });

  it("deals the cells out in turn, so a story's six cells land in six shards, never one slow block", () => {
    const shards = of(10);
    for (const story of new Set(cells.map((cell) => cell.story))) {
      const holding = shards.filter((shard) => shard.some((cell) => cell.story === story));
      expect(holding).toHaveLength(6);
    }
    // Playwright's own --shard cuts contiguous ranges: the first shard held stories s0 and the start of s1.
    expect(shards[0]?.map(({ story }) => story)).toEqual([
      "atoms-s0--default",
      "atoms-s1--default",
      "atoms-s3--default",
      "atoms-s5--default",
      "atoms-s6--default",
      "atoms-s8--default",
    ]);
  });
});
