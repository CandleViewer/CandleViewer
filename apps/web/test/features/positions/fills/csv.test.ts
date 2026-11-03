/**
 * E29-S04 (#979) the fills' CSV (E29-D03 §3.8, D-11; D02 D-21): every fill given, in D03:200's
 * column order, decimals raw (no `+`, no grouping; `fee` as the contract carries it), text guarded
 * against formula injection, RFC 4180 lines; line 1 the watermark naming the identity, the accounts
 * and the time; D03:200's file name. Client-built: it fetches nothing and reports nothing.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fillColumns,
  fillsCsv,
  fillsCsvName,
  ROLE_PART,
  watermark,
  type AccountOf,
  type WatermarkInput,
} from "../../../../src/features/positions/fills/csv";
import { D03_TEXT, DECK, PROPOSED_TEXT } from "../../../../src/features/positions/fills/copy";
import { THEME_ANALYTICS_EVENT } from "../../../../src/shell/bootstrap/themeStore";
import { repoFile } from "../../../lib/ws/support/schemaHarness";
import { MAIN, SUB1, SUB2 } from "../support/fakes";
import { ORDER_A3F2, orderRows, restItems, rowsOf } from "./support/fills";

const LABELS: Record<string, string> = { [MAIN]: "Main", [SUB1]: "Sub-1", [SUB2]: "Sub-2" };
const accountOf: AccountOf = (id) =>
  LABELS[id] === undefined ? null : { label: LABELS[id] ?? "", environment: "live" };
const AT = Date.UTC(2026, 9, 22, 14, 5, 9);
const OWNER: WatermarkInput = {
  displayName: "sam",
  role: "owner",
  accounts: ["Main"],
  environment: "LIVE",
  atMs: AT,
};

afterEach(() => vi.unstubAllGlobals());

describe("the columns: D03:200's, in order", () => {
  it("the header line is D03:200's list", () => {
    const header = fillColumns(accountOf).map((c) => c.header);
    expect(repoFile("docs/design/E29/E29-D03.md").split("\n")[199]).toContain(header.join(", "));
  });

  it("board 02's fills: raw decimals, the fee as carried (positive paid), liquidity words", () => {
    const csv = fillsCsv(orderRows("limit"), accountOf, OWNER).split("\r\n");
    expect(csv[2]).toBe(
      `2026-10-22T14:02:11.418Z,Main,live,BTCUSDT,buy,Trade,63410,0.1,6341,3.48755,USDT,0.00055,taker,,7f3c9a1e-4219-438b-b30a-32ec86300004,${ORDER_A3F2},`,
    );
    expect(csv).toHaveLength(2 + 4 + 1); // watermark, header, four fills, the final CRLF
  });

  it("a fill of no order, a leg's trade group, a rebate: empty cells, never a guess", () => {
    const rows = rowsOf(restItems(), "rest");
    const lines = fillsCsv(rows, accountOf, OWNER).split("\r\n");
    expect(lines[2]?.split(",").slice(1, 6)).toEqual([
      "Sub-2",
      "live",
      "BTCUSDT",
      "sell",
      "AdlTrade",
    ]);
    expect(lines[2]?.endsWith(",,")).toBe(true); // no order, no trade group
    expect(
      lines
        .find((l) => l.includes("32ec86300010"))
        ?.endsWith(",0c000000-0000-4000-8000-000000007c1e"),
    ).toBe(true);
    const [first] = orderRows("limit");
    if (first === undefined) throw new Error("golden");
    const rebate = fillsCsv([{ ...first, fee: "-0.12" }], accountOf, OWNER).split("\r\n")[2];
    expect(rebate?.split(",")[9]).toBe("-0.12");
  });

  it("an account the directory does not name is a blank cell, never its id", () => {
    const [first] = orderRows("limit");
    if (first === undefined) throw new Error("golden");
    const line = fillsCsv([first], () => null, OWNER).split("\r\n")[2] ?? "";
    expect(line.split(",")[1]).toBe("");
    expect(line).not.toContain(first.accountId);
  });

  it("a text cell that would be a formula is guarded; numbers stay numbers (D-21)", () => {
    const [first] = orderRows("limit");
    if (first === undefined) throw new Error("golden");
    const hostile: AccountOf = () => ({ label: '=HYPERLINK("x")', environment: "+live" });
    const line = fillsCsv([{ ...first, symbol: "@SUM" }], hostile, OWNER).split("\r\n")[2] ?? "";
    expect(line.startsWith(`2026-10-22T14:02:11.418Z,"'=HYPERLINK(""x"")",'+live,'@SUM,`)).toBe(
      true,
    );
  });
});

describe("the watermark, line 1 (SR-098, BQ-4)", () => {
  it("names the Owner, the accounts and the time: D03:303's fixture line", () => {
    expect(watermark(OWNER)).toBe(
      "# CandleViewer fills export — not the audit trail · exported by sam (Owner) · accounts: Main (LIVE) · generated 2026-10-22 14:05:09 UTC",
    );
    expect(fillsCsv([], accountOf, OWNER).split("\r\n")[0]).toBe(watermark(OWNER));
  });

  it("a Manager's names them and only their accounts, as D03:301 draws it", () => {
    const line = watermark({
      ...OWNER,
      displayName: "alex",
      role: "manager",
      accounts: ["Sub-1", "Sub-2"],
    });
    expect(line).toContain(
      `${D03_TEXT.exportedByManager.string} · accounts: Sub-1 (LIVE), Sub-2 (LIVE)`,
    );
    expect(line).not.toContain("Main");
    expect(
      fillsCsv([], accountOf, { ...OWNER, accounts: ["Sub-1", "Sub-2"] }).startsWith('"#'),
    ).toBe(true);
  });

  it("while viewing as someone it says so", () => {
    expect(watermark({ ...OWNER, viewingAs: "alex" })).toContain(
      "exported by sam (Owner), viewing as alex ·",
    );
  });

  it("a Viewer's role is PROPOSED text", () => {
    expect(watermark({ ...OWNER, displayName: "alex", role: "viewer" })).toContain(
      PROPOSED_TEXT.exportedByViewer.string,
    );
  });

  it("the Owner's role is the deck's text", () => {
    expect(DECK["fills.export.watermark"].string).toContain(ROLE_PART.owner);
  });

  it("a name or a label is never read as a later span", () => {
    const line = watermark({ ...OWNER, displayName: "Main LIVE (Owner)", accounts: ["LIVE desk"] });
    expect(line).toBe(
      "# CandleViewer fills export — not the audit trail · exported by Main LIVE (Owner) (Owner) · accounts: LIVE desk (LIVE) · generated 2026-10-22 14:05:09 UTC",
    );
  });

  it("a line break in a name stays inside the quoted first line (RFC 4180)", () => {
    const csv = fillsCsv([], accountOf, { ...OWNER, displayName: "sam\r\n=cmd" });
    expect(csv.startsWith('"# CandleViewer')).toBe(true);
    expect(csv.split('"').length).toBe(3);
  });
});

describe("the file name and what the export does not do", () => {
  it("D03:200's name for an order; the tab's PROPOSED one", () => {
    expect(fillsCsvName(AT, ORDER_A3F2)).toBe(D03_TEXT.fileName.string);
    expect(fillsCsvName(AT)).toBe(PROPOSED_TEXT.tabFileName.string);
  });

  it("fetches nothing and reports no analytics event (the caller emits execution.exported)", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const events = vi.fn();
    window.addEventListener(THEME_ANALYTICS_EVENT, events);
    fillsCsv(orderRows("limit"), accountOf, OWNER);
    window.removeEventListener(THEME_ANALYTICS_EVENT, events);
    expect(fetch).not.toHaveBeenCalled();
    expect(events).not.toHaveBeenCalled();
  });
});
