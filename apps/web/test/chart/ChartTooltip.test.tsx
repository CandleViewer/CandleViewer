import { createRequire } from "node:module";
import { act, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChartEvents } from "@candleviewer/chart-engine";
import { Chart, ChartTooltip, useReadout } from "../../src/chart";

type Readout = ChartEvents["readout"];

// `<Chart>` mounts the fake below; `emit` drives its `readout` listeners.
const engine = vi.hoisted(() => ({
  listeners: new Set<(r: unknown) => void>(),
  disposed: 0,
}));
vi.mock("@candleviewer/chart-engine", () => ({
  createChart: (): unknown => ({
    subscribe: (e: string, cb: (r: unknown) => void) => {
      if (e !== "readout") return () => undefined;
      engine.listeners.add(cb);
      return () => engine.listeners.delete(cb);
    },
    dispose: () => {
      engine.disposed += 1;
    },
    setTheme: () => undefined,
    setDensity: () => undefined,
  }),
}));

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const field = (key: string, label: string, value: string, unit = "") => ({
  key,
  label,
  value,
  unit,
  colorToken: "",
});
const readout = (over: Partial<Readout> = {}): Readout => ({
  visible: true,
  x: 100,
  y: 80,
  bar: 7,
  time: 1,
  priceText: "64,120.0",
  timeText: "14 Oct 13:42",
  snap: null,
  fields: [
    field("open", "O", "64,010.0"),
    field("high", "High", "64,020.5"),
    field("low", "L", "63,990.0"),
    field("close", "C", "64,011.0"),
    field("volume", "Vol", "1,204"),
    field("delta", "Δ", "200"),
  ],
  ...over,
});
const emit = (r: Readout): void => engine.listeners.forEach((l) => l(r));
const theme = { palette: "default", convention: "standard", colors: {} } as const;
const plot = { width: 800, height: 500 };

beforeEach(() => {
  engine.listeners.clear();
  engine.disposed = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) =>
    window.setTimeout(() => cb(0), 16),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ChartTooltip", () => {
  it("renders O/H/L/C/Vol/Δ with the time and interval, the snapped label and direction glyph", () => {
    const { container } = render(<ChartTooltip readout={readout()} interval="1m" plot={plot} />);
    const tip = container.querySelector<HTMLElement>(".cv-chart-tooltip");
    expect(tip).toHaveTextContent("14 Oct 13:42 · 1m");
    expect(tip).toHaveTextContent("High64,020.5");
    expect(tip).toHaveTextContent("C64,011.0 ▲");
    expect(tip).toHaveTextContent("Δ+200");
    expect(tip?.style.transform).toBe("translate3d(116px, 96px, 0)");
    expect(tip).toHaveAttribute("data-visible");
  });

  it("shows ▼ when the close is below the open and never colours a value", () => {
    const r = readout({
      fields: [field("open", "O", "10"), field("close", "C", "9"), field("delta", "Δ", "−1")],
    });
    const { container } = render(<ChartTooltip readout={r} interval="5m" plot={plot} />);
    expect(container).toHaveTextContent("C9 ▼");
    expect(container).toHaveTextContent("Δ−1");
    expect(container.querySelector("[style*='color']")).toBeNull();
  });

  it("fades out on visible:false but keeps its text, and renders nothing before the first readout", () => {
    const view = render(<ChartTooltip readout={null} interval="1m" plot={plot} />);
    expect(view.container).toBeEmptyDOMElement();
    view.rerender(<ChartTooltip readout={readout()} interval="1m" plot={plot} />);
    view.rerender(
      <ChartTooltip readout={readout({ visible: false, fields: [] })} interval="1m" plot={plot} />,
    );
    const tip = view.container.querySelector(".cv-chart-tooltip");
    expect(tip).not.toHaveAttribute("data-visible");
    expect(tip).toHaveTextContent("14 Oct 13:42 · 1m");
  });

  it("is aria-hidden, so the tree has nothing to announce, and passes axe", async () => {
    vi.useRealTimers();
    const { container } = render(
      <main>
        <ChartTooltip readout={readout()} interval="1m" plot={plot} />
      </main>,
    );
    expect(screen.queryAllByRole("term")).toEqual([]);
    expect(screen.queryAllByRole("definition")).toEqual([]);
    expect(container.querySelector(".cv-chart-tooltip")).toHaveAttribute("aria-hidden", "true");
    const { violations } = await axe.run(container);
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("keeps long text inside the box (title wraps, no overflow style)", () => {
    const long = readout({ timeText: "14 October 2026 13:42:00 Europe/Kyiv".repeat(3) });
    const { container } = render(<ChartTooltip readout={long} interval="1m" plot={plot} />);
    expect(
      container.querySelector(".cv-chart-tooltip__title")?.textContent?.length,
    ).toBeGreaterThan(80);
  });
});

describe("useReadout", () => {
  const wrapper = ({ children }: { children: ReactNode }): ReactNode => (
    <Chart options={{ theme }} label="Chart">
      {children}
    </Chart>
  );

  it("coalesces a burst to one render per frame, keeping the last value", () => {
    let renders = 0;
    const { result } = renderHook(
      () => {
        renders += 1;
        return useReadout();
      },
      { wrapper },
    );
    expect(result.current).toBeNull();
    const before = renders;
    act(() => {
      for (let i = 0; i < 50; i += 1) emit(readout({ bar: i }));
    });
    expect(renders).toBe(before);
    act(() => void vi.advanceTimersByTime(16));
    expect(result.current?.bar).toBe(49);
    expect(renders).toBe(before + 1);
  });

  it("tears down: unsubscribes, cancels the pending frame and sets nothing after unmount", () => {
    const { result, unmount } = renderHook(() => useReadout(), { wrapper });
    act(() => emit(readout()));
    expect(engine.listeners.size).toBe(1);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    unmount();
    expect(engine.listeners.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    expect(result.current).toBeNull();
  });
});
