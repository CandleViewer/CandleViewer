// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  GatedAnnounceProvider,
  RecorderStatusRow,
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
    expect(columns.map((c) => [c.header, c.sortable, c.interactive])).toEqual([
      ["Symbol", true, true],
      ["Reason", false, true],
      ["State", false, false],
      ["Since", true, false],
      ["Depth", false, false],
      ["Size", true, false],
      ["Retention", false, false],
      ["Keep forever", false, true],
      ["Action", false, true],
    ]);
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

it("runs each RecorderStatusRow story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    canvasElement.remove();
  }
});
