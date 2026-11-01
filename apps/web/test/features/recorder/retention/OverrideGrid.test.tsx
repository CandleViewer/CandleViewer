/**
 * E16-S03 (#485), SCR-141's override grid (E16-D03 §6's seven row kinds; E16-D06 KB-11, FM-08 to FM-10, SR-19, T2-06,
 * F-04): the rows over the `22` example (ETHUSDT's order-book deltas at 3 d Delete after; BTCUSDT pinned), kept in
 * state as the dialog keeps them. Presses are a browser's: focus, then the click.
 */
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { flushSync } from "react-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { GatedAnnounceProvider } from "@candleviewer/ui";
import type { WriteGate } from "../../../../src/features/recorder/retention/GlobalDefaults";
import {
  OverrideGrid,
  freeStreams,
  pendingDays,
  pendingSymbol,
  type PendingAdd,
} from "../../../../src/features/recorder/retention/OverrideGrid";
import {
  addOverride,
  load,
  setAction,
  setDays,
  stageRemoval,
  undoRemoval,
  type Draft,
  type StreamKind,
} from "../../../../src/features/recorder/retention/retentionModel";
import { POLICIES_DEFAULTS } from "./fixtures";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
async function serious(element: Element): Promise<unknown[]> {
  const res = await axe.run(element, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

const BASE = load(POLICIES_DEFAULTS.items);
const REASON = "Read-only while viewing as alex.";
let calls: unknown[][] = [];
let say = vi.fn<(text: string) => void>();
beforeAll(() => {
  // CMP-009 keeps its active option in view; jsdom lays nothing out.
  Element.prototype.scrollIntoView = vi.fn();
});
beforeEach(() => {
  calls = [];
  say = vi.fn();
});

interface HostProps {
  readonly draft?: Draft;
  readonly gate?: WriteGate | null;
}

/** The grid in state, as the dialog holds it: the draft, the add row, every call recorded. */
function Host({ draft: initial = BASE, gate = null }: HostProps) {
  const [draft, setDraft] = useState(initial);
  const [pending, setPending] = useState<PendingAdd | null>(null);
  const globals = new Map(
    draft.rows.filter((r) => r.symbol === null).map((r) => [r.stream, r] as const),
  );
  return (
    <GatedAnnounceProvider announce={say}>
      <p id="notice">{REASON}</p>
      <OverrideGrid
        rows={draft.rows.filter((r) => r.symbol !== null)}
        pending={pending}
        globals={globals}
        pinned={new Set(["BTCUSDT"])}
        symbols={["BTCUSDT", "ETHUSDT"]}
        fieldId={(key) => `field-${key.symbol ?? ""}-${key.stream}`}
        gate={gate}
        onDays={(key, n) => {
          calls.push(["days", key.symbol, key.stream, n]);
          setDraft((d) => setDays(d, key, n));
        }}
        onAction={(key, action) => {
          calls.push(["action", key.symbol, key.stream, action]);
          setDraft((d) => setAction(d, key, action));
        }}
        onRemove={(key) => {
          calls.push(["remove", key.symbol, key.stream]);
          setDraft((d) => stageRemoval(d, key));
        }}
        onUndo={(key) => {
          calls.push(["undo", key.symbol, key.stream]);
          setDraft((d) => undoRemoval(d, key));
        }}
        onAdd={() => {
          calls.push(["add"]);
          setPending((p) =>
            p === null
              ? { id: 1, symbol: "", stream: "trades", days: null, action: "archive_parquet" }
              : { ...p, id: p.id + 1 },
          );
        }}
        onPending={(next) => {
          calls.push(["pending", next]);
          setPending(next);
        }}
        say={say}
      />
    </GatedAnnounceProvider>
  );
}

const grid = (): HTMLElement => screen.getByRole("grid", { name: "Per-symbol overrides" });
const rowOf = (symbol: string): HTMLElement => {
  const header = within(grid()).getByRole("rowheader", { name: symbol });
  return header.closest("tr") as HTMLElement;
};
const press = (control: HTMLElement): void => {
  act(() => control.focus());
  fireEvent.click(control);
};
/**
 * Esc as a browser delivers a user's key: a microtask checkpoint follows each listener, so React's update from the
 * capture phase commits before the bubble phase (A-5353-02). A scripted event in jsdom never does that; a capture
 * listener on the cell flushes it there, outside `act`, as the browser would.
 */
function userEscape(target: HTMLElement): KeyboardEvent {
  const cell = target.closest("td") as HTMLElement;
  const flush = (): void => flushSync(() => undefined);
  const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean | undefined };
  const was = env.IS_REACT_ACT_ENVIRONMENT;
  env.IS_REACT_ACT_ENVIRONMENT = false;
  cell.addEventListener("keydown", flush, true);
  const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  try {
    target.dispatchEvent(event);
  } finally {
    cell.removeEventListener("keydown", flush, true);
    env.IS_REACT_ACT_ENVIRONMENT = was;
  }
  return event;
}
const CASE = { timeout: 20_000 } as const;

describe("the row kinds (D03 §6, board 04)", CASE, () => {
  it("row-symbol: the 22 override, its controls named by row, Status '—', Remove names its object", () => {
    render(<Host />);
    expect(screen.getByRole("group", { name: "Per-symbol overrides" })).toHaveAccessibleDescription(
      "A symbol's rule wins over the global default.",
    );
    expect(
      within(grid())
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Symbol", "Stream", "Retention (days)", "Action", "Status", "Remove"]);
    const row = rowOf("ETHUSDT");
    expect(row).toHaveTextContent("Order-book deltas");
    const field = within(row).getByRole("spinbutton", {
      name: "ETHUSDT order-book deltas Retention (days)",
    });
    expect(field).toHaveValue("3");
    expect(field).toHaveAttribute("aria-valuetext", "3 days");
    expect(
      within(row).getByRole("combobox", { name: "ETHUSDT order-book deltas Action" }),
    ).toHaveTextContent("Delete after");
    expect(within(row).getAllByRole("gridcell")[3]).toHaveTextContent("—");
    expect(
      within(row).getByRole("button", { name: "Remove ETHUSDT order-book deltas rule" }),
    ).toBeVisible();
  });

  it("row-pinned-exempt: a pinned symbol's rule stays editable and says Exempt (pinned)", () => {
    const draft = setDays(
      addOverride(BASE, "BTCUSDT", "trades"),
      { symbol: "BTCUSDT", stream: "trades" },
      14,
    );
    render(<Host draft={draft} />);
    const row = rowOf("BTCUSDT");
    expect(row).toHaveTextContent("Exempt (pinned)");
    const field = within(row).getByRole("spinbutton");
    expect(field).not.toHaveAttribute("aria-disabled");
    fireEvent.keyDown(field, { key: "ArrowUp" });
    expect(calls).toEqual([["days", "BTCUSDT", "trades", 15]]);
  });

  it("row-invalid: 0 days marks the field and says 'Keep at least 1 day.' in the Status, politely", () => {
    render(<Host />);
    const field = within(rowOf("ETHUSDT")).getByRole("spinbutton");
    act(() => field.focus());
    fireEvent.change(field, { target: { value: "0" } });
    fireEvent.blur(field);
    expect(field).toHaveAttribute("aria-invalid", "true");
    const line = within(rowOf("ETHUSDT")).getByText("Keep at least 1 day.");
    expect(line).toHaveAttribute("aria-live", "polite");
    expect(field).toHaveAccessibleDescription(expect.stringContaining("Keep at least 1 day."));
  });

  it("row-removed: Remove stages it, struck, with the rule it follows; Undo has focus, said once (FM-09, SR-19)", () => {
    render(<Host />);
    press(
      within(rowOf("ETHUSDT")).getByRole("button", {
        name: "Remove ETHUSDT order-book deltas rule",
      }),
    );
    expect(calls).toEqual([["remove", "ETHUSDT", "orderbook_delta"]]);
    const row = rowOf("ETHUSDT");
    expect(row).toHaveTextContent("Removed: follows the global rule (7 d)");
    expect(within(row).queryByRole("spinbutton")).toBeNull();
    const undo = within(row).getByRole("button", { name: "Undo" });
    expect(undo).toHaveFocus();
    expect(undo).toHaveAccessibleDescription("Removed: follows the global rule (7 d)");
    expect(say.mock.calls).toEqual([["Removed: follows the global rule (7 d)"]]);
  });

  it("Remove shows its verb; its object is in its name only (A-5353-06)", () => {
    render(<Host />);
    const remove = within(rowOf("ETHUSDT")).getByRole("button", {
      name: "Remove ETHUSDT order-book deltas rule",
    });
    const hidden = remove.querySelector(".cv-visually-hidden");
    expect(hidden).toHaveTextContent("ETHUSDT order-book deltas rule");
    expect(remove.textContent?.replace(hidden?.textContent ?? "", "")).toBe("Remove");
  });

  it("Undo: the row returns and focus stays in the cell, now Remove (FM-10, F-04)", () => {
    render(<Host />);
    press(
      within(rowOf("ETHUSDT")).getByRole("button", {
        name: "Remove ETHUSDT order-book deltas rule",
      }),
    );
    press(within(rowOf("ETHUSDT")).getByRole("button", { name: "Undo" }));
    expect(calls.at(-1)).toEqual(["undo", "ETHUSDT", "orderbook_delta"]);
    const remove = within(rowOf("ETHUSDT")).getByRole("button", {
      name: "Remove ETHUSDT order-book deltas rule",
    });
    expect(remove).toHaveFocus();
    expect(rowOf("ETHUSDT")).not.toHaveTextContent("Removed:");
    // SR-19, BQ-07 (c): the Status words that return, said once (C-5353-07).
    expect(say.mock.calls).toEqual([["Removed: follows the global rule (7 d)"], ["—"]]);
  });

  it("row-add: a new row with focus on its Symbol, Trades at the global days, Move to Parquet after (FM-08)", () => {
    render(<Host />);
    press(screen.getByRole("button", { name: "Add override" }));
    const symbol = within(grid()).getByRole("combobox", { name: "Symbol" });
    expect(symbol).toHaveFocus();
    expect(within(grid()).getByRole("combobox", { name: "Stream" })).toHaveTextContent("Trades");
    expect(within(grid()).getByRole("spinbutton", { name: "Retention (days)" })).toHaveValue("30");
    expect(within(grid()).getByRole("combobox", { name: "Action" })).toHaveTextContent(
      "Move to Parquet after",
    );
    // A second press while the row has no symbol keeps one row and puts focus back on its Symbol.
    act(() => screen.getByRole("button", { name: "Add override" }).focus());
    fireEvent.click(screen.getByRole("button", { name: "Add override" }));
    expect(within(grid()).getAllByRole("combobox", { name: "Symbol" })).toHaveLength(1);
    expect(within(grid()).getByRole("combobox", { name: "Symbol" })).toHaveFocus();
  });

  it("row-add: the Stream offers only the streams the symbol has no rule for (no pair twice)", () => {
    render(<Host />);
    press(screen.getByRole("button", { name: "Add override" }));
    const symbol = within(grid()).getByRole("combobox", { name: "Symbol" });
    fireEvent.change(symbol, { target: { value: "ETHUSDT" } });
    fireEvent.click(within(grid()).getByRole("combobox", { name: "Stream" }));
    const offered = screen.getAllByRole("option").map((o) => o.textContent);
    expect(offered).not.toContain("Order-book deltas");
    expect(offered).toContain("Trades");
  });

  it("Remove on the add row drops it and returns focus to Add override", () => {
    render(<Host />);
    press(screen.getByRole("button", { name: "Add override" }));
    // The row names its object as far as it is chosen: no symbol yet, so its stream.
    press(within(grid()).getByRole("button", { name: "Remove trades rule" }));
    expect(within(grid()).queryByRole("combobox", { name: "Symbol" })).toBeNull();
    expect(screen.getByRole("button", { name: "Add override" })).toHaveFocus();
  });

  it("row-view-as: every control T2 with its full label, pointing at the one notice; a press does nothing", () => {
    render(<Host gate={{ reason: REASON, noticeId: "notice" }} />);
    const row = rowOf("ETHUSDT");
    expect(within(row).getByRole("spinbutton")).toHaveAttribute("aria-disabled", "true");
    const remove = within(row).getByRole("button", {
      name: "Not available Remove ETHUSDT order-book deltas rule",
    });
    expect(remove).toHaveAccessibleDescription(REASON);
    const add = screen.getByRole("button", { name: "Not available Add override" });
    expect(add).toHaveAccessibleDescription(REASON);
    press(remove);
    press(add);
    expect(calls).toEqual([]);
    expect(say.mock.calls).toEqual([[REASON], [REASON]]);
  });
});

describe("the grid's keys (KB-11; CMP-049 grid mode)", CASE, () => {
  it("Enter edits a cell; Esc leaves the edit with the value unchanged and focus on the cell", () => {
    render(<Host />);
    const field = within(rowOf("ETHUSDT")).getByRole("spinbutton");
    const cell = field.closest("td") as HTMLElement;
    act(() => cell.focus());
    fireEvent.keyDown(cell, { key: "Enter" });
    expect(field).toHaveFocus();
    fireEvent.change(field, { target: { value: "9" } });
    fireEvent.keyDown(field, { key: "Escape" });
    expect(cell).toHaveFocus();
    expect(calls).toEqual([]);
    expect(within(rowOf("ETHUSDT")).getByRole("spinbutton")).toHaveValue("3");
  });

  it("Esc as a browser sends it ends the edit there: prevented, focus on the cell, the value unchanged (A-5353-02)", async () => {
    render(<Host />);
    const field = within(rowOf("ETHUSDT")).getByRole("spinbutton");
    const cell = field.closest("td") as HTMLElement;
    act(() => cell.focus());
    fireEvent.keyDown(cell, { key: "Enter" });
    fireEvent.change(field, { target: { value: "9" } });
    const event = userEscape(field);
    await act(async () => undefined);
    expect(event.defaultPrevented).toBe(true);
    expect(cell).toHaveFocus();
    expect(calls).toEqual([]);
    expect(within(rowOf("ETHUSDT")).getByRole("spinbutton")).toHaveValue("3");
  });

  it("Esc after arrow steps restores the value the edit began with (each step committed)", async () => {
    render(<Host />);
    const field = within(rowOf("ETHUSDT")).getByRole("spinbutton");
    const cell = field.closest("td") as HTMLElement;
    act(() => cell.focus());
    fireEvent.keyDown(cell, { key: "Enter" });
    fireEvent.keyDown(field, { key: "ArrowUp" });
    fireEvent.keyDown(within(rowOf("ETHUSDT")).getByRole("spinbutton"), { key: "ArrowUp" });
    expect(within(rowOf("ETHUSDT")).getByRole("spinbutton")).toHaveValue("5");
    userEscape(within(rowOf("ETHUSDT")).getByRole("spinbutton"));
    await act(async () => undefined);
    expect(within(rowOf("ETHUSDT")).getByRole("spinbutton")).toHaveValue("3");
    expect(calls.at(-1)).toEqual(["days", "ETHUSDT", "orderbook_delta", 3]);
    expect(cell).toHaveFocus();
  });

  it("the columns hold the stepper with four digits and 'Move to Parquet after' whole (A-5353-04)", () => {
    render(<Host />);
    // `em` of the table's font, measured in Chromium at both densities; Status takes what is left.
    expect([...grid().querySelectorAll("col")].map((col) => col.style.width)).toEqual([
      "9em",
      "12em",
      "13.5em",
      "15em",
      "",
      "6em",
    ]);
  });

  it("the grid is one Tab stop: its controls leave the Tab order", () => {
    render(<Host />);
    for (const control of within(grid()).getAllByRole("button")) {
      expect(control).toHaveAttribute("tabindex", "-1");
    }
  });
});

describe("the add row's rules (pure)", () => {
  const rows = BASE.rows.filter((r) => r.symbol !== null);
  const add = (patch: Partial<PendingAdd>): PendingAdd => ({
    id: 1,
    symbol: "",
    stream: "trades",
    days: null,
    action: "archive_parquet",
    ...patch,
  });
  it("freeStreams - ETHUSDT has order-book deltas already", () => {
    expect(freeStreams(rows, "ETHUSDT")).not.toContain("orderbook_delta" satisfies StreamKind);
    expect(freeStreams(rows, "BTCUSDT")).toHaveLength(8);
  });
  it("pendingSymbol - a recorded symbol (any case) whose stream is free; else null", () => {
    const symbols = ["BTCUSDT", "ETHUSDT"];
    expect(pendingSymbol(add({ symbol: " ethusdt " }), symbols, rows)).toBe("ETHUSDT");
    expect(
      pendingSymbol(add({ symbol: "ETHUSDT", stream: "orderbook_delta" }), symbols, rows),
    ).toBeNull();
    expect(pendingSymbol(add({ symbol: "SOLUSDT" }), symbols, rows)).toBeNull();
  });
  it("pendingDays - as typed, else the global row's while valid, else the seed", () => {
    const globals = new Map(
      BASE.rows.filter((r) => r.symbol === null).map((r) => [r.stream, r] as const),
    );
    expect(pendingDays(add({ days: 14 }), globals)).toBe(14);
    expect(pendingDays(add({}), globals)).toBe(30);
    const zero = new Map(globals).set("trades", {
      symbol: null,
      stream: "trades",
      days: 0,
      action: "drop",
      removed: false,
    });
    expect(pendingDays(add({}), zero)).toBe(30);
  });
});

describe("axe per row kind", CASE, () => {
  it("clean, with a staged removal and with an add row: no serious violation", async () => {
    const { container } = render(<Host />);
    press(
      within(rowOf("ETHUSDT")).getByRole("button", {
        name: "Remove ETHUSDT order-book deltas rule",
      }),
    );
    press(screen.getByRole("button", { name: "Add override" }));
    expect(await serious(container)).toEqual([]);
  });

  it("while viewing as: no serious violation", async () => {
    const { container } = render(<Host gate={{ reason: REASON, noticeId: "notice" }} />);
    expect(await serious(container)).toEqual([]);
  });
});
