/**
 * E13-S01 (#423) S1: the library's list and search model (SCR-034; D02 §4.1–§4.4) and the preset
 * shapes (D02 D7, D14; `22` IndicatorPresetInput).
 */
import { describe, expect, it, vi } from "vitest";
import { normaliseCatalogue } from "../../../src/features/indicators/model/catalogue";
import { createInstance } from "../../../src/features/indicators/model/instances";
import { inTab, libraryView, type Matcher } from "../../../src/features/indicators/model/library";
import { defaultParams } from "../../../src/features/indicators/model/params";
import {
  favouritesOf,
  findOwnPreset,
  presetInput,
  presetParams,
  presetTarget,
  starredInput,
} from "../../../src/features/indicators/model/presets";
import type { IndicatorPreset } from "../../../src/features/indicators/model/types";
import { CATALOGUE } from "./fixtures";

const ENTRIES = normaliseCatalogue({ items: CATALOGUE }) ?? [];
const byId = (id: string) => ENTRIES.find((e) => e.id === id) as (typeof ENTRIES)[number];

/** A plain substring scorer for the model; CMP-213's own scorer is wired in S3b. */
const substring: Matcher = (label, query) => {
  const at = label.toLowerCase().indexOf(query.trim().toLowerCase());
  return at < 0 ? null : { score: 100 - at, ranges: [[at, at + query.trim().length]] };
};

const preset = (over: Partial<IndicatorPreset>): IndicatorPreset => ({
  id: "00000000-0000-7000-8000-000000000001",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  owner_user_id: null,
  indicator_code: "ema",
  name: "ema(21)",
  is_builtin: true,
  is_favourite: false,
  pane_target: "overlay",
  params: { n: 21 },
  style: {},
  ...over,
});
const BUILTIN = preset({});
const MINE = preset({
  id: "00000000-0000-7000-8000-000000000002",
  is_builtin: false,
  is_favourite: true,
  owner_user_id: "00000000-0000-7000-8000-0000000000aa",
  name: "EMA 34",
  params: { n: 34 },
});
const ORPHAN = preset({ is_builtin: false, is_favourite: true, indicator_code: "gone" });

const view = (over: Partial<Parameters<typeof libraryView>[0]>) =>
  libraryView({
    entries: ENTRIES,
    presets: [BUILTIN, MINE, ORPHAN],
    instances: [],
    tab: "all",
    query: "",
    match: substring,
    ...over,
  });

describe("libraryView: the landing", () => {
  it("lists Favourites, then every entry grouped by category in descriptor order", () => {
    const v = view({});
    expect(v.favourites).toEqual([MINE]);
    expect(v.groups.map((g) => [g.category, g.rows.map((r) => r.entry.id)])).toEqual([
      ["trend", ["ema", "zigzag"]],
      ["momentum", ["rsi"]],
      ["volatility", ["bollinger"]],
      ["volume", ["volume"]],
      ["orderflow", ["cvd"]],
    ]);
    expect(v.matches).toBe(6);
    expect(v.elsewhere).toBe(0);
  });

  it("tags server entries, counts instances on the chart and lists built-ins after their entry", () => {
    let n = 0;
    const mint = () => `i${(n += 1)}`;
    const ema = byId("ema");
    const instance = createInstance(
      [],
      {
        entry: ema,
        params: ema.schema.ok ? defaultParams(ema.schema.fields) : {},
        target: "overlay",
      },
      mint,
    );
    const row = view({ instances: [instance] }).groups[0]?.rows[0];
    expect(row).toMatchObject({ onChart: 1, requiresRecording: true, builtins: [BUILTIN] });
    expect(view({}).groups[2]?.rows[0]).toMatchObject({ requiresRecording: false, onChart: 0 });
  });

  it("lists an entry of an unknown category last, under All only", () => {
    const odd =
      normaliseCatalogue({ items: [{ ...CATALOGUE[0], id: "odd", category: "new" }] }) ?? [];
    const v = libraryView({
      entries: odd,
      presets: [],
      instances: [],
      tab: "all",
      query: "",
      match: substring,
    });
    expect(v.groups).toEqual([
      { category: null, rows: [expect.objectContaining({ entry: odd[0] })] },
    ]);
  });
});

