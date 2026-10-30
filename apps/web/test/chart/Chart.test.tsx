import { act, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  Chart as ChartApi,
  ChartEvents,
  ChartOptions,
  FrameStats,
  ThemeTokens,
} from "@candleviewer/chart-engine";
import type * as EngineModule from "@candleviewer/chart-engine";
import { Chart, Pane, useChartApi, useCrosshair } from "../../src/chart";

// Wrap the real createChart so a test can count creations and drive engine events.
const engine = vi.hoisted(() => ({
  created: [] as ChartApi[],
  crosshair: [] as ((p: ChartEvents["crosshair"]) => void)[],
}));

vi.mock("@candleviewer/chart-engine", async (importOriginal) => {
  // A namespace type, not an inline `typeof import(...)`: Semgrep's TS parser rejects the latter.
  const real = await importOriginal<typeof EngineModule>();
  return {
    ...real,
    createChart: (opts: ChartOptions): ChartApi => {
      const chart = real.createChart(opts);
      const subscribe = chart.subscribe.bind(chart);
      chart.subscribe = ((e, cb) => {
        if (e === "crosshair") {
          const fn = cb as (p: ChartEvents["crosshair"]) => void;
          engine.crosshair.push(fn);
          const off = subscribe(e, cb);
          return () => {
            engine.crosshair.splice(engine.crosshair.indexOf(fn), 1);
            off();
          };
        }
        return subscribe(e, cb);
      }) as ChartApi["subscribe"];
      engine.created.push(chart);
      return chart;
    },
  };
});

const theme: ThemeTokens = {
  palette: "default",
  convention: "standard",
  colors: { "color.chart.background": "#0b0e11" },
};

const fills: string[] = [];
let restore: (() => void)[] = [];

function stubDom(): void {
  const ctx = {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    rect: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    fillRect(): void {
      fills.push(String(ctx.fillStyle));
    },
  };
  const getContext = vi
    .spyOn(HTMLCanvasElement.prototype, "getContext")
    .mockImplementation(((kind: string) =>
      kind === "2d" ? ctx : null) as unknown as HTMLCanvasElement["getContext"]);
  const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
  const height = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => 640,
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get: () => 360,
  });
  restore = [
    () => getContext.mockRestore(),
    () => width && Object.defineProperty(HTMLElement.prototype, "clientWidth", width),
    () => height && Object.defineProperty(HTMLElement.prototype, "clientHeight", height),
  ];
}

beforeEach(() => {
  vi.useFakeTimers();
  engine.created.length = 0;
  engine.crosshair.length = 0;
  fills.length = 0;
  stubDom();
});

afterEach(() => {
  for (const r of restore) r();
  vi.useRealTimers();
});

function ApiProbe({ onApi }: { onApi: (c: ChartApi | null) => void }): ReactNode {
  onApi(useChartApi());
  return null;
}

function CrosshairReadout(): ReactNode {
  const c = useCrosshair();
  return <output aria-label="Crosshair">{c === null ? "none" : `${c.price} @ ${c.time}`}</output>;
}

describe("Scenario: A chart mounts and reports frame stats through the stub", () => {
  it("mounts a canvas sized to the container, filled with color.chart.background", () => {
    render(<Chart options={{ theme }} label="Price chart" />);
    const figure = screen.getByRole("figure", { name: "Price chart" });
    const canvas = figure.querySelector("canvas");
    expect(canvas).not.toBeNull();
    expect(canvas?.width).toBe(640);
    expect(canvas?.height).toBe(360);
    expect(canvas).toHaveAttribute("aria-hidden", "true");
    act(() => {
      vi.advanceTimersByTime(16); // the render runtime paints on its frame (E11-T02, 26 §3.2)
    });
    expect(fills).toEqual(["#0b0e11"]);
  });

  it("delivers frameStats carrying renderProfile to the subscriber within 1 s", () => {
    const seen: FrameStats[] = [];
    render(<Chart options={{ theme }} label="Price chart" onFrameStats={(s) => seen.push(s)} />);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(seen).toHaveLength(1);
    expect(seen[0]?.renderProfile).toBe("degraded-2d"); // jsdom has no WebGL2
  });

  it("renders the engine's DOM mirror root as a real child of the chart region", () => {
    render(<Chart options={{ theme }} label="Price chart" />);
    const figure = screen.getByRole("figure", { name: "Price chart" });
    expect(engine.created[0]?.getDomMirrorRoot().parentElement).toBe(figure);
  });
});

