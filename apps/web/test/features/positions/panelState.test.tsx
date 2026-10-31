/**
 * E29-S01 (#911, BQ-16) the panel's view state: per user on this device under one versioned key,
 * each stored field checked on its own, and R-130's `?groupBy=` / `?account=` deep links (applied,
 * never stored; `manager` is no value, BQ-10; `trade_group` has no deep-link form, D04-G2).
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyDeepLink,
  DEFAULT_PANEL_STATE,
  deepLinkSearch,
  getPanelState,
  PANEL_STORAGE_KEY,
  parsePanelState,
  readDeepLink,
  resetPanelState,
  setPanelUser,
  subscribePanelState,
  updateChips,
  updatePanelState,
  usePanelState,
} from "../../../src/features/positions/panelState";
import { MAIN, SUB1 } from "./support/fakes";

const KEY = `${PANEL_STORAGE_KEY}:user-1`;

beforeEach(() => {
  localStorage.clear();
  resetPanelState();
});
afterEach(() => vi.restoreAllMocks());

describe("persistence per user", () => {
  it("defaults for no one, then the user's stored view", () => {
    expect(getPanelState()).toBe(DEFAULT_PANEL_STATE);
    localStorage.setItem(
      KEY,
      JSON.stringify({
        v: 1,
        tab: "fills",
        groupBy: "symbol",
        chips: [],
        columns: {},
        density: "comfortable",
      }),
    );
    setPanelUser("user-1");
    expect(getPanelState()).toMatchObject({
      tab: "fills",
      groupBy: "symbol",
      density: "comfortable",
    });
    setPanelUser("user-2");
    expect(getPanelState()).toEqual(DEFAULT_PANEL_STATE);
  });

  it("an interactive change is stored under the versioned key", () => {
    setPanelUser("user-1");
    updatePanelState({ groupBy: "trade_group", columns: { positions: ["symbol", "upnl"] } });
    updateChips({ type: "add", chip: { kind: "account", value: SUB1 } });
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toEqual({
      v: 1,
      tab: "positions",
      groupBy: "trade_group",
      chips: [{ kind: "account", value: SUB1 }],
      columns: { positions: ["symbol", "upnl"] },
      density: "compact",
    });
  });

  it("no one signed in: the view holds for the page only", () => {
    updatePanelState({ density: "comfortable" });
    expect(getPanelState().density).toBe("comfortable");
    expect(localStorage.length).toBe(0);
  });

  it("storage that throws neither breaks reading nor the change", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    setPanelUser("user-1");
    updatePanelState({ tab: "algos" });
    expect(getPanelState()).toMatchObject({ tab: "algos" });
  });

  it("a stored value is checked field by field; another version is never guessed at", () => {
    expect(parsePanelState({ v: 2, tab: "fills" })).toBe(DEFAULT_PANEL_STATE);
    expect(parsePanelState("x")).toBe(DEFAULT_PANEL_STATE);
    expect(
      parsePanelState({
        v: 1,
        tab: "nope",
        groupBy: "manager",
        chips: [
          { kind: "account", value: MAIN.toUpperCase() },
          { kind: "account", value: "Main" },
        ],
        columns: { positions: ["upnl", "upnl", "Bad Id", 3], nope: ["x"], fills: "x" },
        density: "huge",
      }),
    ).toEqual({
      tab: "positions",
      groupBy: "account",
      chips: [{ kind: "account", value: MAIN }],
      columns: { positions: ["upnl"] },
      density: "compact",
    });
    localStorage.setItem(KEY, "{not json");
    setPanelUser("user-1");
    expect(getPanelState()).toEqual(DEFAULT_PANEL_STATE);
  });

  it("an unchanged chip list notifies no one", () => {
    const listener = vi.fn();
    const stop = subscribePanelState(listener);
    updateChips({ type: "remove", chip: { kind: "symbol", value: "BTCUSDT" } });
    expect(listener).not.toHaveBeenCalled();
    stop();
  });
});

describe("deep links (12 §7, R-130)", () => {
  it("reads groupBy and account; manager, trade_group and a malformed id are no value", () => {
    expect(readDeepLink(`?groupBy=symbol&account=${SUB1.toUpperCase()}`)).toEqual({
      groupBy: "symbol",
      account: SUB1,
    });
    expect(readDeepLink("?groupBy=manager")).toEqual({});
    expect(readDeepLink("?groupBy=trade_group&account=sub_001")).toEqual({});
    expect(readDeepLink("")).toEqual({});
  });

  it("opens the view the link names, without storing it", () => {
    setPanelUser("user-1");
    updateChips({ type: "add", chip: { kind: "account", value: MAIN } });
    const stored = localStorage.getItem(KEY);
    applyDeepLink(readDeepLink(`?groupBy=symbol&account=${SUB1}`));
    expect(getPanelState()).toMatchObject({
      groupBy: "symbol",
      chips: [{ kind: "account", value: SUB1 }],
    });
    expect(localStorage.getItem(KEY)).toBe(stored);
    applyDeepLink({});
    expect(getPanelState().groupBy).toBe("symbol");
  });

  it("a later unrelated change stores the user's own view, never the link's", () => {
    setPanelUser("user-1");
    updateChips({ type: "add", chip: { kind: "account", value: MAIN } });
    applyDeepLink(readDeepLink(`?groupBy=symbol&account=${SUB1}`));
    updatePanelState({ density: "comfortable" });
    expect(getPanelState()).toMatchObject({
      groupBy: "symbol",
      chips: [{ kind: "account", value: SUB1 }],
      density: "comfortable",
    });
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toMatchObject({
      groupBy: "account",
      chips: [{ kind: "account", value: MAIN }],
      density: "comfortable",
    });
  });

  it("a field changed after a link is stored as chosen; the link keeps the others", () => {
    setPanelUser("user-1");
    applyDeepLink(readDeepLink(`?groupBy=symbol&account=${SUB1}`));
    updatePanelState({ groupBy: "trade_group" });
    expect(getPanelState()).toMatchObject({
      groupBy: "trade_group",
      chips: [{ kind: "account", value: SUB1 }],
    });
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toMatchObject({
      groupBy: "trade_group",
      chips: [],
    });
    updateChips({ type: "add", chip: { kind: "symbol", value: "BTCUSDT" } }); // on the chips shown
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toMatchObject({
      chips: [
        { kind: "account", value: SUB1 },
        { kind: "symbol", value: "BTCUSDT" },
      ],
    });
    setPanelUser("user-1"); // the stored view again, with no link over it
    expect(getPanelState().chips).toHaveLength(2);
  });

  it("writes the link of a view", () => {
    expect(
      deepLinkSearch({
        ...DEFAULT_PANEL_STATE,
        groupBy: "symbol",
        chips: [{ kind: "account", value: SUB1 }],
      }),
    ).toBe(`?groupBy=symbol&account=${SUB1}`);
    expect(deepLinkSearch({ ...DEFAULT_PANEL_STATE, groupBy: "trade_group" })).toBe("");
  });
});

function GroupBy() {
  return <p>{usePanelState("groupBy")}</p>;
}

describe("usePanelState", () => {
  it("re-renders when its field changes", () => {
    render(<GroupBy />);
    expect(screen.getByText("account")).toBeInTheDocument();
    act(() => updatePanelState({ groupBy: "symbol" }));
    expect(screen.getByText("symbol")).toBeInTheDocument();
  });
});
