import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useState } from "react";
import { resetSharedThemeStores } from "@candleviewer/ui";
import { PreferencesProvider } from "../../../src/features/a11y-preferences";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { KeymapHost } from "../../../src/keymap/KeymapHost";
import { runCommand } from "../../../src/keymap/registry";
import { ChartTablePanel } from "../../../src/chart/a11y/ChartTablePanel";
import { useAmbientWriter } from "../../../src/chart/a11y/politeWriter";
import type { ChartTableSeries } from "../../../src/chart/a11y/series";
import { makeSeries } from "./fixture";

function reply(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}
function prefs(accessibility: Record<string, unknown>): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply({ accessibility })));
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  resetSharedThemeStores();
  clearAnnouncements();
});

const chart = <div role="figure" aria-label="BTCUSDT 1m chart" tabIndex={-1} />;
const series = makeSeries({ bars: 40 });
const politeText = (): string => document.querySelector('[aria-live="polite"]')?.textContent ?? "";

function Panel({ s = series }: { s?: ChartTableSeries }): JSX.Element {
  return (
    <ChartTablePanel
      title="BTCUSDT 1m"
      chart={chart}
      series={s}
      writeClipboard={async () => undefined}
    />
  );
}

function renderPanel(): void {
  render(
    <PreferencesProvider>
      <ShellAnnouncer />
      <KeymapHost />
      <Panel />
    </PreferencesProvider>,
  );
}

const altT = (): void => {
  fireEvent.keyDown(document.activeElement ?? window, { key: "t", code: "KeyT", altKey: true });
};

