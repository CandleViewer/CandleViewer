// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  GatedAnnounceProvider,
  RECORDER_REASONS,
  RecorderStatusRow,
  Table,
  recorderStatusColumns,
  type RecorderStatusRowData,
} from "../src/components/index.js";
import * as stories from "../src/components/RecorderStatusRow.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

// E16-D02 §4 and its hand-off (D02H tables 2, 3 and 5). The table variant renders through the stories' grid, the
// host side of the row contract; the stories hold D02 §1's sample rows on the host's clock, 10:31:02 UTC.
const { AutoChartOpen, Degraded, Lingering, ManualWithPosition, Pinned, Starting, Stopped } =
  composeStories(stories);
const NOW = Date.UTC(2026, 9, 20, 10, 31, 2);
const BTC: RecorderStatusRowData = {
  symbol: "BTCUSDT",
  reason: "manual",
  state: "recording",
  startedAt: "2026-09-01T09:00:00Z",
  depth: 200,
  diskUsageBytes: 34.8e9,
  dailyGrowthBytes: 0.71e9,
  retentionDays: null,
  pinned: true,
  now: NOW,
};
const SOL: RecorderStatusRowData = {
  ...BTC,
  symbol: "SOLUSDT",
  reason: "chart_open",
  startedAt: "2026-10-20T10:14:00Z",
  depth: 50,
  diskUsageBytes: 1.3e6,
  dailyGrowthBytes: 0.11e9,
  growthEstimated: true,
  retentionDays: 30,
  pinned: false,
  why: "SOLUSDT's chart has been open since 10:13 UTC.",
};
const CHART = "Recording stops 30 min after the last chart closes.";
const OWNER = "Only the owner can change recording.";
const NOTICE = "Read-only — only the owner can change recording.";

const button = (name: string): HTMLButtonElement =>
  within(document.body).getByRole("button", { name }) as HTMLButtonElement;
const iso = (ms: number): string => new Date(ms).toISOString();
const announced = (ui: JSX.Element): [JSX.Element, ReturnType<typeof fn>] => {
  const announce = fn();
  return [<GatedAnnounceProvider announce={announce}>{ui}</GatedAnnounceProvider>, announce];
};

