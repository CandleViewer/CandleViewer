// Type / contract tests for the frozen §8 surface (E11-T01). The runtime half reads the package
// root through the TypeScript checker, so type-only exports count; the compile-time half
// (expectTypeOf) is enforced by `tsc --noEmit` over test/ in `pnpm typecheck`.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { describe, expect, expectTypeOf, it } from "vitest";
import * as root from "../../src/index.js";
import type {
  CandleData,
  Chart,
  ChartEvents,
  ChartOptions,
  FootprintData,
  FrameStats,
  HeatmapColumnData,
  Pane,
  SeriesHandle,
  SeriesType,
  ThemeTokens,
  Unsubscribe,
} from "../../src/index.js";
import type { EngineTheme } from "../../src/compat.js";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const INDEX = join(PKG, "src", "index.ts");
const DESIGN = join(PKG, "..", "..", "docs", "plan", "26-chart-engine-design.md");

/** The public surface as the checker sees it: every export name, and printed key shapes. */
function readSurface(): {
  names: string[];
  print: (name: string) => string;
  members: (name: string) => Record<string, string>;
} {
  const program = ts.createProgram([INDEX], {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    lib: ["lib.es2022.d.ts", "lib.dom.d.ts"],
    strict: true,
    noEmit: true,
    skipLibCheck: true,
    types: [],
  });
  const checker = program.getTypeChecker();
  const source = program.getSourceFile(INDEX);
  const moduleSymbol = source === undefined ? undefined : checker.getSymbolAtLocation(source);
  if (moduleSymbol === undefined) throw new Error("src/index.ts did not load");
  const exports = checker.getExportsOfModule(moduleSymbol);
  const byName = new Map(exports.map((s) => [s.getName(), s]));
  const typeOf = (name: string): ts.Type => {
    const sym = byName.get(name);
    if (sym === undefined) throw new Error(`${name} is not exported`);
    const target = sym.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(sym) : sym;
    return target.flags & ts.SymbolFlags.Value
      ? checker.getTypeOfSymbol(target)
      : checker.getDeclaredTypeOfSymbol(target);
  };
  return {
    names: [...byName.keys()].sort(),
    print: (name) => checker.typeToString(typeOf(name)),
    members: (name) =>
      Object.fromEntries(
        typeOf(name)
          .getProperties()
          .map((p) => [p.getName(), checker.typeToString(checker.getTypeOfSymbol(p))]),
      ),
  };
}

/** The `export interface|type` names of the §8 sketch, and the text of its code fences only. */
function readSketch(): { declared: string[]; text: string } {
  const doc = readFileSync(DESIGN, "utf8");
  const start = doc.indexOf("## 8. TypeScript API sketch");
  const end = doc.indexOf("React binding (in `apps/web`", start);
  // Prose in §8 (this PR's own pointer paragraph included) cannot vouch for an export.
  const text = [...doc.slice(start, end).matchAll(/^```ts\n([\s\S]*?)^```$/gm)]
    .map((m) => m[1] ?? "")
    .join("\n");
  const declared = [...text.matchAll(/export (?:interface|type) (\w+)/g)].map((m) => m[1] ?? "");
  return { declared, text };
}

const surface = readSurface();
/** Root exports the rulings of record add outside the §8 sketch (E11-T09 is told of each). */
const RULED_ADDITIONS = ["toTicks"]; // E12-S06 BQ-10

