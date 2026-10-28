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

  it("reads when recording began from a no_data_recorded refusal", () => {
    expectTypeOf<Schemas["Problem"]["recording_started_at"]>().toEqualTypeOf<
      string | null | undefined
    >();
  });
});
