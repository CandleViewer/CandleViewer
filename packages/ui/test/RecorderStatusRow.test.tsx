// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  GatedAnnounceProvider,
  RecorderStatusRow,
  Table,
  recorderStatusColumns,
  type RecorderStatusRowData,
  type RecorderStatusRowProps,
} from "../src/components/index.js";
import * as stories from "../src/components/RecorderStatusRow.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

// E16-D02 §4 and its hand-off (D02H tables 2, 3 and 5), on D02 §1's sample rows; the host's clock is 10:31:02 UTC.
const NOW = Date.UTC(2026, 9, 20, 10, 31, 2);
const BTC: RecorderStatusRowProps = {
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
const SOL: RecorderStatusRowProps = {
  symbol: "SOLUSDT",
  reason: "chart_open",
  state: "recording",
  startedAt: "2026-10-20T10:14:00Z",
  depth: 50,
  diskUsageBytes: 1.3e6,
  dailyGrowthBytes: 0.11e9,
  growthEstimated: true,
  retentionDays: 30,
  why: "SOLUSDT's chart has been open since 10:13 UTC.",
  now: NOW,
};
const CHART = "Recording stops 30 min after the last chart closes.";
const OWNER = "Only the owner can change recording.";
const NOTICE = "Read-only — only the owner can change recording.";

const button = (name: string): HTMLButtonElement =>
  within(document.body).getByRole("button", { name }) as HTMLButtonElement;
const described = (el: HTMLElement): string =>
  document.getElementById(el.getAttribute("aria-describedby") ?? "")?.textContent ?? "";

function Grid({ rows }: { readonly rows: readonly RecorderStatusRowData[] }): JSX.Element {
  return (
    <Table
      grid
      caption="Recorded symbols"
      columns={recorderStatusColumns()}
      rows={rows}
      rowKey={(r) => r.symbol}
    />
  );
}

const announced = (ui: JSX.Element): [JSX.Element, ReturnType<typeof fn>] => {
  const announce = fn();
  return [<GatedAnnounceProvider announce={announce}>{ui}</GatedAnnounceProvider>, announce];
};

describe("RecorderStatusRow (CMP-177), table variant: CMP-049's columns", () => {
  it("names its controls and tags as D02H table 3 does; the state icon stays hidden", async () => {
    const host = await mount(<Grid rows={[BTC, SOL]} />);
    expect(button("Stop recording BTCUSDT")).not.toHaveAttribute("aria-disabled");
    const keep = within(host).getByRole("switch", { name: "Keep BTCUSDT data forever" });
    expect(keep).toHaveAttribute("aria-checked", "true");
    const why = button("Why is SOLUSDT recorded?");
    expect(why).toHaveAttribute("aria-expanded", "false");
    expect(why).toHaveAttribute("aria-controls");
    expect(within(host).queryByRole("button", { name: "Why is BTCUSDT recorded?" })).toBeNull();
    expect(within(host).getByText("Manual")).toBeInTheDocument();
    expect(within(host).getByText("Auto: chart")).toBeInTheDocument();
    expect(within(host).getByText("34.8 GB · 0.71/d")).toBeInTheDocument();
    expect(within(host).getByText("1.3 MB · 0.11/d est.")).toBeInTheDocument();
    const words = within(host).getAllByText("Recording")[0]?.closest("td") ?? host;
    expect(within(words).queryByRole("img")).toBeNull();
  });

  it("a blocked Stop keeps its role and name, the named lock leading, its reason as its description", async () => {
    const onStop = fn();
    const [ui, announce] = announced(
      <Grid rows={[{ ...SOL, stopBlockedReason: "chart_open", onStop }]} />,
    );
    await mount(ui);
    const stop = button("Not available Stop recording SOLUSDT");
    expect(stop).toHaveAttribute("aria-disabled", "true");
    expect(stop.disabled).toBe(false);
    expect(stop).toHaveAccessibleDescription(CHART);
    expect(described(stop)).toBe(CHART);
    const lock = within(stop).getByRole("img", { name: "Not available" });
    expect(stop.firstElementChild).toContainElement(lock);
    await userEvent.click(stop);
    expect(onStop).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[CHART]]);
  });

  it("Enter and Space re-show the reason once each, a held key once, and send nothing (G-T2.3)", async () => {
    const onStop = fn();
    const blocked = {
      ...SOL,
      reason: "manual",
      stopBlockedReason: "position_open",
      onStop,
    } as const;
    const [ui, announce] = announced(<Grid rows={[blocked]} />);
    await mount(ui);
    const stop = button("Not available Stop recording SOLUSDT");
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
    let set: (row: RecorderStatusRowData) => void = () => undefined;
    function Live(): JSX.Element {
      const [row, setRow] = useState<RecorderStatusRowData>(SOL);
      set = setRow;
      return <Grid rows={[row]} />;
    }
    await mount(<Live />);
    const stop = button("Stop recording SOLUSDT");
    act(() => stop.focus());
    await act(async () => set({ ...SOL, stopBlockedReason: "chart_open" }));
    expect(button("Not available Stop recording SOLUSDT")).toBe(stop);
    expect(stop).toHaveFocus();
    await act(async () => set({ ...SOL, state: "lingering", lingerUntil: iso(NOW + 23.5 * 60e3) }));
    expect(button("Keep recording SOLUSDT")).toBe(stop);
    expect(stop).toHaveFocus();
  });

  it("Keep recording, and Record again T2 at the symbol limit (T2-02)", async () => {
    const onKeepRecording = fn();
    const ada: RecorderStatusRowData = {
      ...BTC,
      symbol: "ADAUSDT",
      state: "stopped",
      stoppedAt: "2026-10-18T12:00:00Z",
      pinned: false,
      retentionDays: 30,
      recordAgainBlockedReason: "symbol_cap",
    };
    const lingering = { ...SOL, state: "lingering", lingerUntil: iso(NOW + 30e3) } as const;
    const host = await mount(<Grid rows={[{ ...lingering, onKeepRecording }, ada]} />);
    expect(within(host).getByText("Recording · stops in under a minute")).toBeInTheDocument();
    await userEvent.click(button("Keep recording SOLUSDT"));
    expect(onKeepRecording).toHaveBeenCalledTimes(1);
    expect(within(host).getByText("Stopped 18 Oct · gone by 17 Nov")).toBeInTheDocument();
    const again = button("Not available Record ADAUSDT again");
    expect(again).toHaveAccessibleDescription("The symbol limit is reached.");
  });

  it("a refused start has no control: no switch, no action, its retention a dash", async () => {
    const doge: RecorderStatusRowData = {
      ...SOL,
      symbol: "DOGEUSDT",
      state: "refused",
      refusal: "symbol_cap",
      symbolLimit: 20,
    };
    const host = await mount(<Grid rows={[doge]} />);
    expect(within(host).getByText("Not recording: 20-symbol limit reached")).toBeInTheDocument();
    expect(within(host).queryByRole("switch")).toBeNull();
    expect(
      within(host)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Why is DOGEUSDT recorded?"]);
  });

  it("Why? opens on Keep recording; Keep recording closes it, focus back on Why? (F-03)", async () => {
    const onKeepRecording = fn();
    const onWhyOpen = fn();
    await mount(<Grid rows={[{ ...SOL, onKeepRecording, onWhyOpen }]} />);
    const why = button("Why is SOLUSDT recorded?");
    await userEvent.click(why);
    const popover = within(document.body).getByRole("dialog", { name: "Recorded automatically" });
    expect(popover).toHaveTextContent("SOLUSDT's chart has been open since 10:13 UTC.");
    expect(button("Keep recording SOLUSDT")).toHaveFocus();
    expect(onWhyOpen).toHaveBeenCalledTimes(1);
    await userEvent.click(button("Keep recording SOLUSDT"));
    expect(onKeepRecording).toHaveBeenCalledTimes(1);
    expect(why).toHaveAttribute("aria-expanded", "false");
    expect(why).toHaveFocus();
  });

  it("1 Hz values change in place with no live region in a row (D02H table 5)", async () => {
    const host = await mount(<Grid rows={[BTC, { ...SOL, state: "starting", startedAt: null }]} />);
    const body = host.querySelector("tbody") as HTMLElement;
    expect(body.querySelectorAll("[aria-live], [role=status], [role=alert]")).toHaveLength(0);
    expect(within(host).getByText("Starting · initial book snapshot")).toBeInTheDocument();
  });

  it("has no serious axe violation", async () => {
    const rows: RecorderStatusRowData[] = [
      BTC,
      { ...SOL, stopBlockedReason: "chart_open" },
      { ...BTC, symbol: "ETHUSDT", state: "degraded", gapCount: 2, pinned: false },
    ];
    const host = await mount(<Grid rows={rows} />);
    expect(within(host).getByText("Degraded · stream unhealthy · 2 gaps in 24 h")).toBeVisible();
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("RecorderStatusRow (CMP-177), standalone (SCR-103)", () => {
  it("is a group named '{symbol} recording', its summary the description (RG-03)", async () => {
    const host = await mount(<RecorderStatusRow {...BTC} />);
    expect(
      within(host).getByRole("group", { name: "BTCUSDT recording" }),
    ).toHaveAccessibleDescription(
      "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on",
    );
  });

  it("Tab reaches Why?, then Keep forever, then the action (D02H table 2)", async () => {
    await mount(<RecorderStatusRow {...SOL} />);
    await userEvent.tab();
    expect(button("Why is SOLUSDT recorded?")).toHaveFocus();
    await userEvent.tab();
    expect(within(document.body).getByRole("switch")).toHaveFocus();
    await userEvent.tab();
    expect(button("Stop recording SOLUSDT")).toHaveFocus();
  });

  it("a state T2 shows its reason inline (2a), the one copy, and no echo", async () => {
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

  it("stale and near the budget: words kept, a stale tag, the share in words", async () => {
    const host = await mount(<RecorderStatusRow {...BTC} stale diskLevel={1} budgetShare={0.17} />);
    expect(within(host).getByRole("group")).toHaveAccessibleDescription(
      "BTCUSDT, manual, recording since 1 Sep 2026, 34.8 GB, keep forever on, stale",
    );
    expect(within(host).getByText("stale")).toBeInTheDocument();
    expect(within(host).getByText(/34\.8 GB · 0\.71\/d · 17 % of budget/)).toBeInTheDocument();
    expect(await seriousViolations(host)).toEqual([]);
  });
});

it("runs each RecorderStatusRow story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    canvasElement.remove();
  }
});

function iso(ms: number): string {
  return new Date(ms).toISOString();
}
