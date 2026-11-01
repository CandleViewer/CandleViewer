// E22-S01 (#714) PR-B, G-64: the Tape keymap context. Every Tape key but ←/→ reaches the panel
// through the app's keymap by focus context, each valid only where `keymap.json` says: `P` and the
// jumps on the panel, ↑/↓ on the grid (held, they repeat), Home / End, Enter and Esc on a row.
// All rebind in SCR-113 except Esc. ←/→ are the grid's own (the APG grid's cell keys).
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TapeEvent } from "../../../src/features/tape/view/tapeController";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import { KEYMAP } from "../../../src/keymap/keymap";
import { TapePanel } from "../../../src/features/tape/view/TapePanel";
import { fakeClient, fakeDisplay } from "./fakeFeed";
import { items, snap } from "./frames";

const mount = (locate = vi.fn(), onTapeEvent = vi.fn<(e: TapeEvent) => void>()) => {
  const fake = fakeClient();
  const display = fakeDisplay();
  render(
    <>
      <KeymapHost />
      <TapePanel
        symbol="BTCUSDT"
        enabled
        client={fake.client}
        clock={display.clock}
        transport="connected"
        fetchTrades={() => Promise.resolve([])}
        locate={locate}
        onTapeEvent={onTapeEvent}
      />
    </>,
  );
  const handle = fake.handles[0];
  if (handle === undefined) throw new Error("no subscription");
  handle.status = "live";
  handle.queue.push(snap(items(1, 120)));
  act(() => display.frame());
  const grid = screen.getByRole("grid", { name: "Tape BTCUSDT" });
  const pause = screen.getByRole("button", { name: "Pause tape (P)" });
  const status = screen.getByTestId("tape-status-row");
  return { grid, pause, display, status, locate, onTapeEvent };
};

