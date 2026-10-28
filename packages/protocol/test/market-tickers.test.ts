import { describe, expect, expectTypeOf, it } from "vitest";
import { generated } from "../src/index.js";

// E08-T08 (#4707): the client's reading of the bulk ticker snapshot `GET /market/tickers` and of
// the 24 h high and low (C-6.2), on the generated types. Nothing serves the route yet; the
// implementation PR does. The expectTypeOf checks bind under `pnpm typecheck` (tsconfig.json
// includes test/), not the vitest run; the runtime expects only keep the sample values in use.
type Schemas = generated.rest.components["schemas"];
type Op = generated.rest.operations["getTickers"];
type Answer = Op["responses"][200]["content"]["application/json"];
type Ticker = Schemas["Ticker"];
type Item = Schemas["TickersItem"];
type WsItem = generated.ws.TickerSymbolTicker["tickers"][number];

const ts = "2026-09-14T10:31:02.100Z";
const answer: Answer = {
  items: [
    {
      symbol: "BTCUSDT",
      last_price: "63120.50",
      high_24h: "63980.00",
      low_24h: "61455.50",
      ts,
      stale: false,
    },
    { symbol: "ETHUSDT", last_price: "2415.38", ts, stale: true },
  ],
  unknown_symbols: ["NOSUCHUSDT"],
  meta: { next_cursor: null, has_more: false, count: 2 },
};

describe("bulk ticker snapshot (consumer side, 22-api-openapi /market/tickers)", () => {
  it("asks for one required list of symbols and nothing else", () => {
    expectTypeOf<Op["parameters"]["query"]>().toEqualTypeOf<{ symbols: string[] }>();
  });

  it("answers the tickers it found and reports the symbols it has none for", () => {
    expect(answer.items.map((t) => t.symbol)).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(answer.unknown_symbols).toEqual(["NOSUCHUSDT"]);
    expectTypeOf<Answer>().toEqualTypeOf<Schemas["TickersResponse"]>();
    expectTypeOf<Answer["items"]>().toEqualTypeOf<Item[]>();
    expectTypeOf<Answer["unknown_symbols"]>().toEqualTypeOf<string[]>();
  });

  it("requires each item's symbol, ts and stale, which a bare Ticker may leave out", () => {
    expect(answer.items.map((t) => t.stale)).toEqual([false, true]);
    expectTypeOf<Item>().toExtend<Ticker>();
    expectTypeOf<Item["symbol"]>().toEqualTypeOf<string>();
    expectTypeOf<Item["ts"]>().toEqualTypeOf<string>();
    expectTypeOf<Item["stale"]>().toEqualTypeOf<boolean>();
    expectTypeOf<Ticker["ts"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<Ticker["stale"]>().toEqualTypeOf<boolean | undefined>();
  });

  it("refuses with the shared problem responses only, never a 404", () => {
    expectTypeOf<keyof Op["responses"]>().toEqualTypeOf<200 | 400 | 401 | 403 | 503>();
  });

  it("keeps the 24 h high and low optional decimals on REST and WS alike", () => {
    expect(answer.items[1]?.high_24h).toBeUndefined();
    expectTypeOf<Ticker["high_24h"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<Ticker["low_24h"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<WsItem["high_24h"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<WsItem["low_24h"]>().toEqualTypeOf<string | undefined>();
  });
});
