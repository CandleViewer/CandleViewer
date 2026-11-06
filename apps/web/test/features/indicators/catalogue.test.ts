/**
 * E13-S01 (#423) S1: the catalogue (`listIndicators`; D06 §3.1, BQ-2, BQ-14): every descriptor the
 * server returns, in its order; a body that breaks the contract is a failed catalogue, never a
 * partial list; values a reader may not know are tolerated (C-6.3).
 */
import { describe, expect, it, vi } from "vitest";
import {
  entryById,
  fetchCatalogue,
  normaliseCatalogue,
  normaliseDescriptor,
} from "../../../src/features/indicators/model/catalogue";
import { BOLLINGER, CATALOGUE, EMA, SMA_5933 } from "./fixtures";

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("normaliseDescriptor", () => {
  it("keeps the rendered fields and parses the schema once", () => {
    expect(normaliseDescriptor(EMA)).toMatchObject({
      id: "ema",
      name: "Exponential moving average",
      category: "trend",
      pane: "price",
      compute: "server",
      estimated: false,
      unit: "price",
      warmupBars: 21,
      outputs: [{ id: "ema", name: "EMA" }],
      schema: { ok: true },
    });
  });

  it("reads #5933's sma (source and offset; if #5933 merges as is)", () => {
    const entry = normaliseDescriptor(SMA_5933);
    expect(entry?.schema).toEqual({
      ok: true,
      fields: [
        {
          kind: "integer",
          name: "n",
          title: "Period",
          minimum: 1,
          maximum: 5000,
          step: 1,
          default: 20,
        },
        {
          kind: "enum",
          name: "source",
          title: "Source",
          options: ["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"],
          default: "close",
        },
        {
          kind: "integer",
          name: "offset",
          title: "Offset",
          minimum: 0,
          maximum: 500,
          step: 1,
          default: 0,
        },
      ],
    });
  });

  it("treats an absent outputs as none by design (22 does not require it)", () => {
    expect(normaliseDescriptor({ ...EMA, outputs: undefined })?.outputs).toEqual([]);
  });

  it("accepts a 1,024-character name and refuses one past the sanity bound", () => {
    expect(normaliseDescriptor({ ...EMA, name: "x".repeat(1024) })?.name).toHaveLength(1024);
    expect(normaliseDescriptor({ ...EMA, name: "x".repeat(1025) })).toBeNull();
  });

  it("tolerates an unknown unit or category and absent optional fields", () => {
    const entry = normaliseDescriptor({
      ...BOLLINGER,
      unit: "furlong",
      category: "astrology",
      warmup_bars: -1,
      outputs: undefined,
    });
    expect(entry).toMatchObject({ unit: null, category: null, warmupBars: null, outputs: [] });
  });

  it("keeps an entry whose schema is refused, marked so (its Add is T2, BQ-2)", () => {
    expect(normaliseDescriptor({ ...EMA, params_schema: { $ref: "#" } })?.schema).toEqual({
      ok: false,
    });
  });

  it.each([
    ["an unknown compute", { ...EMA, compute: "gpu" }],
    ["an unknown pane", { ...EMA, pane: "left" }],
    ["an id off the contract pattern", { ...EMA, id: "E" }],
    ["an empty name", { ...EMA, name: "" }],
    ["an output without a name", { ...EMA, outputs: [{ id: "ema" }] }],
    ["outputs that are not a list", { ...EMA, outputs: {} }],
    ["an empty outputs (22 minItems 1)", { ...EMA, outputs: [] }],
    ["an output id off 22's pattern", { ...EMA, outputs: [{ id: "EMA", name: "EMA" }] }],
    ["an output id with a leading digit", { ...EMA, outputs: [{ id: "1ema", name: "EMA" }] }],
    [
      "an output id past 32 characters",
      { ...EMA, outputs: [{ id: `e${"a".repeat(32)}`, name: "E" }] },
    ],
    ["an output that is not an object", { ...EMA, outputs: ["ema"] }],
    ["an array", [EMA]],
  ])("refuses %s", (_label, raw) => {
    expect(normaliseDescriptor(raw)).toBeNull();
  });
});

describe("normaliseCatalogue", () => {
  it("lists every descriptor in the server's order", () => {
    expect(normaliseCatalogue({ items: CATALOGUE })?.map((e) => e.id)).toEqual(
      CATALOGUE.map((d) => d.id),
    );
    expect(normaliseCatalogue({})).toEqual([]);
  });

  it("fails the whole catalogue on one broken or duplicate entry (no partial list)", () => {
    expect(normaliseCatalogue({ items: [EMA, { ...BOLLINGER, compute: "x" }] })).toBeNull();
    expect(normaliseCatalogue({ items: [EMA, EMA] })).toBeNull();
    expect(normaliseCatalogue({ items: "ema" })).toBeNull();
    expect(normaliseCatalogue(null)).toBeNull();
  });

  it("refuses no catalogue for its size: 22 owns no maxItems, the library pages the render", () => {
    const items = Array.from({ length: 300 }, (_, i) => ({ ...EMA, id: `ind_${i}` }));
    expect(normaliseCatalogue({ items })).toHaveLength(300);
  });

  it("finds an entry by id", () => {
    const entries = normaliseCatalogue({ items: CATALOGUE }) ?? [];
    expect(entryById(entries, "cvd")?.name).toBe("Cumulative volume delta");
    expect(entryById(entries, "nope")).toBeUndefined();
  });
});

describe("fetchCatalogue", () => {
  it("GETs /api/v1/indicators and normalises the body", async () => {
    const fetchFn = vi.fn(() => Promise.resolve(json({ items: [EMA] })));
    const result = await fetchCatalogue(fetchFn);
    expect(fetchFn).toHaveBeenCalledWith("/api/v1/indicators", { method: "GET" });
    expect(result.ok && result.entries.map((e) => e.id)).toEqual(["ema"]);
  });

  it("reports a refusal, no answer and a broken body as failures with their status", async () => {
    expect(await fetchCatalogue(() => Promise.resolve(json({}, 503)))).toEqual({
      ok: false,
      status: 503,
    });
    expect(await fetchCatalogue(() => Promise.reject(new TypeError("offline")))).toEqual({
      ok: false,
      status: 0,
    });
    expect(
      await fetchCatalogue(() => Promise.resolve(new Response("<html>", { status: 200 }))),
    ).toEqual({ ok: false, status: 200 });
  });
});