describe("<Chart> lifecycle and option diffing", () => {
  it("useChartApi is null outside a chart and the live chart inside it", () => {
    const outside = vi.fn();
    const inside = vi.fn();
    render(
      <>
        <ApiProbe onApi={outside} />
        <Chart options={{ theme }} label="Price chart">
          <ApiProbe onApi={inside} />
        </Chart>
      </>,
    );
    expect(outside).toHaveBeenLastCalledWith(null);
    expect(inside).toHaveBeenLastCalledWith(engine.created[0]);
  });

  it("does not recreate the chart on an unrelated prop change", () => {
    const { rerender } = render(<Chart options={{ theme }} label="Price chart" />);
    rerender(<Chart options={{ theme }} label="Main chart" onFrameStats={vi.fn()} />);
    expect(engine.created).toHaveLength(1);
    expect(screen.getByRole("figure", { name: "Main chart" })).toBeInTheDocument();
  });

  it("applies theme and density in place and only when they change", () => {
    const { rerender } = render(<Chart options={{ theme }} label="Price chart" />);
    const chart = engine.created[0];
    if (chart === undefined) throw new Error("no chart");
    const setTheme = vi.spyOn(chart, "setTheme");
    const setDensity = vi.spyOn(chart, "setDensity");
    rerender(<Chart options={{ theme }} label="Price chart" />);
    expect(setTheme).not.toHaveBeenCalled();
    const light = { ...theme, colors: { "color.chart.background": "#ffffff" } };
    rerender(<Chart options={{ theme: light, density: "dense" }} label="Price chart" />);
    expect(setTheme).toHaveBeenCalledWith(light);
    expect(setDensity).toHaveBeenCalledWith("dense");
    rerender(<Chart options={{ theme: light, density: "dense" }} label="Price chart" />);
    expect(setTheme).toHaveBeenCalledTimes(1);
    expect(setDensity).toHaveBeenCalledTimes(1);
    expect(engine.created).toHaveLength(1);
  });

  it("recreates the chart when an option without a setter changes, disposing the old one", () => {
    const { rerender } = render(<Chart options={{ theme, maxBars: 1000 }} label="Price chart" />);
    rerender(<Chart options={{ theme, maxBars: 2000 }} label="Price chart" />);
    expect(engine.created).toHaveLength(2);
    expect(() => engine.created[0]?.addPane({})).toThrow(/disposed/);
    expect(
      screen.getByRole("figure", { name: "Price chart" }).querySelectorAll("canvas"),
    ).toHaveLength(1);
  });

  it("disposes the chart on unmount and delivers nothing afterwards", () => {
    const onStats = vi.fn();
    const { unmount } = render(
      <Chart options={{ theme }} label="Price chart" onFrameStats={onStats} />,
    );
    const chart = engine.created[0];
    unmount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(onStats).not.toHaveBeenCalled();
    expect(() => chart?.addPane({})).toThrow(/disposed/);
  });
});

describe("<Pane> and useCrosshair", () => {
  function Panes({ ratio, show }: { ratio: number; show: boolean }): ReactNode {
    return (
      <Chart options={{ theme }} label="Price chart">
        {show ? (
          <Pane heightRatio={ratio}>
            <CrosshairReadout />
          </Pane>
        ) : null}
        <Pane />
      </Chart>
    );
  }

  it("adds a pane per <Pane>, resizes it in place and removes it on unmount", () => {
    const { rerender } = render(<Panes ratio={0.6} show />);
    const chart = engine.created[0];
    expect(chart?.panes).toHaveLength(2);
    const first = chart?.panes[0] as unknown as { heightRatio: number };
    expect(first.heightRatio).toBe(0.6);
    rerender(<Panes ratio={0.4} show />);
    expect(first.heightRatio).toBe(0.4);
    expect(chart?.panes).toHaveLength(2);
    rerender(<Panes ratio={0.4} show={false} />);
    expect(chart?.panes).toHaveLength(1);
  });

  it("useCrosshair shows the latest crosshair and unsubscribes on unmount", () => {
    const { rerender } = render(<Panes ratio={0.6} show />);
    const readout = screen.getByRole("status", { name: "Crosshair" });
    expect(readout).toHaveTextContent("none");
    expect(engine.crosshair).toHaveLength(1);
    act(() => {
      engine.crosshair[0]?.({ time: 1_700_000_000_000_000, price: 42, barIndex: 7 });
    });
    expect(readout).toHaveTextContent("42 @ 1700000000000000");
    rerender(<Panes ratio={0.6} show={false} />);
    expect(engine.crosshair).toHaveLength(0);
  });

  it("useCrosshair outside a chart is null", () => {
    render(<CrosshairReadout />);
    expect(screen.getByRole("status", { name: "Crosshair" })).toHaveTextContent("none");
  });

  it("a pane given no ratio takes the engine default", () => {
    function Probe(): ReactNode {
      const [n] = useState(0);
      return <span>{n}</span>;
    }
    render(
      <Chart options={{ theme }} label="Price chart">
        <Pane>
          <Probe />
        </Pane>
      </Chart>,
    );
    const pane = engine.created[0]?.panes[0] as unknown as { heightRatio: number };
    expect(pane.heightRatio).toBe(1);
  });
});
