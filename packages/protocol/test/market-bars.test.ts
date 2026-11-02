import { describe, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// E12-Q04 (#420): the client's reading of `GET /market/klines` and `GET /market/bars` (C-6.2), on
// the generated types: the required window (`from`), the bar types, decimals as strings, the
// forming bar's `confirm`, null order flow and the `no_data_recorded` problem's
// `recording_started_at`. These checks bind under `pnpm typecheck` (tsconfig.json includes test/),
// not the vitest run.
type Schemas = generated.rest.components["schemas"];
type Klines = generated.rest.operations["getKlines"];
type Bars = generated.rest.operations["getBars"];
type Page = Bars["responses"][200]["content"]["application/json"];
type Bar = Schemas["Bar"];
type WsBar = generated.ws.BarsSymbolBarTypeParam["bars"][number];
type SnapMeta = NonNullable<generated.ws.CandleViewerWSEnvelope["meta"]>;
type Refusals = 400 | 401 | 403 | 422 | 503;

describe("klines and bars pages (consumer side, 22-api-openapi /market/klines, /market/bars)", () => {
  it("asks for a window that always names its start", () => {
    expectTypeOf<Klines["parameters"]["query"]["from"]>().toEqualTypeOf<string>();
    expectTypeOf<Bars["parameters"]["query"]["from"]>().toEqualTypeOf<string>();
    expectTypeOf<Bars["parameters"]["query"]["bar_type"]>().toEqualTypeOf<Schemas["BarType"]>();
    expectTypeOf<Bars["parameters"]["query"]["param"]>().toEqualTypeOf<string>();
  });

  it("reads one page shape from both routes and refuses only with the shared problems", () => {
    expectTypeOf<Klines["responses"][200]["content"]["application/json"]>().toEqualTypeOf<Page>();
    expectTypeOf<keyof Klines["responses"]>().toEqualTypeOf<200 | Refusals>();
    expectTypeOf<keyof Bars["responses"]>().toEqualTypeOf<200 | Refusals>();
  });

  it("keys bars by generation and index, with decimals as strings and null order flow", () => {
    expectTypeOf<Bar["generation"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Bar["index"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Bar["o"]>().toEqualTypeOf<string>();
    expectTypeOf<Bar["delta"]>().toEqualTypeOf<string | null | undefined>();
    expectTypeOf<Page["meta"]["recording_started_at"]>().toEqualTypeOf<string | null | undefined>();
  });

  it("names the forming bar `confirm` on REST and on the bars topic alike", () => {
    expectTypeOf<Bar["confirm"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<WsBar["confirm"]>().toEqualTypeOf<boolean>();
  });

  it("reads the bar flags as booleans, false by default, on REST and WS (#5396)", () => {
    // REST types a member with a `default` as present; the WS item keeps it optional.
    expectTypeOf<Bar["gap_before"]>().toEqualTypeOf<boolean>();
    expectTypeOf<Bar["partial"]>().toEqualTypeOf<boolean>();
    expectTypeOf<Bar["tape_gap"]>().toEqualTypeOf<boolean>();
    expectTypeOf<WsBar["gap_before"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<WsBar["partial"]>().toEqualTypeOf<boolean | undefined>();
    expectTypeOf<WsBar["tape_gap"]>().toEqualTypeOf<boolean | undefined>();
  });

  it("reads build provenance from the page meta, named as the WS snapshot's (#5396)", () => {
    expectTypeOf<Page["meta"]>().toEqualTypeOf<Schemas["BarsMeta"]>();
    expectTypeOf<Page["meta"]["spec_hash"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<Page["meta"]["build_version"]>().toEqualTypeOf<number | undefined>();
    expectTypeOf<Page["meta"]["stale_build"]>().toEqualTypeOf<boolean>();
    // One key, one meaning: REST carries no WS-style feed `stale`.
    expectTypeOf<Page["meta"]>().not.toHaveProperty("stale");
    expectTypeOf<Page["meta"]["coverage_holes"]>().toEqualTypeOf<
      Schemas["DataMeta"]["coverage_holes"]
    >();
  });

  it("reads coverage holes from a bars snapshot as from a REST page (#5396)", () => {
    type Hole = NonNullable<Page["meta"]["coverage_holes"]>[number];
    expectTypeOf<SnapMeta["coverage_holes"]>().toEqualTypeOf<Hole[] | undefined>();
    expectTypeOf<Hole>().toEqualTypeOf<{ start_us: number; end_us: number }>();
  });

  it("reads when recording began from a no_data_recorded refusal", () => {
    expectTypeOf<Schemas["Problem"]["recording_started_at"]>().toEqualTypeOf<
      string | null | undefined
    >();
  });
});
