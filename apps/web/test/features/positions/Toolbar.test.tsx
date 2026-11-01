/**
 * E29-S01 (#911) the Positions toolbar (E29-D02 §9.1): Group by (CMP-009), the FilterBar (CMP-055) with
 * "+ Filter" opening the account picker (CMP-105), Columns (CMP-056's menu) and Export CSV. Each is a
 * read or a view choice: none is T2 and none is disabled, for any role (E29-D04 §4.2).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { POSITIONS_GRID_COLUMNS } from "@candleviewer/ui";
import {
  accountInfo,
  type AccountInfo,
  type ExchangeAccount,
} from "../../../src/features/positions/model/rowMapping";
import type { FilterChip } from "../../../src/features/positions/model/filters";
import {
  columnLabel,
  MANDATORY_COLUMNS,
  OPTIONAL_COLUMNS,
  Toolbar,
  type ToolbarProps,
} from "../../../src/features/positions/Toolbar";
import { golden, MAIN, SUB1, SUB2 } from "./support/fakes";

const accounts = golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
  .items.map(accountInfo)
  .filter((a): a is AccountInfo => a !== null);

function renderToolbar(over: Partial<ToolbarProps> = {}) {
  const props: ToolbarProps = {
    accounts,
    chips: [],
    groupBy: "account",
    columns: OPTIONAL_COLUMNS,
    onGroupBy: vi.fn(),
    onChips: vi.fn(),
    onColumns: vi.fn(),
    onExport: vi.fn(),
    ...over,
  };
  render(<Toolbar {...props} />);
  return props;
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn(); // jsdom lays nothing out
});

describe("the columns", () => {
  it("Account and Symbol stay out of the picker (BQ-6's interim); the rest in D02 §5.1's order and words", () => {
    expect(MANDATORY_COLUMNS).toEqual(["account", "symbol"]);
    expect([...MANDATORY_COLUMNS, ...OPTIONAL_COLUMNS]).toEqual(POSITIONS_GRID_COLUMNS);
    expect(OPTIONAL_COLUMNS.map(columnLabel)).toEqual([
      "Side",
      "Size",
      "Entry (USDT)",
      "Mark (USDT)",
      "uPnL (USDT)",
      "R",
      "rPnL today (USDT)",
      "Liq price (USDT)",
      "Liq dist. %",
      "Lev",
      "Margin",
    ]);
    expect(columnLabel("status")).toBe("Status");
  });
});

describe("Toolbar", () => {
  it("Group by: Account, Symbol, Trade group; a choice is handed up once", () => {
    const props = renderToolbar();
    const select = screen.getByRole("combobox", { name: "Group by" });
    expect(select).toHaveTextContent("Account");
    fireEvent.click(select);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Account",
      "Symbol",
      "Trade group",
    ]);
    fireEvent.click(screen.getByRole("option", { name: "Trade group" }));
    expect(props.onGroupBy).toHaveBeenCalledWith("trade_group");
    fireEvent.click(screen.getByRole("combobox", { name: "Group by" }));
    fireEvent.click(screen.getByRole("option", { name: "Account" }));
    expect(props.onGroupBy).toHaveBeenCalledTimes(1); // the same choice again is no change
  });

  it("the chips, each removable by name; Clear all from two", () => {
    const chips: FilterChip[] = [
      { kind: "account", value: SUB1 },
      { kind: "side", value: "long" },
    ];
    const props = renderToolbar({ chips });
    const group = screen.getByRole("group", { name: "Active filters" });
    fireEvent.click(within(group).getByRole("button", { name: "Remove filter Account: Sub-1" }));
    expect(props.onChips).toHaveBeenCalledWith({ type: "remove", chip: chips[0] });
    fireEvent.click(within(group).getByRole("button", { name: "Clear all" }));
    expect(props.onChips).toHaveBeenCalledWith({ type: "clear" });
  });

  it("+ Filter lists the server-scoped accounts; a press adds or drops one; Select all adds every one", () => {
    const props = renderToolbar({
      chips: [
        { kind: "account", value: SUB1 },
        { kind: "symbol", value: "BTCUSDT" },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const list = screen.getByRole("listbox", { name: "Filter" });
    expect(
      within(list)
        .getAllByRole("option")
        .map((o) => [o.textContent, o.getAttribute("aria-selected")]),
    ).toEqual([
      ["Main", "false"],
      ["Sub-1", "true"],
      ["Sub-2", "false"],
    ]);
    fireEvent.click(within(list).getByRole("option", { name: "Main" }));
    expect(props.onChips).toHaveBeenLastCalledWith({
      type: "add",
      chip: { kind: "account", value: MAIN },
    });
    fireEvent.click(within(list).getByRole("option", { name: "Sub-1" }));
    expect(props.onChips).toHaveBeenLastCalledWith({
      type: "remove",
      chip: { kind: "account", value: SUB1 },
    });
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(props.onChips).toHaveBeenLastCalledWith({
      type: "replace",
      chips: [
        { kind: "symbol", value: "BTCUSDT" },
        { kind: "account", value: MAIN },
        { kind: "account", value: SUB1 },
        { kind: "account", value: SUB2 },
      ],
    });
  });

  it("Columns shows and hides one column, keeping D02 §5.1's order", () => {
    const props = renderToolbar({ columns: ["side", "upnl"] });
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    const items = screen.getAllByRole("menuitemcheckbox");
    expect(items.map((i) => [i.textContent, i.getAttribute("aria-checked")]).slice(0, 5)).toEqual([
      ["Side", "true"],
      ["Size", "false"],
      ["Entry (USDT)", "false"],
      ["Mark (USDT)", "false"],
      ["uPnL (USDT)", "true"],
    ]);
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Size" }));
    expect(props.onColumns).toHaveBeenLastCalledWith(["side", "size", "upnl"]);
  });

  it("Export CSV hands the press up; no control is T2 or disabled", () => {
    const props = renderToolbar();
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(props.onExport).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll("[aria-disabled], [disabled]")).toHaveLength(0);
  });
});
