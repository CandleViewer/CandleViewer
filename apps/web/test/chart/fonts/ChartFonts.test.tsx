// E11-S11 PR C (G-87): `<Chart>` under a font source is created once the fonts settle, with their
// bytes, or with none after a typed failure (fail closed, BQ-259); with no source it mounts at once.
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Chart as ChartApi, ChartOptions } from "@candleviewer/chart-engine";
import {
  Chart,
  ChartFontError,
  ChartFontsContext,
  createChartFontStore,
  type ChartFont,
} from "../../../src/chart";

const created = vi.hoisted(() => [] as ChartOptions[]);
vi.mock("@candleviewer/chart-engine", () => ({
  createChart: (opts: ChartOptions): ChartApi => {
    created.push(opts);
    // A stub of the two members `<Chart>` calls; the rest of the engine API is never reached.
    return { subscribe: () => () => undefined, dispose: () => undefined } as unknown as ChartApi;
  },
}));

const theme = { palette: "default", convention: "standard", colors: {} } as const;
const FONT: ChartFont = { family: "JetBrains Mono", weight: 400, bytes: new ArrayBuffer(8) };

function deferred(): {
  promise: Promise<readonly ChartFont[]>;
  resolve: (f: readonly ChartFont[]) => void;
  reject: (e: unknown) => void;
} {
  let resolve!: (f: readonly ChartFont[]) => void; // assigned synchronously by the executor
  let reject!: (e: unknown) => void; // assigned synchronously by the executor
  const promise = new Promise<readonly ChartFont[]>((res, rej) => {
    [resolve, reject] = [res, rej];
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  created.length = 0;
});

describe("<Chart> design-font binding", () => {
  it("test_chart_withFontSource_waitsThenPassesTheVerifiedBytes", async () => {
    const d = deferred();
    const store = createChartFontStore(() => d.promise);
    render(
      <ChartFontsContext.Provider value={store}>
        <Chart options={{ theme }} label="Price chart" />
      </ChartFontsContext.Provider>,
    );
    expect(created).toHaveLength(0); // no chart, and no `no-font` error, while the fonts load
    expect(screen.getByRole("figure", { name: "Price chart" })).toBeInTheDocument();
    await act(async () => d.resolve([FONT]));
    expect(created).toHaveLength(1);
    expect(created[0]?.fonts).toEqual([FONT]);
  });

  it("test_chart_fontFailure_createsTheChartWithNoFontsAndReportsTheReason", async () => {
    const d = deferred();
    const report = vi.fn();
    const store = createChartFontStore(() => d.promise, report);
    render(
      <ChartFontsContext.Provider value={store}>
        <Chart options={{ theme }} label="Price chart" />
      </ChartFontsContext.Provider>,
    );
    await act(async () => d.reject(new ChartFontError("integrity", "x.woff2", "mismatch")));
    expect(created).toHaveLength(1);
    expect(created[0]).not.toHaveProperty("fonts");
    expect(report).toHaveBeenCalledWith(
      expect.objectContaining({ reason: "integrity", file: "x.woff2" }),
    );
  });

  it("test_chart_explicitFonts_winOverTheSource", async () => {
    const store = createChartFontStore(async () => [FONT]);
    const own: ChartFont = { ...FONT, family: "Inter", weight: 600 };
    render(
      <ChartFontsContext.Provider value={store}>
        <Chart options={{ theme, fonts: [own] }} label="Price chart" />
      </ChartFontsContext.Provider>,
    );
    await act(async () => undefined);
    expect(created.map((o) => o.fonts)).toEqual([[own]]);
  });

  it("test_chart_noFontSource_mountsAtOnceWithoutFonts", () => {
    render(<Chart options={{ theme }} label="Price chart" />);
    expect(created).toHaveLength(1);
    expect(created[0]).not.toHaveProperty("fonts");
  });
});