describe("Scenario: The package builds and exports the designed surface", () => {
  it("exports exactly the frozen name list (a widening shows up in review)", () => {
    expect(surface.names).toEqual([
      "BarView",
      "BubbleOptions",
      "CandleData",
      "CandleOptions",
      "Chart",
      "ChartEvents",
      "ChartOptions",
      "Density",
      "Drawing",
      "FocusedUnit",
      "FootprintCellRef",
      "FootprintData",
      "FootprintOptions",
      "FrameStats",
      "HeatmapColumnData",
      "HeatmapOptions",
      "HistogramOptions",
      "IndicatorHandle",
      "IndicatorPlugin",
      "LineOptions",
      "LineStyle",
      "LutId",
      "Modifiers",
      "OrderLine",
      "OutputBuffers",
      "OutputSpec",
      "OverlayHandle",
      "OverlayPlugin",
      "Pane",
      "PaneId",
      "PaneOptions",
      "ParamSpec",
      "Params",
      "PickResult",
      "PluginContext",
      "Point",
      "PriceScale",
      "ProfileOptions",
      "Range",
      "Rect",
      "RenderContext",
      "SeriesDataMap",
      "SeriesDeltaMap",
      "SeriesHandle",
      "SeriesOptionsMap",
      "SeriesPlugin",
      "SeriesType",
      "TextStyle",
      "TextureId",
      "ThemeTokens",
      "TimeScale",
      "Unsubscribe",
      "Viewport",
      "VisibleWindow",
      "createChart",
      "toTicks", // E12-S06 BQ-10: ruled additive
    ]);
  });

  it("exports every interface and type the §8 sketch declares", () => {
    const { declared } = readSketch();
    expect(declared.length).toBeGreaterThan(15);
    expect(declared.filter((name) => !surface.names.includes(name))).toEqual([]);
  });

  it("exports no symbol the §8 sketch does not name, except the ruled additions", () => {
    const { text } = readSketch();
    const outside = surface.names.filter((name) => !new RegExp(`\\b${name}\\b`).test(text));
    expect(outside).toEqual(RULED_ADDITIONS);
  });

  it("has two runtime exports: createChart with the §8 signature, and toTicks (BQ-10)", () => {
    expect(Object.keys(root).sort()).toEqual(["createChart", "toTicks"]);
    expect(surface.print("createChart")).toBe("(opts: ChartOptions) => Chart");
    expect(surface.print("toTicks")).toBe(
      "(price: number, priceOrigin: number, tickSize: number) => number",
    );
  });

  it("keeps the §8 data shapes: Int32Array ticks with priceOrigin/tickSize, Float64Array µs", () => {
    expect(surface.members("CandleData")).toEqual({
      time: "Float64Array<ArrayBufferLike>",
      open: "Int32Array<ArrayBufferLike>",
      high: "Int32Array<ArrayBufferLike>",
      low: "Int32Array<ArrayBufferLike>",
      close: "Int32Array<ArrayBufferLike>",
      volume: "Float32Array<ArrayBufferLike>",
      priceOrigin: "number",
      tickSize: "number",
      flags: "Uint8Array<ArrayBufferLike> | undefined", // E12-S06 BQ-3, 24 §19.75
    });
    expect(surface.members("FootprintData")).toEqual({
      barIndexOffsets: "Uint32Array<ArrayBufferLike>",
      cellPriceLevel: "Int32Array<ArrayBufferLike>",
      cellBidVol: "Float32Array<ArrayBufferLike>",
      cellAskVol: "Float32Array<ArrayBufferLike>",
      cellTradeCount: "Uint16Array<ArrayBufferLike>",
      priceOrigin: "number",
      tickSize: "number",
    });
    expect(Object.keys(surface.members("HeatmapColumnData"))).toEqual([
      "time",
      "priceOrigin",
      "priceStep",
      "rows",
      "sizes",
      "estimated",
    ]);
  });

  it("keeps the Chart and Pane members of §8 (plus BQ-3's accessibility queries)", () => {
    expect(Object.keys(surface.members("Chart")).sort()).toEqual([
      "addPane",
      "dispose",
      "getDomMirrorRoot",
      "getFocusedUnit",
      "getStats",
      "getVisibleWindow",
      "panes",
      "removePane",
      "setDensity",
      "setTheme",
      "subscribe",
      "takeScreenshot",
      "timeScale",
    ]);
    expect(Object.keys(surface.members("Pane")).sort()).toEqual([
      "addIndicator",
      "addOverlay",
      "addSeries",
      "id",
      "priceScale",
      "remove",
      "setHeightRatio",
    ]);
    expect(Object.keys(surface.members("ChartEvents")).sort()).toEqual([
      "click",
      "crosshair",
      "dataState",
      "drawingChanged",
      "error",
      "frameStats",
      "orderLineDragged",
      "viewportChanged",
      "visibleRangeNeedsData",
    ]);
  });

  it("type-checks the key signatures (enforced by tsc over test/)", () => {
    expectTypeOf(root.createChart).parameters.toEqualTypeOf<[ChartOptions]>();
    expectTypeOf(root.createChart).returns.toEqualTypeOf<Chart>();
    expectTypeOf<Chart["subscribe"]>().parameter(0).toEqualTypeOf<keyof ChartEvents>();
    expectTypeOf<ReturnType<Chart["subscribe"]>>().toEqualTypeOf<Unsubscribe>();
    expectTypeOf<ChartEvents["frameStats"]>().toEqualTypeOf<FrameStats>();
    // BQ-64: one optional field, set only on ENGINE_CONTEXT_LOST; it widens nothing that exists.
    // E11-T05 BQ-90: the same optional field also carries ENGINE_NO_WEBGL2's codes, and E11-S11
    // BQ-272 ENGINE_ATLAS_GENERATION_FAILED's reason.
    expectTypeOf<ChartEvents["error"]>().toEqualTypeOf<{
      code: string;
      message: string;
      recoverable: boolean;
      details?:
        | { attempt: number; maxAttempts: number; nextTryMs: number }
        | {
            reducedCapabilities: (
              "footprint-text" | "heatmap" | "bubbles" | "profile-shading" | "gpu-effects"
            )[];
            reason: "no-webgl2" | "context-failed" | "compile-failed" | "restore-failed" | "forced";
          }
        | { atlasReason: "no-font" | "font-load" | "coverage" | "overflow" | "raster" };
    }>();
    expectTypeOf<{ code: string; message: string; recoverable: boolean }>().toMatchTypeOf<
      ChartEvents["error"]
    >();
    expectTypeOf<FrameStats["renderProfile"]>().toEqualTypeOf<"full" | "reduced" | "degraded-2d">();
    expectTypeOf<SeriesHandle<"candles">["setData"]>().parameter(0).toEqualTypeOf<CandleData>();
    expectTypeOf<SeriesHandle<"footprint">["append"]>().parameter(0).toEqualTypeOf<FootprintData>();
    expectTypeOf<SeriesHandle<"heatmap">["append"]>()
      .parameter(0)
      .toEqualTypeOf<HeatmapColumnData>();
    expectTypeOf<Parameters<Pane["addSeries"]>[0]>().toEqualTypeOf<SeriesType>();
    expectTypeOf<CandleData["open"]>().toEqualTypeOf<Int32Array>();
    expectTypeOf<CandleData["time"]>().toEqualTypeOf<Float64Array>();
    // The pre-§8 palette seam and the §8 theme tokens are one shape (README BQ-2).
    expectTypeOf<EngineTheme>().toEqualTypeOf<ThemeTokens>();
    expect(true).toBe(true);
  });
});
