// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import {
  Callout,
  ChartLegend,
  GatedAnnounceProvider,
  RbacGate,
  formatRbacReason,
  type ChartLegendItem,
  type ChartLegendProps,
} from "../src/components/index.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

afterEach(() => vi.restoreAllMocks());

const page = within(document.body);
const row = (id: string, over: Partial<ChartLegendItem> = {}): ChartLegendItem => ({
  id,
  label: id.toUpperCase().replace("-", " "),
  kind: "line",
  colorToken: "color.indicator.palette.2",
  marker: "line",
  value: 3398.12,
  visible: true,
  ...over,
});
const ITEMS = [
  row("price", { label: "ETHUSDT 5m", marker: "bar" }),
  row("ema-21", { label: "EMA 21" }),
];
const props = (over: Partial<ChartLegendProps> = {}): ChartLegendProps => ({
  items: ITEMS,
  paneLabel: "Price",
  collapsed: false,
  onToggleVisible: fn(),
  onRemove: fn(),
  onQuickEdit: fn(),
  ...over,
});
const live = (): string => document.getElementById("cv-theme-live-region")?.textContent ?? "";
const tabStops = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-nav]")).filter((n) => n.tabIndex === 0);

describe("ChartLegend (CMP-199)", () => {
  it("is a named group of rows whose eye keeps the stable name and carries the state in aria-pressed", async () => {
    await mount(
      <ChartLegend
        {...props({
          items: [ITEMS[0] as ChartLegendItem, row("ema-21", { label: "EMA 21", visible: false })],
        })}
      />,
    );
    expect(page.getByRole("group", { name: "Price legend" })).toBeTruthy();
    expect(page.getByRole("button", { name: "EMA 21 visible" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(page.getByRole("button", { name: "ETHUSDT 5m visible" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(page.getAllByRole("listitem")[2]).toHaveTextContent("EMA 21 hidden—");
  });

  it("has one tab stop and moves it with the arrows, never wrapping (KL-01)", async () => {
    await mount(<ChartLegend {...props()} />);
    expect(tabStops()).toHaveLength(1);
    page.getByRole("button", { name: "Collapse Price" }).focus();
    await userEvent.keyboard("{ArrowUp}");
    expect(page.getByRole("button", { name: "Collapse Price" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toHaveTextContent("3,398.12");
    expect(document.activeElement?.closest("li")).toHaveAttribute("aria-current", "true");
    await userEvent.keyboard("{ArrowRight}");
    expect(page.getByRole("button", { name: "ETHUSDT 5m visible" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(page.getByRole("button", { name: "EMA 21 visible" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(document.activeElement).toHaveTextContent("3,398.12");
    expect(tabStops()).toHaveLength(1);
  });

  it("toggles the row on Space and announces it once, politely, by name", async () => {
    const p = props();
    await mount(<ChartLegend {...p} />);
    page.getByRole("button", { name: "EMA 21 visible" }).focus();
    await userEvent.keyboard(" ");
    expect(p.onToggleVisible).toHaveBeenCalledWith("ema-21", false);
    expect(live()).toBe("EMA 21 hidden");
  });

  it("lets Space activate the focused control: Remove removes, the eye is not toggled", async () => {
    const p = props();
    await mount(<ChartLegend {...p} />);
    page.getByRole("button", { name: "Remove EMA 21" }).focus();
    await userEvent.keyboard(" ");
    expect(p.onRemove).toHaveBeenCalledWith("ema-21");
    expect(p.onToggleVisible).not.toHaveBeenCalled();
  });

  it("moves focus to the neighbouring row when a row is removed", async () => {
    const Host = (): JSX.Element => {
      const [items, setItems] = useState(ITEMS);
      return (
        <ChartLegend
          {...props({ items, onRemove: (id) => setItems((is) => is.filter((i) => i.id !== id)) })}
        />
      );
    };
    await mount(<Host />);
    await userEvent.click(page.getByRole("button", { name: "Remove EMA 21" }));
    expect(page.getByRole("button", { name: "Remove ETHUSDT 5m" })).toHaveFocus();
  });

  it("names the value button by what it edits", async () => {
    await mount(<ChartLegend {...props({ items: [row("ema-21", { label: "EMA 21" })] })} />);
    expect(
      page.getByRole("button", {
        name: "3,398.12 — Edit primary parameter (per descriptor) for EMA 21",
      }),
    ).toBeTruthy();
  });

  it("applies the row cap after a collapsed legend is expanded", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
    // The pane row is 0 high (collapsed-state measure would use it); only the series rows measure 24.
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains("cv-chart-legend__pane") ? 0 : this.matches("li") ? 24 : 0;
    });
    const items = Array.from({ length: 13 }, (_, i) => row(`ema-${i}`, { label: `EMA ${i}` }));
    await mount(<ChartLegend {...props({ items, collapsed: true })} />);
    await userEvent.click(page.getByRole("button", { name: "Expand Price" }));
    expect(page.getAllByRole("button", { name: /visible$/ })).toHaveLength(7);
  });

  it("does not steal focus later when the host ignored the removal", async () => {
    const Host = (): JSX.Element => {
      const [items, setItems] = useState(ITEMS);
      return (
        <>
          <button type="button" onClick={() => setItems([...ITEMS])}>
            refresh
          </button>
          <ChartLegend {...props({ items, onRemove: () => undefined })} />
        </>
      );
    };
    await mount(<Host />);
    await userEvent.click(page.getByRole("button", { name: "Remove EMA 21" }));
    await userEvent.click(page.getByRole("button", { name: "refresh" }));
    expect(page.getByRole("button", { name: "refresh" })).toHaveFocus();
  });

  /** A host whose removal lands later (a server round trip), re-rendering `items` in between as value ticks do. */
  const asyncHost = (): { Host: () => JSX.Element; commit: () => void; tick: () => void } => {
    let setItems: (
      next: (is: readonly ChartLegendItem[]) => readonly ChartLegendItem[],
    ) => void = () => undefined;
    let removed: string | null = null;
    const Host = (): JSX.Element => {
      const [items, set] = useState<readonly ChartLegendItem[]>(ITEMS);
      setItems = set;
      return (
        <>
          <button type="button">elsewhere</button>
          <ChartLegend
            {...props({
              items,
              onRemove: (id) => {
                removed = id;
              },
            })}
          />
        </>
      );
    };
    return {
      Host,
      tick: () => act(() => setItems((is) => is.map((i) => ({ ...i, value: (i.value ?? 0) + 1 })))),
      commit: () => act(() => setItems((is) => is.filter((i) => i.id !== removed))),
    };
  };

  it("keeps the focus hand-off across re-renders that still hold the removed row", async () => {
    const { Host, tick, commit } = asyncHost();
    await mount(<Host />);
    await userEvent.click(page.getByRole("button", { name: "Remove EMA 21" }));
    tick();
    commit();
    expect(page.getByRole("button", { name: "Remove ETHUSDT 5m" })).toHaveFocus();
  });

  it("leaves focus where the user moved it before the removal landed", async () => {
    const { Host, commit } = asyncHost();
    await mount(<Host />);
    await userEvent.click(page.getByRole("button", { name: "Remove EMA 21" }));
    await userEvent.click(page.getByRole("button", { name: "elsewhere" }));
    commit();
    expect(page.getByRole("button", { name: "elsewhere" })).toHaveFocus();
  });

  it("lets the focus hand-off lapse after the 10 s removal window", async () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(1_000);
    const { Host, commit } = asyncHost();
    await mount(<Host />);
    await userEvent.click(page.getByRole("button", { name: "Remove EMA 21" }));
    now.mockReturnValue(11_001);
    commit();
    expect(document.activeElement).toBe(document.body);
  });

  it("keeps the quick-edit's Esc inside the field: an enclosing popover does not see it", async () => {
    // A popover or dialog host listens above the legend's React root, as Radix's dismiss layer does.
    const outer = vi.fn<(event: KeyboardEvent) => void>();
    document.body.addEventListener("keydown", outer);
    const p = props({ items: [row("ema-21", { label: "EMA 21", editing: { param: "Period" } })] });
    await mount(<ChartLegend {...p} />);
    await userEvent.type(page.getByRole("spinbutton", { name: "Period for EMA 21" }), "{Escape}");
    document.body.removeEventListener("keydown", outer);
    expect(outer.mock.calls.filter(([event]) => event.key === "Escape")).toEqual([]);
  });

  it("says the gated reason once per Enter press, not per key repeat (T2-07)", async () => {
    const announce = vi.fn<(text: string) => void>();
    const reason = formatRbacReason("rbac.view_as", { user: "Dana" });
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Callout id="n" title={reason} live="off" />
        <RbacGate
          form="notice"
          noticeId="n"
          allowed={false}
          reason="rbac.view_as"
          fills={{ user: "Dana" }}
        >
          <ChartLegend
            {...props({
              items: [row("ema-21", { label: "EMA 21", editing: { param: "Period" } })],
            })}
          />
        </RbacGate>
      </GatedAnnounceProvider>,
    );
    const field = page.getByRole("spinbutton", { name: "Period for EMA 21" });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.keyDown(field, { key: "Enter", repeat: true });
    fireEvent.keyDown(field, { key: "Enter", repeat: true });
    expect(announce.mock.calls).toEqual([[reason]]);
  });

  it("never shows fewer than 3 rows, however short the pane", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(24);
    const items = Array.from({ length: 6 }, (_, i) => row(`ema-${i}`, { label: `EMA ${i}` }));
    await mount(<ChartLegend {...props({ items })} />);
    expect(page.getAllByRole("button", { name: /visible$/ })).toHaveLength(3);
    expect(page.getByRole("button", { name: "3 more series" })).toBeTruthy();
  });

  it("never announces a value: values reach the legend only through props (BQ-07)", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    const p = props();
    await act(async () => root.render(<ChartLegend {...p} />));
    const before = live();
    await act(async () => {
      for (let i = 0; i < 1000; i += 1)
        root.render(<ChartLegend {...p} items={[row("ema-21", { value: i })]} />);
    });
    expect(page.getByRole("group")).toHaveTextContent("999");
    expect(live()).toBe(before);
    await act(async () => root.unmount());
  });

  it("expands and collapses a ribbon from its chevron with → and ←", async () => {
    const ribbon = row("ribbon", {
      label: "MA ribbon",
      children: [row("r-8", { label: "EMA 8" })],
    });
    await mount(<ChartLegend {...props({ items: [ribbon] })} />);
    page.getByRole("button", { name: "Expand MA ribbon" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(page.getByRole("button", { name: "Collapse MA ribbon" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(page.getByRole("button", { name: "EMA 8 visible" })).toBeTruthy();
    await userEvent.keyboard("{ArrowLeft}");
    expect(page.queryByRole("button", { name: "EMA 8 visible" })).toBeNull();
  });

  it("opens the quick-edit on Enter, commits on Enter and returns focus to the value", async () => {
    const p = props();
    await mount(<ChartLegend {...p} />);
    const value = page
      .getAllByRole("button")
      .find((b) => b.textContent === "3,398.12" && b.closest("li")?.textContent?.startsWith("EMA"));
    value?.focus();
    await userEvent.keyboard("{Enter}");
    const field = page.getByRole("spinbutton", {
      name: "primary parameter (per descriptor) for EMA 21",
    });
    expect(field).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(field).toHaveAttribute("aria-invalid", "true");
    await userEvent.type(field, "34{Enter}");
    expect(p.onQuickEdit).toHaveBeenCalledWith("ema-21", 34);
    expect(page.queryByRole("spinbutton")).toBeNull();
    expect(document.activeElement).toHaveTextContent("3,398.12");
  });

  it("reverts on Esc without committing", async () => {
    const p = props({ items: [row("ema-21", { label: "EMA 21", editing: { param: "Period" } })] });
    await mount(<ChartLegend {...p} />);
    await userEvent.type(page.getByRole("spinbutton", { name: "Period for EMA 21" }), "9{Escape}");
    expect(p.onQuickEdit).not.toHaveBeenCalled();
  });

  it("makes the quick-edit commit and Remove T2 under the frame's notice; the eye stays T1 (T2-04)", async () => {
    const p = props({ items: [row("ema-21", { label: "EMA 21", editing: { param: "Period" } })] });
    const reason = formatRbacReason("rbac.view_as", { user: "Dana" });
    await mount(
      <>
        <Callout id="n" title={reason} live="off" />
        <RbacGate
          form="notice"
          noticeId="n"
          allowed={false}
          reason="rbac.view_as"
          fills={{ user: "Dana" }}
        >
          <ChartLegend {...p} />
        </RbacGate>
      </>,
    );
    const field = page.getByRole("spinbutton", { name: "Period for EMA 21" });
    expect(field).toHaveAttribute("aria-disabled", "true");
    expect(field).toHaveAttribute("aria-describedby", "n");
    // The lock leads the field's label and badges the Remove icon (2b).
    expect(page.getAllByRole("img", { name: "Not available" })).toHaveLength(2);
    expect(field).toHaveAttribute("readonly");
    await userEvent.type(field, "34{Enter}");
    expect(p.onQuickEdit).not.toHaveBeenCalled();
    expect(field.closest("li")?.querySelector(".cv-chart-legend__detail")).toHaveTextContent(
      reason,
    );
    const remove = page.getByRole("button", { name: "Remove EMA 21" });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(remove);
    expect(p.onRemove).not.toHaveBeenCalled();
    await userEvent.click(page.getByRole("button", { name: "EMA 21 visible" }));
    expect(p.onToggleVisible).toHaveBeenCalledWith("ema-21", false);
  });

  it("shows ⌊0.3 × pane / row⌋ rows (min 3) and the rest behind a focus-managed “+N more”", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(24);
    const items = Array.from({ length: 13 }, (_, i) => row(`ema-${i}`, { label: `EMA ${i}` }));
    await mount(<ChartLegend {...props({ items })} />);
    expect(page.getAllByRole("button", { name: /visible$/ })).toHaveLength(7);
    await userEvent.click(page.getByRole("button", { name: "6 more series" }));
    expect(page.getByRole("dialog", { name: "6 more series" })).toHaveTextContent("EMA 12");
    await userEvent.keyboard("{Escape}");
    expect(page.getByRole("button", { name: "6 more series" })).toHaveFocus();
  });

  it("collapses to the one-line summary and words every state", async () => {
    const items = [
      row("a", { label: "A", visible: false }),
      row("b", { label: "B", error: "Compute failed: x." }),
      row("c", { label: "C", warmup: { needed: 34 }, value: null }),
      row("d", { label: "D", stale: { ageS: 7, lastGoodTs: "13:42:05" } }),
      row("e", { label: "E", provisional: true, usedByRules: true, estimated: true }),
      row("f", { label: "F", rebuilding: true, beforeHistory: { startsAt: "1 Sep" } }),
      row("g", { label: "A very long indicator label" }),
    ];
    await mount(
      <ChartLegend items={items} paneLabel="Price" collapsed={false} onToggleVisible={fn()} />,
    );
    const text = page.getByRole("group").textContent ?? "";
    for (const word of [
      "A hidden",
      "error",
      "Compute failed: x.",
      "34 more bars needed",
      "Stale 7s",
      "last 13:42:05",
      "provisional",
      "used by rules",
      "E (estimated)",
      "rebuilding…",
      "History starts 1 Sep",
      "A very long indicator label",
    ]) {
      expect(text).toContain(word);
    }
    expect(text).toContain("A very long indic…");
    await userEvent.click(page.getByRole("button", { name: "Collapse Price" }));
    expect(page.getByRole("group")).toHaveTextContent("Price7 series · 1 hidden");
  });

  it("has no serious or critical axe violation", async () => {
    const host = await mount(<ChartLegend {...props()} />);
    expect(await seriousViolations(host)).toEqual([]);
  });
});