describe("RecorderStatusRow (CMP-177), table variant: a row of the host's grid", () => {
  it("names the row and its controls as D02H table 3 does; the state icon stays hidden", async () => {
    const host = await mount(
      <>
        <Pinned />
        <AutoChartOpen stopBlockedReason={null} />
      </>,
    );
    const name = "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on";
    const row = within(host).getByRole("row", { name });
    expect(row).toHaveAttribute("aria-rowindex", "2");
    expect(within(row).getByRole("rowheader")).toHaveTextContent("BTCUSDT");
    expect(within(row).getByRole("button", { name: "Stop recording BTCUSDT" })).not.toHaveAttribute(
      "aria-disabled",
    );
    const keep = within(row).getByRole("switch", { name: "Keep BTCUSDT data forever" });
    expect(keep).toHaveAttribute("aria-checked", "true");
    expect(within(row).queryByRole("button", { name: /^Why is/ })).toBeNull();
    const why = button("Why is SOLUSDT recorded?");
    expect(why).toHaveAttribute("aria-expanded", "false");
    expect(why).toHaveAttribute("aria-controls");
    expect(within(host).getByText("Auto: chart")).toBeInTheDocument();
    expect(within(host).getByText("1.3 MB · 0.11/d est.")).toBeInTheDocument();
    const state = within(row).getByText("Recording").closest("td") ?? row;
    expect(within(state).queryByRole("img")).toBeNull();
    const cells = within(row).getAllByRole("gridcell");
    // CMP-049's interactive cells (Enter or F2 into their controls): Keep forever and the action here.
    const interactive = cells.map((c) => c.hasAttribute("data-cv-interactive"));
    expect(interactive).toEqual([false, false, false, false, false, false, true, true]);
  });

  it("gives the host's grid its columns in the row's cell order, each with its words", () => {
    const columns = recorderStatusColumns();
    // D02 §1 at 1440 × 900: px ÷ the root's 16 px, each its own minimum, so the grid stacks before it squeezes;
    // Action holds CMP-001's "Record again" with its lock (138 px, a measured deviation), State gives the room.
    expect(columns.map((c) => [c.header, c.widthEm, c.sortable, c.interactive])).toEqual([
      ["Symbol", 7.5, true, false],
      ["Reason", 9.375, false, true],
      ["State", 13.5, false, false],
      ["Since", 6.5, true, false],
      ["Depth", 4, false, false],
      ["Size", 9.375, true, false],
      ["Retention", 7.5, false, false],
      ["Keep forever", 5.625, false, true],
      ["Action", 8.625, false, true],
    ]);
    expect(columns.every((c) => c.minWidthEm === c.widthEm)).toBe(true);
    expect(columns.reduce((em, c) => em + (c.widthEm ?? 0), 0)).toBe(72); // 1152 px
    const ends = columns.filter((c) => c.numeric === undefined && c.align === "end");
    expect(ends.map((c) => c.header)).toEqual(["Since", "Depth", "Size"]);
    // D02 §1 at 1280 × 800: Since and Depth go to the row detail; 992 px in all.
    const narrow = recorderStatusColumns({ narrow: true });
    expect(narrow.map((c) => c.header)).toEqual([
      "Symbol",
      "Reason",
      "State",
      "Size",
      "Retention",
      "Keep forever",
      "Action",
    ]);
    expect(narrow.map((c) => c.widthEm)).toEqual([7.5, 9.375, 14, 9.375, 7.5, 5.625, 8.625]);
    expect(narrow.reduce((em, c) => em + (c.widthEm ?? 0), 0)).toBe(62);
    expect(columns.map((c) => c.cell(BTC))).toEqual([
      "BTCUSDT",
      "Manual",
      "Recording",
      "2026-09-01",
      "200",
      "34.8 GB · 0.71/d",
      "Forever",
      "on",
      "",
    ]);
  });

  it("a blocked Stop keeps its role and name, the named lock leading, its reason as its description", async () => {
    const onStop = fn();
    const [ui, announce] = announced(<AutoChartOpen onStop={onStop} />);
    await mount(ui);
    const stop = button("Not available Stop recording SOLUSDT");
    expect(stop).toHaveAttribute("aria-disabled", "true");
    expect(stop.disabled).toBe(false);
    expect(stop).toHaveAccessibleDescription(CHART);
    const lock = within(stop).getByRole("img", { name: "Not available" });
    expect(stop.firstElementChild).toContainElement(lock);
    // Composed on CMP-001 as CMP-055's controls are: the atom's T2, pointed at the row's reason node (2b here).
    expect(stop).toHaveAttribute("data-cmp", "CMP-001");
    expect(stop).toHaveAttribute("data-gated");
    await userEvent.click(stop);
    expect(onStop).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[CHART]]);
  });

  it("Enter and Space re-show the reason once each, a held key once, and send nothing (G-T2.3)", async () => {
    const onStop = fn();
    const [ui, announce] = announced(<ManualWithPosition onStop={onStop} />);
    await mount(ui);
    const stop = button("Not available Stop recording ETHUSDT");
    act(() => stop.focus());
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await userEvent.keyboard("{Enter>4/}");
    await userEvent.keyboard("[Space>4/]");
    const reason = "Stop is unavailable while a position is open.";
    expect(announce.mock.calls).toEqual([[reason], [reason], [reason], [reason]]);
    expect(onStop).not.toHaveBeenCalled();
  });

  it("a gate that engages and lifts keeps the element and its focus (D02 §9.1)", async () => {
    let set: (patch: Partial<RecorderStatusRowData>) => void = () => undefined;
    function Live(): JSX.Element {
      const [patch, setPatch] = useState<Partial<RecorderStatusRowData>>({
        stopBlockedReason: null,
      });
      set = setPatch;
      return <AutoChartOpen {...patch} />;
    }
    await mount(<Live />);
    const stop = button("Stop recording SOLUSDT");
    act(() => stop.focus());
    await act(async () => set({ stopBlockedReason: "chart_open" }));
    expect(button("Not available Stop recording SOLUSDT")).toBe(stop);
    expect(stop).toHaveFocus();
    await act(async () => set({ state: "lingering", lingerUntil: iso(NOW + 30e3) }));
    expect(button("Keep recording SOLUSDT")).toBe(stop);
    expect(stop).toHaveFocus();
    expect(within(document.body).getByText("Recording · stops in under a minute")).toBeVisible();
  });

  it("Record again is T2 at the symbol limit (T2-02); no row holds a live region (D02H table 5)", async () => {
    const host = await mount(
      <>
        <Stopped recordAgainBlockedReason="symbol_cap" />
        <Starting />
        <Lingering />
      </>,
    );
    const again = button("Not available Record ADAUSDT again");
    expect(again).toHaveAccessibleDescription("The symbol limit is reached.");
    expect(host.querySelectorAll("tbody [aria-live], tbody [role=status]")).toHaveLength(0);
  });

  it("Why? opens on Keep recording, which keeps recording and returns focus to Why? (F-03)", async () => {
    const onKeepRecording = fn();
    const onWhyOpen = fn();
    await mount(
      <AutoChartOpen
        stopBlockedReason={null}
        onKeepRecording={onKeepRecording}
        onWhyOpen={onWhyOpen}
      />,
    );
    const why = button("Why is SOLUSDT recorded?");
    await userEvent.click(why);
    const popover = within(document.body).getByRole("dialog", { name: "Recorded automatically" });
    expect(popover).toHaveTextContent("recording started 60 s later");
    expect(button("Keep recording SOLUSDT")).toHaveFocus();
    expect(onWhyOpen).toHaveBeenCalledTimes(1);
    await userEvent.click(button("Keep recording SOLUSDT"));
    expect(onKeepRecording).toHaveBeenCalledTimes(1);
    expect(why).toHaveAttribute("aria-expanded", "false");
    expect(why).toHaveFocus();
  });

  // axe walks three grids, which can take longer than the default 5 s on a loaded runner.
  it("has no serious axe violation", { timeout: 15_000 }, async () => {
    const host = await mount(
      <>
        <Pinned />
        <AutoChartOpen />
        <Degraded />
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

// E16-D02 §2 and §3 `paused` (board 04): while `accelerate_retention` holds, an unpinned row's Retention reads its
// days and the effective days the host passes (the reaper halves retention, `21-database-schema.md`).
describe("RecorderStatusRow (CMP-177), accelerated retention", () => {
  const { AcceleratedRetention } = composeStories(stories);

  it("an unpinned row reads '30 d → 15 d (accelerated)' in the grid and the card", async () => {
    const host = await mount(<AcceleratedRetention />);
    const row = within(host).getByRole("row", { name: /^ETHUSDT, manual/ });
    expect(within(row).getByText("30 d → 15 d (accelerated)")).toBeVisible();
    const card = await mount(
      <RecorderStatusRow {...SOL} retentionDays={7} retentionAcceleratedDays={3.5} />,
    );
    expect(within(card).getByText(/Retention 7 d → 3\.5 d \(accelerated\)/)).toBeInTheDocument();
    const words = recorderStatusColumns().find((c) => c.id === "retention");
    expect(words?.cell({ ...SOL, retentionDays: 30, retentionAcceleratedDays: 15 })).toBe(
      "30 d → 15 d (accelerated)",
    );
  });

  it("a pinned row stays Forever, a refused one a dash; no accelerated days, the plain days", async () => {
    const words = recorderStatusColumns().find((c) => c.id === "retention");
    expect(words?.cell({ ...BTC, retentionAcceleratedDays: 15 })).toBe("Forever");
    expect(words?.cell({ ...SOL, state: "refused", retentionAcceleratedDays: 15 })).toBe("—");
    expect(words?.cell({ ...SOL, retentionAcceleratedDays: null })).toBe("30 d");
  });
});

describe("RecorderStatusRow (CMP-177), standalone (SCR-103)", () => {
  it("Tab reaches Why?, then Keep forever, then the action (D02H table 2)", async () => {
    await mount(<RecorderStatusRow {...SOL} />);
    await userEvent.tab();
    expect(button("Why is SOLUSDT recorded?")).toHaveFocus();
    await userEvent.tab();
    expect(within(document.body).getByRole("switch")).toHaveFocus();
    await userEvent.tab();
    expect(button("Stop recording SOLUSDT")).toHaveFocus();
  });

  it("a state T2 shows its reason inline (2a), its one copy, with no echo", async () => {
    await mount(<RecorderStatusRow {...SOL} stopBlockedReason="chart_open" />);
    const stop = button("Not available Stop recording SOLUSDT");
    expect(stop).toHaveAccessibleDescription(CHART);
    await userEvent.hover(stop);
    expect(within(document.body).getAllByText(CHART)).toHaveLength(1);
  });

  it("ReadOnly: one notice describes every gated control; a press says the reason once (T2-03)", async () => {
    const onTogglePin = fn();
    const onStop = fn();
    const [ui, announce] = announced(
      <RecorderStatusRow
        {...SOL}
        writeReason="rbac.owner_only"
        onTogglePin={onTogglePin}
        onStop={onStop}
      />,
    );
    const host = await mount(ui);
    const notice = within(host).getByText(NOTICE);
    const keep = within(host).getByRole("switch", {
      name: "Not available Keep SOLUSDT data forever",
    });
    const stop = button("Not available Stop recording SOLUSDT");
    expect(stop).toHaveAttribute("data-cmp", "CMP-001");
    for (const control of [keep, stop]) {
      expect(control).toHaveAttribute("aria-describedby", notice.id);
      expect(control).toHaveAccessibleDescription(NOTICE);
      expect(control).toHaveAttribute("aria-disabled", "true");
    }
    act(() => keep.focus());
    await userEvent.keyboard(" ");
    await userEvent.click(stop);
    expect(announce.mock.calls).toEqual([[OWNER], [OWNER]]);
    expect(onTogglePin).not.toHaveBeenCalled();
    expect(onStop).not.toHaveBeenCalled();
    await userEvent.click(button("Why is SOLUSDT recorded?"));
    expect(button("Not available Keep recording SOLUSDT")).toHaveAccessibleDescription(OWNER);
  });

  it("ReadOnly while viewing as another user: the notice is the reason alone (D-16)", async () => {
    const host = await mount(
      <RecorderStatusRow {...BTC} writeReason="rbac.view_as" viewAsUser="Sam" />,
    );
    expect(within(host).getByText("Read-only while viewing as Sam.")).toBeInTheDocument();
    expect(within(host).queryByText(/Read-only —/)).toBeNull();
  });

  it(
    "stale and near the budget: the words kept, a stale tag, the share in words",
    { timeout: 15_000 },
    async () => {
      const host = await mount(
        <RecorderStatusRow {...BTC} stale diskLevel={1} budgetShare={0.17} />,
      );
      expect(within(host).getByRole("group")).toHaveAccessibleDescription(
        "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on, stale",
      );
      expect(within(host).getByText("stale")).toBeInTheDocument();
      expect(within(host).getByText(/34\.8 GB · 0\.71\/d · 17 % of budget/)).toBeInTheDocument();
      expect(await seriousViolations(host)).toEqual([]);
    },
  );
});

/** The row in the real CMP-049 grid: D02 §1's nine columns, or the narrow seven. */
const inGrid = (row: RecorderStatusRowData, narrow = false): JSX.Element => (
  <Table
    columns={recorderStatusColumns({ narrow })}
    rows={[row]}
    rowKey={(r) => r.symbol}
    caption="Recorded symbols"
    renderRow={(data, grid) => (
      <RecorderStatusRow {...data} variant="table" grid={grid} narrow={narrow} />
    )}
  />
);

describe("RecorderStatusRow (CMP-177) in CMP-049: the column plan, Enter, names and figures (#5309)", () => {
  it("narrow, the row draws no Since and no Depth (D02 §1 at 1280 × 800; D-5309-03)", async () => {
    const host = await mount(inGrid(BTC, true));
    const headers = within(host)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Symbol",
      "Reason",
      "State",
      "Size",
      "Retention",
      "Keep forever",
      "Action",
    ]);
    const row = within(host).getByRole("row", { name: /^BTCUSDT, manual/ });
    expect(within(row).getAllByRole("gridcell")).toHaveLength(6); // and the symbol's rowheader
    expect(row).not.toHaveTextContent("2026-09-01");
  });

  it("Enter on a cell with no control opens the row's detail, once per press (B-5309-03)", async () => {
    const onOpenDetail = fn();
    const host = await mount(inGrid({ ...BTC, onOpenDetail }));
    const row = within(host).getByRole("row", { name: /^BTCUSDT, manual/ });
    const [, state] = within(row).getAllByRole("gridcell");
    act(() => state?.focus());
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{Enter>3/}"); // a held key: its repeats open nothing more
    expect(onOpenDetail).toHaveBeenCalledTimes(2);
    // The symbol's cell is no control cell: Enter there opens it too, and its button is no Tab stop of its own.
    const symbol = within(row).getByRole("rowheader");
    expect(within(symbol).getByRole("button", { name: "BTCUSDT" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    act(() => symbol.focus());
    await userEvent.keyboard("{Enter}");
    expect(onOpenDetail).toHaveBeenCalledTimes(3);
    // A control cell: Enter is CMP-049's way into its control, and opens nothing.
    const stop = button("Stop recording BTCUSDT");
    act(() => (stop.closest("td") as HTMLElement).focus());
    await userEvent.keyboard("{Enter}");
    expect(stop).toHaveFocus();
    expect(onOpenDetail).toHaveBeenCalledTimes(3);
    // A press on the symbol's button opens it too, and hands the host's `() => void` no event (B-5309-10).
    await userEvent.click(within(symbol).getByRole("button", { name: "BTCUSDT" }));
    expect(onOpenDetail).toHaveBeenCalledTimes(4);
    expect(onOpenDetail).toHaveBeenLastCalledWith();
  });

  it.each<[string, Partial<RecorderStatusRowData>, string]>([
    [
      "silent",
      { pinned: false, state: "silent", lastEventAt: "2026-10-20T10:29:40Z" },
      "BTCUSDT, manual, no writes since 10:29:40, 34.8 GB, keep forever off",
    ],
    [
      "lingering",
      { ...SOL, state: "lingering", lingerUntil: iso(NOW + 23.5 * 60e3) },
      "SOLUSDT, auto: chart, recording since 20 Oct 2026, stops in 24 min, 1.3 MB, keep forever off",
    ],
    [
      "degraded",
      { state: "degraded", gapCount: 2 },
      "BTCUSDT, manual, degraded, stream unhealthy, 2 gaps in 24 h, 34.8 GB, keep forever on",
    ],
    [
      "recording by a position",
      { ...SOL, reason: "position_open", stopBlockedReason: "position_open" },
      "SOLUSDT, auto: position, recording since 20 Oct 2026, position, 1.3 MB, keep forever off",
    ],
  ])(
    "names a %s row with its start only on recording (B-5309-04, D-5309-12)",
    async (_, patch, name) => {
      const host = await mount(inGrid({ ...BTC, ...patch }));
      expect(within(host).getByRole("row", { name })).toBeInTheDocument();
    },
  );

  it("Size: '—' with nothing written, grouped figures, 1.0 GB from 999.95 MB (B-5309-12, A-5309-10)", () => {
    const size = recorderStatusColumns().find((c) => c.id === "size");
    const bare = { ...BTC, dailyGrowthBytes: null };
    expect(size?.cell({ ...bare, diskUsageBytes: null })).toBe("—");
    expect(size?.cell({ ...bare, diskUsageBytes: 999_960_000 })).toBe("1.0 GB");
    expect(size?.cell({ ...bare, diskUsageBytes: 999_940_000 })).toBe("999.9 MB");
    expect(size?.cell({ ...bare, diskUsageBytes: 1_188e9 })).toBe("1,188.0 GB");
  });

  it("the share of the budget takes its own line, end-aligned; no `numeric` cell (board 05, D-5309-03)", async () => {
    const host = await mount(inGrid({ ...BTC, diskLevel: 1, budgetShare: 0.17 }));
    const size = within(host).getByText("34.8 GB · 0.71/d · 17 % of budget");
    expect(size).toHaveClass("cv-rsr__num");
    expect(size.querySelector("br")).not.toBeNull();
    expect(size.closest("td")).not.toHaveAttribute("data-numeric");
    expect(within(host).getByRole("columnheader", { name: "Size" })).toHaveAttribute(
      "data-numeric",
    );
  });

  it("the State's words carry their whole text for CMP-049's echo while cut (D02 §9.1, B-5309-01)", async () => {
    const words = "Degraded · stream unhealthy · 2 gaps in 24 h";
    const host = await mount(inGrid({ ...BTC, state: "degraded", gapCount: 2 }));
    expect(within(host).getByText(words)).toHaveAttribute("data-cv-cut", words);
  });

  it("the Action cell's T2 reason is the grid's one echo on the cell (2b, D-5309-09)", async () => {
    await mount(inGrid({ ...SOL, stopBlockedReason: "chart_open" }));
    const stop = button("Not available Stop recording SOLUSDT");
    expect(stop.closest("td")).toHaveAttribute("data-cv-echo", CHART);
    expect(stop).toHaveAccessibleDescription(CHART);
  });

  it("the five §8.5 reasons verbatim, `{grace}` the policy's (B-5309-11)", async () => {
    expect(RECORDER_REASONS).toEqual({
      "recorder.stop_blocked.chart_auto": "Recording stops {grace} after the last chart closes.",
      "recorder.stop_blocked.chart_manual": "Stop is available once the last chart closes.",
      "recorder.stop_blocked.position_auto": "Recording continues while a position is open.",
      "recorder.stop_blocked.position_manual": "Stop is unavailable while a position is open.",
      "recorder.symbol_cap": "The symbol limit is reached.",
    });
    await mount(inGrid({ ...SOL, stopBlockedReason: "chart_open", graceSeconds: 5400 }));
    expect(button("Not available Stop recording SOLUSDT")).toHaveAccessibleDescription(
      "Recording stops 1 h 30 min after the last chart closes.",
    );
  });

  it("a write in flight: the action is busy and a press sends nothing (C-5309-13)", async () => {
    const onKeepRecording = fn();
    const lingering = { state: "lingering", lingerUntil: iso(NOW + 30e3) } as const;
    await mount(inGrid({ ...SOL, ...lingering, actionBusy: true, onKeepRecording }));
    const keep = button("Keep recording SOLUSDT");
    expect(keep).toHaveAttribute("aria-busy", "true");
    await userEvent.click(keep);
    expect(onKeepRecording).not.toHaveBeenCalled();
  });

  it("a T2 Keep forever: CMP-004's centred lock leads the label, named first (B-5309-09)", async () => {
    const host = await mount(<RecorderStatusRow {...SOL} writeReason="rbac.owner_only" />);
    const keep = within(host).getByRole("switch", {
      name: "Not available Keep SOLUSDT data forever",
    });
    const label = document.getElementById(keep.getAttribute("aria-labelledby") ?? "");
    expect(label?.firstElementChild).toHaveClass("cv-choice__lock");
  });
});

describe("RecorderStatusRow (CMP-177) stacked into cards (CMP-049's reflow; D-5309-07, D-5309-08)", () => {
  /** A ResizeObserver the test fires: CMP-049 measures its shell with one. */
  const observers: { readonly callback: ResizeObserverCallback; readonly targets: Element[] }[] =
    [];
  class FakeObserver {
    readonly targets: Element[] = [];
    constructor(readonly callback: ResizeObserverCallback) {
      observers.push(this);
    }
    observe(target: Element): void {
      this.targets.push(target);
    }
    unobserve(): void {}
    disconnect(): void {}
  }
  beforeEach(() => {
    observers.length = 0;
    vi.stubGlobal("ResizeObserver", FakeObserver);
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) =>
      el instanceof HTMLElement && el.dataset["cmp"] === "CMP-049"
        ? ({ fontSize: "16px" } as CSSStyleDeclaration)
        : real(el, pseudo),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
  /** CMP-049 measures a 300 px shell, under the columns' 72 em: it stacks. */
  const stack = async (): Promise<void> => {
    await act(async () => {
      for (const observer of observers) {
        const shell = observer.targets.find((t) => t.matches('[data-cmp="CMP-049"]'));
        if (shell === undefined) continue;
        const entry = {
          target: shell,
          contentRect: { width: 300 },
        } as unknown as ResizeObserverEntry;
        observer.callback([entry], observer as unknown as ResizeObserver);
      }
    });
  };

  it("a T2 reason shows inline under the action (2a), never echoed (D-5309-08)", async () => {
    const host = await mount(inGrid({ ...SOL, stopBlockedReason: "chart_open" }));
    await stack();
    expect(host.querySelector('[data-cmp="CMP-049"]')).toHaveAttribute("data-layout", "stacked");
    const stop = button("Not available Stop recording SOLUSDT");
    const reason = document.getElementById(stop.getAttribute("aria-describedby") ?? "");
    expect(reason).toHaveClass("cv-rsr__reason");
    expect(reason).toHaveTextContent(CHART);
    expect(stop.closest("td")).not.toHaveAttribute("data-cv-echo");
  });

  it("a control a frame removes hands focus to the row's next stop, else its previous (D-5309-07)", async () => {
    let set: (patch: Partial<RecorderStatusRowData>) => void = () => undefined;
    function Live(): JSX.Element {
      const [patch, setPatch] = useState<Partial<RecorderStatusRowData>>({});
      set = setPatch;
      return inGrid({ ...SOL, ...patch });
    }
    await mount(<Live />);
    await stack();
    const keep = (): HTMLElement =>
      within(document.body).getByRole("switch", { name: "Keep SOLUSDT data forever" });
    act(() => button("Why is SOLUSDT recorded?").focus());
    await act(async () => set({ reason: "manual" })); // Why? goes with the auto reason
    expect(keep()).toHaveFocus();
    act(() => button("Stop recording SOLUSDT").focus());
    await act(async () => set({ reason: "manual", state: "stopping" })); // no action while stopping
    expect(keep()).toHaveFocus();
  });
});

it("runs each RecorderStatusRow story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    if (name.startsWith("Contrast")) {
      // A theme story's theme is the preview's runtime: here it renders its grids and its card.
      const host = await mount(<Story />);
      expect(within(host).getAllByRole("grid", { name: "Recorded symbols" })).toHaveLength(2);
      host.remove(); // its grids' Tab stops are not the next story's
      continue;
    }
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    canvasElement.remove();
  }
});
