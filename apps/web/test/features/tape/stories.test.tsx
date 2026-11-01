// E22-S01 (#714) PR-B, BQ-216: every `Tape/SCR-053` story is a state fixture of the real panel.
// Each one renders its D02 state's deck strings, passes axe (zero serious or critical), and keeps
// at most 60 row nodes. The pause, keyboard and locate behaviours have their own cases below.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../../src/features/tape/view/TapePanel.stories";
import { TapeStateFixture } from "../../../src/features/tape/view/TapePanel.stories";
import { MAX_DOM_ROWS, ROW_HEIGHT_PX } from "../../../src/features/tape/view/gridWriter";
import { LIVE_OVERSCAN_ROWS } from "../../../src/features/tape/view/tapeController";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as {
  run: (
    el: Element,
    o?: object,
  ) => Promise<{ violations: { id: string; impact?: string | null; nodes: unknown[] }[] }>;
};

type State = Parameters<typeof TapeStateFixture>[0]["state"];

const show = (state: State, extra: Partial<Parameters<typeof TapeStateFixture>[0]> = {}) => {
  const view = render(<TapeStateFixture state={state} {...extra} />);
  const panel = screen.getByRole("region", { name: "Tape BTCUSDT" });
  return {
    ...view,
    panel,
    statusRow: () => screen.getByTestId("tape-status-row"),
    readout: () => screen.getByRole("note", { name: "tape speed" }),
    status: () => screen.getByRole("status", { name: "Tape status" }),
    grid: () => screen.getByRole("grid", { name: "Tape BTCUSDT" }),
    pause: () => screen.getByRole("button", { name: "Pause tape (P)" }),
  };
};

const perSecond = /^\d[\d ]* \/s \(1 s\) · \d+ \/frame$/;