describe("Tape keymap context", () => {
  it("registers the Tape commands in keymap.json, every one rebindable but Esc", () => {
    const tape = KEYMAP.filter((c) => c.context === "Tape");
    expect(Object.fromEntries(tape.map((c) => [c.id, c.defaultBinding]))).toEqual({
      "tape.pause_toggle": "P",
      "tape.row_prev": "↑",
      "tape.row_next": "↓",
      "tape.cell_first": "Home",
      "tape.cell_last": "End",
      "tape.jump_live": "Ctrl+Home",
      "tape.jump_oldest": "Ctrl+End",
      "tape.locate": "Enter",
      "tape.cancel": "Esc",
    });
    // Esc is the universal cancel, never remapped (`05` §3.3 rule 3); the rest rebind in SCR-113
    const locked = tape.filter((c) => c.editable === false).map((c) => c.id);
    expect(locked).toEqual(["tape.cancel"]);
  });

  it("KR-1: P with panel focus toggles the hard pause, and only the tape's", () => {
    const { grid, pause } = mount();
    act(() => grid.focus());
    fireEvent.keyDown(grid, { key: "p", code: "KeyP" });
    expect(pause).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(grid, { key: "p", code: "KeyP" });
    expect(pause).toHaveAttribute("aria-pressed", "false");
    act(() => grid.blur());
    fireEvent.keyDown(document.body, { key: "p", code: "KeyP" }); // outside the Tape context
    expect(pause).toHaveAttribute("aria-pressed", "false");
  });

  it("KR-3 / FP-08: Ctrl+End reaches the oldest row and Ctrl+Home the newest, the pause holding", () => {
    const { grid } = mount();
    act(() => grid.focus());
    fireEvent.keyDown(grid, { key: "ArrowDown" });
    fireEvent.keyDown(grid, { key: "End", ctrlKey: true });
    const oldest = grid.getAttribute("aria-activedescendant") ?? "";
    expect(
      document.getElementById(oldest)?.closest('[role="row"]')?.getAttribute("aria-rowindex"),
    ).toBe("121");
    fireEvent.keyDown(grid, { key: "Home", ctrlKey: true });
    const newest = grid.getAttribute("aria-activedescendant") ?? "";
    expect(
      document.getElementById(newest)?.closest('[role="row"]')?.getAttribute("aria-rowindex"),
    ).toBe("2");
    expect(screen.getByTestId("tape-status-row").textContent).toContain("Paused");
  });

  it("FP-12 / KR-7: the first arrow pauses on the newest row; arrows move the cursor; Esc resumes", () => {
    const t = mount();
    act(() => t.grid.focus());
    expect(t.grid).not.toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r0-c0$/);
    expect(t.status.textContent).toContain("Paused — 0 prints buffered");
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r1-c0$/);
    fireEvent.keyDown(t.grid, { key: "End", code: "End" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r1-c4$/);
    fireEvent.keyDown(t.grid, { key: "ArrowLeft", code: "ArrowLeft" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r1-c3$/);
    fireEvent.keyDown(t.grid, { key: "Home", code: "Home" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r1-c0$/);
    fireEvent.keyDown(t.grid, { key: "ArrowUp", code: "ArrowUp" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r0-c0$/);
    expect(fireEvent.keyDown(t.grid, { key: "Escape", code: "Escape" })).toBe(false); // used
    expect(t.grid).not.toHaveAttribute("aria-activedescendant"); // FP-05: no row active
    expect(document.activeElement).toBe(t.grid);
    expect(t.status.textContent).not.toContain("Paused");
    // nothing left to cancel: the key is not swallowed
    expect(fireEvent.keyDown(t.grid, { key: "Escape", code: "Escape" })).toBe(true);
  });

  it("KR-6: Enter on a row locates it and keeps focus there; on the pause button it presses it", () => {
    const t = mount();
    act(() => t.grid.focus());
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.keyDown(t.grid, { key: "Enter", code: "Enter" });
    expect(t.locate).toHaveBeenCalledTimes(1);
    expect(t.locate.mock.calls[0]?.[0]).toMatchObject({ symbol: "BTCUSDT", price: 65_000 });
    expect(document.activeElement).toBe(t.grid);
    act(() => t.pause.focus());
    // the row keys are the grid's only: Enter on the button is not taken from it
    expect(fireEvent.keyDown(t.pause, { key: "Enter", code: "Enter" })).toBe(true);
    expect(t.locate).toHaveBeenCalledTimes(1);
  });

  it("P13 / FP-06: Esc in a hard pause releases the selection and keeps the pause", () => {
    const t = mount();
    act(() => t.grid.focus());
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    fireEvent.keyDown(t.grid, { key: "p", code: "KeyP" });
    expect(t.pause).toHaveAttribute("aria-pressed", "true");
    expect(fireEvent.keyDown(t.grid, { key: "Escape", code: "Escape" })).toBe(false);
    expect(t.grid.querySelector('[aria-selected="true"]')).toBeNull();
    expect(t.pause).toHaveAttribute("aria-pressed", "true");
    expect(fireEvent.keyDown(t.grid, { key: "Escape", code: "Escape" })).toBe(true);
  });

  it("a held ↑ / ↓ moves one row per auto-repeat (a stepper, ignoreRepeat false)", () => {
    const t = mount();
    act(() => t.grid.focus());
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r0-c0$/);
    for (let k = 0; k < 3; k += 1) {
      fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown", repeat: true });
    }
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r3-c0$/);
    fireEvent.keyDown(t.grid, { key: "ArrowUp", code: "ArrowUp", repeat: true });
    fireEvent.keyDown(t.grid, { key: "ArrowUp", code: "ArrowUp", repeat: true });
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r1-c0$/);
  });

  it("Home / End are taken only on an active row; on the bare grid they keep their default", () => {
    const t = mount();
    act(() => t.grid.focus());
    // no row active: not swallowed, so the browser still scrolls the list
    expect(fireEvent.keyDown(t.grid, { key: "Home", code: "Home" })).toBe(true);
    expect(fireEvent.keyDown(t.grid, { key: "End", code: "End" })).toBe(true);
    expect(t.grid).not.toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    expect(fireEvent.keyDown(t.grid, { key: "End", code: "End" })).toBe(false);
    expect(t.grid.getAttribute("aria-activedescendant")).toMatch(/-r0-c4$/);
  });

  it("WCAG 2.4.7: with no row active the grid keeps its own focus ring; an active cell takes it over", () => {
    const t = mount();
    act(() => t.grid.focus());
    expect(t.grid).toHaveClass("cv-focus-ring");
    expect(t.grid.style.outline).toBe(""); // the CMP-039 ring is not suppressed
    fireEvent.keyDown(t.grid, { key: "ArrowDown", code: "ArrowDown" });
    expect(t.grid.style.outline).toBe("none"); // one ring: the active cell's
    const cell = document.getElementById(t.grid.getAttribute("aria-activedescendant") ?? "");
    expect(cell?.style.outline).toContain("solid");
    fireEvent.keyDown(t.grid, { key: "Escape", code: "Escape" }); // FP-05: no row active
    expect(t.grid).not.toHaveAttribute("aria-activedescendant");
    expect(t.grid.style.outline).toBe("");
  });

  it("BQ-212: a row click emits tape.print_clicked through onTapeEvent, with the print's fields", () => {
    const t = mount();
    const cell = t.grid.querySelector('[role="row"][aria-rowindex="3"] [role="gridcell"]');
    if (cell === null) throw new Error("no row 3");
    fireEvent.click(cell);
    expect(t.onTapeEvent).toHaveBeenCalledWith({
      type: "tape.print_clicked",
      ts_ms: 1_700_000_000_119,
      price: "65000.9",
      side: "sell",
      tier: 0,
      source: "row",
    });
    expect(t.locate).toHaveBeenCalledTimes(1);
  });
});