describe("SCR-045 entry from the chart panel header (equal status)", () => {
  it("is a named region with a Chart / Table group; the Table button opens the grid", async () => {
    prefs({});
    renderPanel();
    const region = screen.getByRole("region", { name: "BTCUSDT 1m" });
    const group = within(region).getByRole("group", { name: "Chart view" });
    const table = within(group).getByRole("button", { name: "Table" });
    expect(table).toHaveAttribute("aria-keyshortcuts", "Alt+T");
    expect(within(group).getByRole("button", { name: "Chart" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    table.focus();
    fireEvent.click(table);
    expect(table).toHaveAttribute("aria-pressed", "true");
    expect(within(region).getByRole("grid")).toBeInTheDocument();
    expect(table).toHaveFocus(); // a press keeps focus on the control
    fireEvent.click(within(group).getByRole("button", { name: "Chart" }));
    expect(within(region).queryByRole("grid")).toBeNull();
  });

  it("takes its heading level from the host", () => {
    prefs({});
    render(
      <PreferencesProvider>
        <ChartTablePanel
          title="BTCUSDT 1m"
          chart={chart}
          series={series}
          headingLevel={3}
          writeClipboard={async () => undefined}
        />
      </PreferencesProvider>,
    );
    expect(screen.getByRole("heading", { level: 3, name: "BTCUSDT 1m" })).toBeInTheDocument();
  });

  it("'Always show data tables' makes the table the panel's default view", async () => {
    prefs({ always_show_tables: true });
    renderPanel();
    await waitFor(() => expect(screen.getByRole("grid")).toBeInTheDocument());
    expect(screen.getByRole("figure", { hidden: true })).not.toBeVisible(); // kept mounted, hidden
  });
});

describe("Alt+T (chart.table_toggle)", () => {
  it("round trip: chart → table on the latest row → chart, each said once", () => {
    prefs({});
    renderPanel();
    screen.getByRole("figure").focus();
    act(() => altT());
    const grid = screen.getByRole("grid");
    expect(grid.contains(document.activeElement)).toBe(true);
    expect(document.activeElement?.closest("tr")).toHaveAttribute("aria-rowindex", "41");
    expect(politeText()).toBe("Data table, row 40 of 40");
    act(() => altT());
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("figure")).toHaveFocus();
    expect(politeText()).toBe("Chart view");
  });

  it("Esc with nothing selected or open returns to the chart, focus on its surface", () => {
    prefs({});
    renderPanel();
    screen.getByRole("figure").focus();
    act(() => altT());
    act(() => {
      fireEvent.keyDown(document.activeElement as Element, { key: "Escape" });
    });
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("figure")).toHaveFocus();
    expect(politeText()).toBe("Chart view");
  });

  it("back on a chart with nothing focusable, focus goes to the Table button, not the page", () => {
    prefs({});
    render(
      <PreferencesProvider>
        <ShellAnnouncer />
        <KeymapHost />
        <ChartTablePanel
          title="BTCUSDT 1m"
          chart={<div>loading</div>}
          series={series}
          writeClipboard={async () => undefined}
        />
      </PreferencesProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    act(() => screen.getByRole("grid").querySelector<HTMLElement>('[tabindex="0"]')?.focus());
    act(() => altT());
    expect(screen.queryByRole("grid")).toBeNull();
    expect(screen.getByRole("button", { name: "Table" })).toHaveFocus();
  });

  it("does nothing outside a chart panel", () => {
    prefs({});
    render(
      <PreferencesProvider>
        <KeymapHost />
        <button type="button">elsewhere</button>
        <Panel />
      </PreferencesProvider>,
    );
    screen.getByRole("button", { name: "elsewhere" }).focus();
    act(() => altT());
    expect(screen.queryByRole("grid")).toBeNull();
  });

  it("teardown: the handler is registered while a panel is mounted and released with the last", () => {
    prefs({});
    const two = render(
      <PreferencesProvider>
        <Panel />
        <Panel />
      </PreferencesProvider>,
    );
    expect(runCommand("chart.table_toggle")).toBe(true);
    two.rerender(
      <PreferencesProvider>
        <Panel />
      </PreferencesProvider>,
    );
    expect(runCommand("chart.table_toggle")).toBe(true);
    two.unmount();
    expect(runCommand("chart.table_toggle")).toBe(false);
  });
});

/** A 20 Hz tick stream: the table's last bar and the ambient "last price" field change every 50 ms. */
function Streaming({ onTick }: { onTick: (tick: (n: number) => void) => void }): JSX.Element {
  const [s, setS] = useState(series);
  const writer = useAmbientWriter(["last"]);
  useEffect(() => {
    onTick((n) => {
      setS((prev) => {
        const close = Int32Array.from(prev.candles.close);
        close[close.length - 1] = 20 + n;
        return { ...prev, candles: { ...prev.candles, close } };
      });
      writer.set("last", `Last price ${64000 + n / 2}`);
    });
  }, [onTick, writer]);
  return <Panel s={s} />;
}

describe("Gherkin 2: streaming does not flood or steal", () => {
  it("at 20 Hz with the 2 s cadence: ≤ 1 polite write per 2 s with the latest value, focus kept", async () => {
    prefs({ announce_prices: "always", always_show_tables: true });
    let tick: (n: number) => void = () => undefined;
    const view = render(
      <PreferencesProvider>
        <ShellAnnouncer />
        <Streaming onTick={(t) => (tick = t)} />
      </PreferencesProvider>,
    );
    await waitFor(() => expect(screen.getByRole("grid")).toBeInTheDocument());
    vi.useFakeTimers();
    clearAnnouncements();
    const stop = screen.getByRole("grid").querySelector<HTMLElement>('[tabindex="0"]');
    act(() => stop?.focus());
    fireEvent.keyDown(document.activeElement as Element, { key: "ArrowDown" });
    const selected = document.activeElement;
    expect(selected?.closest("tr")).toHaveAttribute("aria-current", "true");
    const writes = new Map<string, string>();
    for (let n = 1; n <= 200; n++) {
      act(() => {
        tick(n);
        vi.advanceTimersByTime(50);
      });
      const p = document.querySelector('[aria-live="polite"] p');
      if (p !== null && p.textContent?.startsWith("Last price")) {
        writes.set(p.getAttribute("data-seq") ?? "", p.textContent);
      }
      expect(document.activeElement).toBe(selected);
    }
    act(() => vi.advanceTimersByTime(2_000));
    const last = document.querySelector('[aria-live="polite"] p');
    if (last !== null) writes.set(last.getAttribute("data-seq") ?? "", last.textContent ?? "");
    expect(writes.size).toBeGreaterThan(0);
    expect(writes.size).toBeLessThanOrEqual(10_000 / 2_000 + 1);
    expect([...writes.values()].at(-1)).toBe("Last price 64100");
    expect(document.activeElement).toBe(selected);
    view.unmount();
    act(() => vi.runAllTimers()); // the writer was disposed with the panel: no timer left behind
    expect(vi.getTimerCount()).toBe(0);
  });
});
