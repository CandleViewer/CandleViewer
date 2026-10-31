/**
 * E08-S08 (#4702 PR (c)): SCR-101's symbol text (E08-D07 §4.4, D14): a paste or a file read into tokens, the preview's
 * groups against the list and the instrument index, a file's name as a list's name, a free name, and the export.
 */
import { describe, expect, it } from "vitest";
import {
  cleanName,
  exportFile,
  freeName,
  groupSymbols,
  nameOfFile,
  tokensOf,
  unknownTokens,
  type GroupFacts,
} from "../../../src/features/watchlist/manager/symbolText";

const TRADING = new Set(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "1000PEPEUSDT"]);
const facts = (onList: readonly string[] = []): GroupFacts => ({
  onList: new Set(onList),
  trading: (s) => TRADING.has(s),
  delisted: (s) => s === "LUNAUSDT",
});

describe("tokensOf (§4.4)", () => {
  it("splits on newlines, commas, semicolons, spaces and tabs; trims, upper-cases and collapses duplicates", () => {
    expect(tokensOf("btcusdt, ethusdt;solusdt\tXRPUSDT\r\n  ethusdt  \n\n")).toEqual([
      "BTCUSDT",
      "ETHUSDT",
      "SOLUSDT",
      "XRPUSDT",
    ]);
  });

  it("drops a line that starts with #, and empty tokens", () => {
    expect(
      tokensOf('# CandleViewer watchlist "Majors", 2 symbols\nBTCUSDT\n  # note\n,,;\nETHUSDT'),
    ).toEqual(["BTCUSDT", "ETHUSDT"]);
  });

  it("reads nothing from an empty or comment-only text", () => {
    expect(tokensOf("")).toEqual([]);
    expect(tokensOf("# only a comment\n\n")).toEqual([]);
  });
});

describe("groupSymbols (§4.4's preview)", () => {
  it("groups each token once: to add, already on the list, not found, delisted, not a symbol", () => {
    const groups = groupSymbols(
      ["BTCUSDT", "SOLUSDT", "DOGEUSDT", "LUNAUSDT", "BTC-PERP", "1000PEPEUSDT"],
      facts(["BTCUSDT"]),
    );
    expect(groups).toEqual({
      add: ["SOLUSDT", "1000PEPEUSDT"],
      onList: ["BTCUSDT"],
      overCap: [],
      notFound: ["DOGEUSDT"],
      delisted: ["LUNAUSDT"],
      invalid: ["BTC-PERP"],
    });
  });

  it("a token that is no symbol shows cut at 24 characters", () => {
    const long = `${"X".repeat(30)}<B>`;
    expect(groupSymbols([long], facts()).invalid).toEqual([`${"X".repeat(24)}…`]);
  });

  it("past the 200 cap the rest are not added", () => {
    const onList = Array.from({ length: 198 }, (_, i) => `S${i}USDT`);
    const groups = groupSymbols(["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"], facts(onList));
    expect(groups.add).toEqual(["BTCUSDT", "ETHUSDT"]);
    expect(groups.overCap).toEqual(["SOLUSDT", "XRPUSDT"]);
  });

  it("the tokens a lookup could tell apart: the form of a symbol, neither Trading nor known delisted", () => {
    expect(unknownTokens(["BTCUSDT", "DOGEUSDT", "LUNAUSDT", "nope"], facts())).toEqual([
      "DOGEUSDT",
    ]);
  });
});

describe("names", () => {
  it("a file's name without its extension, trimmed, at most 80 characters", () => {
    expect(nameOfFile("Breakouts.txt")).toBe("Breakouts");
    expect(nameOfFile(" my.list.csv ")).toBe("my.list");
    expect(nameOfFile(".txt")).toBe(".txt");
    expect([...nameOfFile(`${"é".repeat(90)}.txt`)]).toHaveLength(80);
  });

  it("C-5335-08 / S-5335-02: a name drops its control and format characters (`22` refuses them); a file's runs of white space are one space", () => {
    expect(cleanName(" Core\u200b ")).toBe("Core");
    expect(cleanName("Al\u202ets\u0007")).toBe("Alts");
    expect(cleanName("\u200b\u202e\t")).toBe("");
    expect(nameOfFile("Break\u202eouts\u200b.txt")).toBe("Breakouts");
    expect(nameOfFile("My\t\tlist   2.csv")).toBe("My list 2");
    expect(nameOfFile("\u200b.txt")).toBe("");
  });

  it("a taken name gets ' 2', then ' 3' (trimmed, case-insensitive), within 80 characters", () => {
    expect(freeName("Watchlist", [])).toBe("Watchlist");
    expect(freeName("Watchlist", ["watchlist "])).toBe("Watchlist 2");
    expect(freeName("Majors copy", ["Majors copy", "MAJORS COPY 2"])).toBe("Majors copy 3");
    const long = "x".repeat(80);
    expect(freeName(long, [long])).toBe(`${"x".repeat(78)} 2`);
  });
});

describe("exportFile (§4.4 Export)", () => {
  it("one header line, then the symbols in order; a safe file name", () => {
    const file = exportFile(
      'Majors/Q4: "core"',
      ["BTCUSDT", "ETHUSDT"],
      new Date("2026-10-21T10:31:59Z"),
    );
    expect(file.fileName).toBe("Majors-Q4- -core-.txt");
    expect(file.text).toBe(
      '# CandleViewer watchlist "Majors/Q4: "core"", 2 symbols, exported 2026-10-21 10:31 UTC\nBTCUSDT\nETHUSDT\n',
    );
  });

  it("keeps letters and digits of any script, spaces, '_' and '-'", () => {
    expect(exportFile("Альты_2 x-y", [], new Date(0)).fileName).toBe("Альты_2 x-y.txt");
  });
});