describe("libraryView: tabs and search (D02 D3)", () => {
  it("filters by pane target; `both` is under both pane tabs", () => {
    const ids = (tab: "overlay" | "subpane" | "orderflow") =>
      view({ tab }).groups.flatMap((g) => g.rows.map((r) => r.entry.id));
    expect(ids("overlay")).toEqual(["ema", "zigzag", "bollinger", "volume"]);
    expect(ids("subpane")).toEqual(["rsi", "volume", "cvd"]);
    expect(ids("orderflow")).toEqual(["cvd"]);
    expect(inTab({ pane: "both", category: "volume" }, "orderflow")).toBe(false);
  });

  it("searches name and id inside the tab, best first, and drops the landing groups", () => {
    const v = view({ query: "average" });
    expect(v.favourites).toBeNull();
    expect(v.groups.flatMap((g) => g.rows.map((r) => [r.entry.id, r.ranges]))).toEqual([
      ["ema", [[19, 26]]],
    ]);
    expect(v.groups[0]?.rows[0]?.builtins).toEqual([]);
    expect(view({ query: "cvd" }).groups[0]?.rows[0]).toMatchObject({
      entry: { id: "cvd" },
      ranges: [],
    });
  });

  it("reports matches the active tab hides", () => {
    const v = view({ tab: "orderflow", query: "e" });
    expect(v.matches).toBe(1);
    expect(v.elsewhere).toBe(4);
    expect(view({ query: "xyz" })).toMatchObject({ matches: 0, groups: [] });
  });
});

describe("presets", () => {
  const ema = byId("ema");
  const cvd = byId("cvd");
  const vol = byId("volume");

  it("builds the star's body: params written out, style empty (D02 D7)", () => {
    expect(presetInput(ema, "Exponential moving average", { n: 21 }, "overlay", true)).toEqual({
      indicator_code: "ema",
      name: "Exponential moving average",
      params: { n: 21 },
      pane_target: "overlay",
      is_favourite: true,
      style: {},
    });
    expect(starredInput(MINE, false)).toMatchObject({
      name: "EMA 34",
      params: { n: 34 },
      is_favourite: false,
      style: {},
    });
  });

  it("finds the caller's own same-code, same-name preset, case-insensitively, never a built-in", () => {
    expect(findOwnPreset([BUILTIN, MINE], "ema", "ema 34")).toBe(MINE);
    expect(findOwnPreset([BUILTIN, MINE], "ema", "ema(21)")).toBeUndefined();
    expect(favouritesOf([BUILTIN, MINE, ORPHAN], ENTRIES)).toEqual([MINE]);
  });

  it("folds a name locale-independently, so a Turkish host locale never misses or mismatches", () => {
    // A Turkish host folds "I" to the dotless "ı" and "İ" to "i": the server's fold does neither.
    const turkish = vi.spyOn(String.prototype, "toLocaleLowerCase").mockImplementation(function (
      this: string,
    ) {
      return this.replace(/I/g, "\u0131").toLowerCase();
    });
    try {
      const index = preset({ ...MINE, indicator_code: "ema", name: "INDEX 34" });
      expect(findOwnPreset([index], "ema", "index 34")).toBe(index);
      expect(findOwnPreset([index], "ema", "\u0131ndex 34")).toBeUndefined();
    } finally {
      turkish.mockRestore();
    }
  });

  it("re-validates a preset's params against the live schema (BQ-11)", () => {
    expect(presetParams(MINE, ema)).toEqual({ ok: true, params: { n: 34 } });
    expect(presetParams(preset({ params: { n: 0 } }), ema)).toMatchObject({
      ok: false,
      errors: [{ name: "n", rule: "minimum" }],
    });
    expect(presetParams(MINE, cvd)).toMatchObject({ ok: false });
  });

  it("keeps the preset's target only where the entry offers it", () => {
    expect(presetTarget(preset({ pane_target: "subpane" }), ema)).toBe("overlay");
    expect(presetTarget(preset({ pane_target: "overlay" }), cvd)).toBe("subpane");
    expect(presetTarget(preset({ pane_target: "subpane" }), vol)).toBe("subpane");
  });
});