describe("Tape/SCR-053 stories", () => {
  const all = Object.entries(stories).filter(
    (e): e is [string, { args: { state: State } }] =>
      typeof e[1] === "object" && e[1] !== null && "args" in e[1],
  );

  it("carries one story per state S01 owns (BQ-216), named after D05 §4.3", () => {
    expect(all.map(([name]) => name)).toEqual([
      "St01Streaming",
      "St02SoftPaused",
      "St03ScrollAwayPaused",
      "St04HardPaused",
      "St05Resumed",
      "St06ClickToLocate",
      "St07Delayed",
      "St08StaleT1",
      "St09StaleT2",
      "St10Disconnected",
      "St11Loading",
      "St12Empty",
      "St14PartialHistory",
      "St15ReconnectBackfillBefore",
      "St16ReconnectBackfillAfter",
      "St21ViewAsReadOnly",
      "St22PausedBufferFull",
    ]);
    expect(stories.default.title).toBe("Tape/SCR-053");
  });

  it.each(all)(
    "%s: axe finds nothing serious or critical, with at most 60 row nodes",
    async (_, story) => {
      const { panel } = show(story.args.state);
      await act(async () => {
        await Promise.resolve();
      });
      const result = await axe.run(panel, { rules: { "color-contrast": { enabled: false } } });
      const blocking = result.violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
      expect(blocking.map((v) => v.id)).toEqual([]);
      expect(panel.querySelectorAll('[role="row"]').length).toBeLessThanOrEqual(MAX_DOM_ROWS);
    },
    // an axe pass over a full 60-row grid; the per-test budget keymap-editor-axe.test.tsx uses
    30_000,
  );

  it("S1 streaming: rows newest first with ms times, a side glyph, the readout, no chip", () => {
    const t = show("S1");
    expect(t.readout().textContent).toMatch(perSecond);
    const rows = within(t.grid()).getAllByRole("row");
    expect(rows[0]?.textContent).toBe("TimePriceSizeNotionalSide");
    const first = rows[1] as HTMLElement;
    expect(first.getAttribute("aria-rowindex")).toBe("2");
    const cells = within(first).getAllByRole("gridcell");
    expect(cells[0]?.textContent).toMatch(/^\d\d:\d\d:\d\d\.\d{3}$/);
    expect(cells[1]?.textContent).toMatch(/^[▲▼]\d/);
    expect(first.getAttribute("aria-label")).toMatch(/^(Buy|Sell), /);
    // the side is the feed's: print 1400 is "buy" (n % 3 !== 0), the newest in the fixture
    expect(cells[4]?.textContent?.startsWith("Buy")).toBe(true);
    expect(t.statusRow().textContent).not.toMatch(/Paused|Stale|Offline/);
    expect(t.grid().getAttribute("aria-rowcount")).toBe("1401");
  });

  it("S2 / S4: a soft or hard pause shows the chip, freezes the list and keeps buffering", () => {
    for (const state of ["S2", "S4"] as const) {
      const t = show(state);
      expect(t.statusRow().textContent).toContain("Paused — 412 prints buffered");
      expect(t.readout().textContent).toMatch(/^\d[\d ]* \/s \(1 s\)$/); // the ladder drops "/frame"
      expect(t.grid().getAttribute("aria-rowcount")).toBe("1401"); // frozen: the 412 are not shown
      expect(t.pause().getAttribute("aria-pressed")).toBe(state === "S4" ? "true" : "false");
      t.unmount();
    }
  });

  it("S3: a scroll-away pause offers Jump to live, which resumes and inserts under a divider", () => {
    const t = show("S3");
    expect(t.statusRow().textContent).toContain("Paused — 412 prints buffered · Jump to live");
    fireEvent.click(screen.getByRole("button", { name: "Jump to live" }));
    expect(t.status().textContent).toBe("Resumed, 412 prints inserted");
    expect(t.statusRow().textContent).not.toContain("Paused");
  });

  it("S5: the resume inserts the buffered prints under one divider and says so once", () => {
    const t = show("S5");
    expect(t.status().textContent).toBe("Resumed, 412 prints inserted");
    expect(t.grid().getAttribute("aria-rowcount")).toBe("1813");
    expect(t.statusRow().textContent).not.toContain("Paused");
  });

  it("S6: a row click pauses, selects the row and locates the print on the charts", () => {
    const onLocate = vi.fn();
    const t = show("S6", { onLocate });
    expect(onLocate).toHaveBeenCalledTimes(1);
    expect(onLocate.mock.calls[0]?.[0]).toMatchObject({ symbol: "BTCUSDT" });
    const selected = within(t.grid())
      .getAllByRole("row")
      .find((r) => r.getAttribute("aria-selected") === "true");
    expect(selected?.getAttribute("aria-rowindex")).toBe("6");
    expect(t.statusRow().textContent).toContain("Paused — 0 prints buffered");
  });

  it("S7: a saturated feed adds no tape chip; every print is still a row", () => {
    const t = show("S7");
    expect(t.statusRow().textContent).not.toMatch(/Stale|Offline|Paused/);
    expect(t.grid().getAttribute("aria-rowcount")).toBe("1401");
  });

  it("S8 / S9: stale shows its age, the readout reads a dash, and T1 is said once", () => {
    const s8 = show("S8");
    expect(s8.statusRow().textContent).toContain("Stale 12s");
    expect(s8.readout().textContent).toBe("—");
    expect(s8.status().textContent).toBe("Tape stale 12 seconds.");
    s8.unmount();
    const s9 = show("S9");
    expect(s9.statusRow().textContent).toContain("Stale 30s");
  });

  it("S10: disconnected keeps the rows under the strip and gates the pause button with its reason", () => {
    const t = show("S10");
    expect(screen.getByText("Disconnected — last data 00:12")).toBeInTheDocument();
    expect(t.statusRow().textContent).toContain("Offline");
    expect(t.readout().textContent).toBe("—");
    const pause = t.pause();
    expect(pause).toHaveAttribute("aria-disabled", "true");
    expect(pause).not.toHaveAttribute("disabled");
    expect(pause).toHaveAccessibleDescription("Nothing to pause while disconnected.");
    expect(within(pause).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    fireEvent.click(pause);
    expect(pause).toHaveAttribute("aria-pressed", "false");
    expect(t.status().textContent).toBe("Nothing to pause while disconnected.");
    expect(t.grid().getAttribute("aria-rowcount")).toBe("1401");
  });

  it("S11: loading reads the word in the readout and the list, never a dash", () => {
    const t = show("S11");
    expect(t.readout().textContent).toBe("Loading…");
    expect(within(screen.getByRole("log")).getByText("Loading…")).toBeInTheDocument();
  });

  it("S12: an empty snapshot while live is quiet and names the last print history knows", async () => {
    const t = show("S12");
    expect(t.readout().textContent).toBe("0 /s · quiet");
    await waitFor(() =>
      expect(
        within(screen.getByRole("log")).getByText(/^No prints yet · last print \d\d:\d\d:\d\d$/),
      ).toBeInTheDocument(),
    );
  });

  it("S14: past the oldest print, an empty history page shows the partial-history seam", async () => {
    const onFetch = vi.fn();
    show("S14", { onFetch });
    await waitFor(() =>
      expect(
        screen.getByText(/^— No history before \d\d:\d\d:\d\d\. Recording started then\. —$/),
      ).toBeInTheDocument(),
    );
    expect(onFetch).toHaveBeenCalledTimes(1);
  });

  it("S15: a reconnect reseeds under a gap divider with the gapped chip and Load missed prints", () => {
    const t = show("S15");
    expect(t.statusRow().textContent).toContain("Reconstructed after gap");
    expect(screen.getByRole("button", { name: "Load missed prints" })).toBeInTheDocument();
    expect(t.status().textContent).toMatch(/^Reconnected — gap \S+ to \S+$/);
    const divider = screen.getByText(/^— gap \d\d:\d\d:\d\d\.\d{3} → \d\d:\d\d:\d\d\.\d{3} —$/);
    expect(divider.closest('[role="presentation"]')).not.toBeNull(); // a divider row, never a focus target
    // AC4: the snapshot reseeded without duplicating a row: 100 of its 120 were held already
    expect(t.grid().getAttribute("aria-rowcount")).toBe(String(1_400 + 20 + 1));
  });

  it("S16: the loaded missed prints sit under the divider, which then counts them", async () => {
    const t = show("S16");
    await waitFor(() => expect(t.status().textContent).toBe("3 missed prints loaded"));
    expect(screen.getByText("— 3 prints while disconnected —")).toBeInTheDocument();
    expect(t.statusRow().textContent).toContain("Reconstructed after gap"); // the chip outlives the load
    expect(screen.queryByRole("button", { name: "Load missed prints" })).toBeNull();
  });

  it("S21: view-as shows one notice under the header; pause stays T1", () => {
    const t = show("S21");
    expect(screen.getByText("Read-only while viewing as Dana.")).toBeInTheDocument();
    expect(t.pause()).not.toHaveAttribute("aria-disabled");
  });

  it("S22: a full ring while paused pins the window, counts what it did not keep, and says it on resume", () => {
    const t = show("S22");
    expect(t.statusRow().textContent).toMatch(/Paused — buffer full · \d[\d ]* kept/);
    fireEvent.click(t.pause());
    const said = t.status().textContent ?? "";
    expect(said).toMatch(/^Resumed, \d[\d ]* prints inserted, \d[\d ]* not kept$/);
    // live, the window is the viewport plus a small overscan (BQ-215): the divider sits under the
    // inserted prints, so scroll to it (which pauses again) before looking for its row
    const shown = () =>
      [...t.grid().querySelectorAll<HTMLElement>("[role=row][id], [role=presentation][id]")].filter(
        (r) => r.style.display === "flex",
      ).length;
    expect(shown()).toBe(25 + LIVE_OVERSCAN_ROWS); // jsdom's 25-row viewport, then the overscan
    const inserted = Number((said.split(" prints inserted")[0] ?? "").replace(/\D/g, ""));
    act(() => {
      t.grid().scrollTop = inserted * ROW_HEIGHT_PX;
      fireEvent.scroll(t.grid());
    });
    expect(
      screen.getByText(/^— \d[\d ]* prints while paused · \d[\d ]* not kept —$/),
    ).toBeInTheDocument();
    expect(shown()).toBeGreaterThan(25 + LIVE_OVERSCAN_ROWS); // paused: the whole pool again
  });
});

describe("tape pointer and focus (FP-07, KR-1's button)", () => {
  it("FP-07: focus leaving the list resumes it", () => {
    const t = show("S1");
    act(() => t.grid().focus());
    const cell = t.grid().querySelector('[role="row"][aria-rowindex="3"] [role="gridcell"]');
    fireEvent.click(cell as Element);
    expect(t.statusRow().textContent).toContain("Paused");
    act(() => t.pause().focus());
    expect(t.statusRow().textContent).not.toContain("Paused");
  });

  it("KR-1: the pause button toggles the hard pause and its pressed state", () => {
    const t = show("S1");
    fireEvent.click(t.pause());
    expect(t.pause()).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(t.pause());
    expect(t.pause()).toHaveAttribute("aria-pressed", "false");
  });
});
