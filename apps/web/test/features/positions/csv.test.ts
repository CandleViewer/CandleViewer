/**
 * E29-S01 (#911, BQ-17) CSV export (E29-D02 D-21): the rows in view, the visible column order,
 * decimals raw (no `+`, numbers stay numbers), text guarded against formula injection; client-side
 * only, so it fetches nothing and reports no analytics event.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  exportPositionsCsv,
  guardCell,
  toCsv,
  type CsvColumn,
} from "../../../src/features/positions/csv";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";
import { readLiq } from "../../../src/features/positions/model/liqTier";
import {
  accountInfo,
  mapRow,
  type AccountInfo,
  type ExchangeAccount,
  type PositionRowModel,
} from "../../../src/features/positions/model/rowMapping";
import { golden } from "./support/fakes";

const directory = new Map(
  golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
    .items.map(accountInfo)
    .filter((a): a is AccountInfo => a !== null)
    .map((a) => [a.id, a]),
);
const rows = golden<generated.ws.Positions>("ws_positions_contract_fields.json")
  .positions.map((item) => mapRow(item, "ws", directory))
  .filter((r): r is PositionRowModel => r !== null);
const liq = new Map(
  rows.map((r) => [
    r.key,
    readLiq({
      side: r.side,
      entry: r.entry,
      mark: r.mark,
      liqPrice: r.liqPrice,
      marginMode: r.marginMode.value,
      mmRate: null,
    }),
  ]),
);

afterEach(() => vi.unstubAllGlobals());

describe("guardCell (D-21)", () => {
  it.each(["=SUM(A1)", "+1", "-2", "@cmd", "\tx", "\rx"])("prefixes %j", (text) => {
    expect(guardCell(text)).toBe(`'${text}`);
  });

  it("leaves other text alone", () => {
    expect(guardCell("Main — UTA")).toBe("Main — UTA");
    expect(guardCell("")).toBe("");
  });
});

describe("toCsv", () => {
  type Row = { label: string; pnl: string | null };
  const columns: CsvColumn<Row>[] = [
    { header: "Account", kind: "text", value: (r) => r.label },
    { header: "uPnL (USDT)", kind: "number", value: (r) => r.pnl },
  ];

  it("writes numbers raw, guards text, quotes per RFC 4180, CRLF lines", () => {
    const out = toCsv(
      [
        { label: '=HYPERLINK("x")', pnl: "-121.50" },
        { label: 'Sub, "2"\nline', pnl: null },
        { label: "Main", pnl: "-x" },
      ],
      columns,
    );
    expect(out).toBe(
      'Account,uPnL (USDT)\r\n"\'=HYPERLINK(""x"")",-121.50\r\n"Sub, ""2""\nline",\r\nMain,\'-x\r\n',
    );
  });
});

describe("exportPositionsCsv", () => {
  it("the rows in view, in the visible column order, decimals raw", () => {
    const csv = exportPositionsCsv(
      rows.slice(2, 4),
      [
        "symbol",
        "account",
        "side",
        "upnl",
        "r",
        "rpnl_today",
        "liq_dist",
        "margin",
        "position_idx",
        "nope",
      ],
      liq,
    );
    expect(csv.split("\r\n")).toEqual([
      "Symbol,Account,Side,uPnL (USDT),R,rPnL today (USDT),Liq dist. %,Margin,Pos. idx",
      "ETHUSDT,Sub-1,Short,-121.5,-0.8526,-18.2,1.2,Isolated,0",
      "SOLUSDT,Sub-2,Long · hedge,-92,-0.9388,0,0.5,Cross,1",
      "",
    ]);
  });

  it("every catalogued column has its D02 §5.1 header", () => {
    const ids = [
      "account",
      "symbol",
      "side",
      "size",
      "entry",
      "mark",
      "upnl",
      "r",
      "rpnl_today",
      "liq_price",
      "liq_dist",
      "leverage",
      "margin",
      "take_profit",
      "notional",
      "position_idx",
      "trade_group",
    ];
    const header = exportPositionsCsv([], ids, liq).trim();
    expect(header).toBe(
      "Account,Symbol,Side,Size,Entry (USDT),Mark (USDT),uPnL (USDT),R,rPnL today (USDT),Liq price (USDT),Liq dist. %,Lev,Margin,TP,Notional,Pos. idx,Trade group",
    );
    const line = exportPositionsCsv(rows.slice(0, 1), ids, new Map()).split("\r\n")[1];
    expect(line).toBe(
      "Main,BTCUSDT,Long,0.25,63980,64012,8,0.32,12.4,57901.9,,10,Isolated,,16003.00,0,0c000000-0000-4000-8000-000000000001",
    );
  });

  it("BQ-17: no request and no analytics event", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const events = vi.fn();
    window.addEventListener(THEME_ANALYTICS_EVENT, events);
    exportPositionsCsv(rows, ["symbol"], liq);
    window.removeEventListener(THEME_ANALYTICS_EVENT, events);
    expect(fetch).not.toHaveBeenCalled();
    expect(events).not.toHaveBeenCalled();
  });
});
