// E11-S02 PR4: SCR-048's strip and cards over the real engine binding (E11-D04 §12, E11-D06 D19).
// The engine mock records each chart's error / frameStats listeners so a test drives them, and
// logs create and dispose so a retry's remount is shown not to leak.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  Chart as ChartApi,
  ChartEvents,
  ChartOptions,
  FrameStats,
  ThemeTokens,
} from "@candleviewer/chart-engine";
import type * as EngineModule from "@candleviewer/chart-engine";
import { ChartErrorSurface } from "../../../src/features/chart-errors/ChartErrorSurface";
import { CHART_ERROR_COPY as COPY } from "../../../src/features/chart-errors/copy";
import { ENGINE_CODES as C } from "../../../src/features/chart-errors/state";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";

type Listeners = {
  error: Set<(e: ChartEvents["error"]) => void>;
  stats: Set<(s: FrameStats) => void>;
};
const engine = vi.hoisted(() => ({
  charts: [] as { api: ChartApi; on: Listeners }[],
  log: [] as string[],
  realErrors: false,
}));

vi.mock("@candleviewer/chart-engine", async (importOriginal) => {
  const real = await importOriginal<typeof EngineModule>();
  return {
    ...real,
    createChart: (opts: ChartOptions): ChartApi => {
      const n = engine.charts.length;
      engine.log.push(`create#${n}`);
      const api = real.createChart(opts);
      const on: Listeners = { error: new Set(), stats: new Set() };
      const subscribe = api.subscribe.bind(api);
      api.subscribe = ((e, cb) => {
        if (e !== "error" && e !== "frameStats") return subscribe(e, cb);
        const set = (e === "error" ? on.error : on.stats) as Set<typeof cb>;
        set.add(cb);
        const off = e === "error" && engine.realErrors ? subscribe(e, cb) : () => undefined;
        return () => {
          set.delete(cb);
          off();
        };
      }) as ChartApi["subscribe"];
      const dispose = api.dispose.bind(api);
      api.dispose = () => {
        engine.log.push(`dispose#${n}`);
        dispose();
      };
      engine.charts.push({ api, on });
      return api;
    },
  };
});

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const theme: ThemeTokens = { palette: "default", convention: "standard", colors: {} };
let restore: (() => void)[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  engine.charts.length = 0;
  engine.log.length = 0;
  engine.realErrors = false;
  const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((
    kind: string,
  ) => {
    if (kind === "webgl2") engine.log.push("probe");
    return kind === "2d" ? { clearRect: vi.fn(), fillRect: vi.fn() } : null;
  }) as unknown as HTMLCanvasElement["getContext"]);
  restore = [() => getContext.mockRestore()];
});

afterEach(() => {
  for (const r of restore) r();
  vi.useRealTimers();
});

const last = (): Listeners => {
  const c = engine.charts.at(-1);
  if (c === undefined) throw new Error("no chart");
  return c.on;
};
const emit = (code: string, extra: Partial<ChartEvents["error"]> = {}): void =>
  act(() => {
    for (const cb of last().error)
      cb({ code, message: "driver says http://host", recoverable: true, ...extra });
  });
const frame = (renderProfile: FrameStats["renderProfile"]): void =>
  act(() => {
    for (const cb of last().stats) cb({ renderProfile } as FrameStats);
  });
const lost = (attempt: number, nextTryMs: number): void =>
  emit(C.lost, { details: { attempt, maxAttempts: 3, nextTryMs } });
const mount = () =>
  render(
    <ChartErrorSurface options={{ theme }} label="Price chart">
      <button type="button">In the panes</button>
    </ChartErrorSurface>,
  );
/** The surface's own polite region (CMP-033 has its own status too). */
const said = (): string =>
  document.querySelector("[data-chart-error] > [role='status']")?.textContent ?? "";
const stack = (): HTMLElement | null | undefined =>
  screen.getByRole("figure", { hidden: true }).parentElement;

async function expectNoSeriousAxe(): Promise<void> {
  vi.useRealTimers();
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

describe("Scenario: Context loss recovers within the R1 exit budget (SCR-048 strip)", () => {
  it("details drive the strip, the countdown ticks at 1 Hz, announced once, frame held", async () => {
    mount();
    lost(1, 1000);
    expect(screen.getByText(COPY.strip.title)).toBeInTheDocument();
    expect(screen.getByText("attempt 1 of 3 · next try in 1 s")).toBeInTheDocument();
    expect(screen.queryByText(/driver says/)).toBeNull();
    expect(said()).toBe(COPY.strip.announce);
    lost(2, 2000);
    expect(screen.getByText("attempt 2 of 3 · next try in 2 s")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("attempt 2 of 3 · next try in 1 s")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByText("attempt 2 of 3 · next try in 1 s")).toBeInTheDocument(); // 1 s floor
    expect(screen.getAllByRole("status")).toHaveLength(1); // the strip itself is aria-live off
    expect(said()).toBe(COPY.strip.announce);
    expect(stack()?.style.visibility).toBe("");
    expect(screen.getByRole("figure").querySelector("canvas")).not.toBeNull();
    await expectNoSeriousAxe();
  });

  it("on restore the strip goes and 'Chart restored' is said once", () => {
    mount();
    lost(1, 1000);
    emit(C.restored);
    expect(screen.queryByText(COPY.strip.title)).toBeNull();
    expect(said()).toBe(COPY.restored);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(said()).toBe(COPY.restored);
    expect(screen.queryByText(/next try/)).toBeNull();
  });

  it("the countdown never shows more than the event's wait when the clock steps back", () => {
    mount();
    lost(1, 1000);
    act(() => {
      vi.setSystemTime(Date.now() - 10_000);
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByText("attempt 1 of 3 · next try in 1 s")).toBeInTheDocument();
  });

  it("the 1 Hz interval is cleared on unmount", () => {
    const set = vi.spyOn(globalThis, "setInterval");
    const clear = vi.spyOn(globalThis, "clearInterval");
    const { unmount } = mount();
    lost(1, 1000);
    const id = set.mock.results.at(-1)?.value as unknown;
    unmount();
    expect(clear).toHaveBeenCalledWith(id);
  });
});

describe("Scenario: Repeated loss gives up gracefully rather than looping (SCR-048 card)", () => {
  it("the card alerts once, keeps focus, hides the panes and shows the code and reference", async () => {
    mount();
    for (const [n, ms] of [
      [1, 1000],
      [2, 2000],
      [3, 4000],
    ] as const)
      lost(n, ms);
    emit(C.restoreFailed, { recoverable: false });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(COPY.stopped.heading);
    expect(alert).toHaveTextContent(COPY.stopped.body);
    expect(document.activeElement).toBe(document.body);
    expect(screen.getByRole("region", { name: "Price chart" })).toBeInTheDocument();
    expect(stack()?.style.visibility).toBe("hidden");
    expect(stack()).toHaveAttribute("inert");
    expect(
      screen.getByText(/^ENGINE_CONTEXT_RESTORE_FAILED · ref urn:cv:ui:[0-9a-f-]{36}$/),
    ).toBeInTheDocument();
    expect(screen.getByText(COPY.stopped.retryLine)).toBeInTheDocument();
    expect(
      screen.queryByText(/driver says|Open data table|Open diagnostics|Renderer settings/),
    ).toBeNull();
    expect(screen.queryByText(COPY.strip.title)).toBeNull();
    const [retry, copyRef] = [COPY.stopped.retry, COPY.copyReference].map((name) =>
      screen.getByRole("button", { name }),
    );
    // §12.4: Retry precedes Copy reference in the Tab order.
    expect(retry?.compareDocumentPosition(copyRef as Node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    for (const b of [retry, copyRef]) {
      b?.focus();
      expect(document.activeElement).toBe(b);
    }
    await expectNoSeriousAxe();
  });

  it("Retry remounts: the old chart is disposed before the new one is created; failure keeps it", () => {
    mount();
    emit(C.restoreFailed);
    const ref = screen.getByText(/· ref /).textContent;
    const oldCanvas = screen.getByRole("figure", { hidden: true }).querySelector("canvas");
    engine.log.length = 0;
    fireEvent.click(screen.getByRole("button", { name: COPY.stopped.retry }));
    // dispose#0 before create#1: nothing of the old chart is live when the new one is created.
    expect(engine.log.slice(0, 2)).toEqual(["dispose#0", "create#1"]);
    expect(engine.charts[0]?.on.error.size).toBe(0);
    expect(engine.charts[0]?.on.stats.size).toBe(0);
    expect(oldCanvas?.isConnected).toBe(false);
    emit(C.noWebgl2);
    expect(screen.getAllByText(COPY.stopped.retryFailed)).toHaveLength(2); // the line and the status
    expect(said()).toBe(COPY.stopped.retryFailed);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText(/· ref /).textContent).toBe(ref);
  });

  it("a Retry that draws with WebGL2 closes the card: 'Chart restored', focus to the region", () => {
    mount();
    emit(C.restoreFailed);
    const retry = screen.getByRole("button", { name: COPY.stopped.retry });
    retry.focus();
    fireEvent.click(retry);
    frame("full");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(said()).toBe(COPY.restored);
    expect(stack()).not.toHaveAttribute("inert");
    expect(document.activeElement).toHaveAttribute("data-chart-error", "restored");
  });

  it("a shader compile failure shows the fatal card without the automatic-retry line", () => {
    mount();
    emit(C.shaderFailed);
    expect(screen.getByRole("alert")).toHaveTextContent(COPY.stopped.heading);
    expect(screen.getByRole("alert")).toHaveTextContent(COPY.fatalBody);
    expect(screen.queryByText(/three attempts/)).toBeNull();
    expect(screen.getByText(/^ENGINE_SHADER_COMPILE_FAILED · ref /)).toBeInTheDocument();
    expect(screen.queryByText(COPY.stopped.retryLine)).toBeNull();
  });
});

describe("SCR-048 worker lost (README C-8)", () => {
  it("a final ENGINE_WORKER_LOST opens the stopped card; Retry starts a fresh chart", () => {
    mount();
    emit(C.workerLost); // still restarting: no card
    expect(screen.queryByRole("alert")).toBeNull();
    emit(C.workerLost, { recoverable: false });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(COPY.stopped.heading);
    expect(alert).toHaveTextContent(COPY.fatalBody);
    expect(screen.getByText(/^ENGINE_WORKER_LOST · ref urn:cv:ui:/)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: COPY.stopped.retry });
    expect(
      retry.compareDocumentPosition(screen.getByRole("button", { name: COPY.copyReference })),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    engine.log.length = 0;
    fireEvent.click(retry);
    expect(engine.log.slice(0, 2)).toEqual(["dispose#0", "create#1"]);
    frame("full");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("SCR-048 focus, recreate and analytics", () => {
  it("focus in the panes moves to the card's first stop and returns to it on close", () => {
    mount();
    const inPanes = screen.getByRole("button", { name: "In the panes" });
    inPanes.focus();
    emit(C.noWebgl2);
    const go = screen.getByRole("button", { name: COPY.noWebgl2.continue });
    expect(document.activeElement).toBe(go);
    fireEvent.click(go);
    expect(document.activeElement).toBe(inPanes);
  });

  it("a RECREATE_KEYS change clears the card so it never sits over a healthy chart", () => {
    const { rerender } = mount();
    emit(C.restoreFailed);
    rerender(<ChartErrorSurface options={{ theme, locale: "de-DE" }} label="Price chart" />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(stack()).not.toHaveAttribute("inert");
  });

  it("chart.error_shown is reported once per card on the app's analytics seam", () => {
    const seen: unknown[] = [];
    const on = (e: Event): void => {
      seen.push((e as CustomEvent).detail);
    };
    window.addEventListener(THEME_ANALYTICS_EVENT, on);
    restore.push(() => window.removeEventListener(THEME_ANALYTICS_EVENT, on));
    mount();
    frame("full");
    emit(C.shaderFailed, { recoverable: false });
    fireEvent.click(screen.getByRole("button", { name: COPY.stopped.retry }));
    emit(C.shaderFailed, { recoverable: false });
    expect(seen).toEqual([
      {
        name: "chart.error_shown",
        code: C.shaderFailed,
        correlationId: expect.stringMatching(/^urn:cv:ui:/) as unknown,
        kind: "engine",
        recoverable: false,
        attempt: 0,
        nextRetryMs: null,
        renderProfile: "full",
      },
    ]);
  });
});

describe("SCR-048 no-WebGL2 card", () => {
  it("the real engine's ENGINE_NO_WEBGL2 opens it; Continue dismisses it to the region", async () => {
    engine.realErrors = true;
    mount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(COPY.noWebgl2.heading);
    expect(alert).toHaveTextContent(COPY.noWebgl2.body);
    const card = within(alert.closest("[data-cmp='SCR-048']") as HTMLElement);
    const go = card.getByRole("button", { name: COPY.noWebgl2.continue });
    expect(card.getByRole("button", { name: COPY.noWebgl2.retry })).toBeInTheDocument();
    await expectNoSeriousAxe();
    go.focus();
    fireEvent.click(go);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.activeElement).toHaveAttribute("data-chart-error", "basic");
  });

  it("Retry WebGL2 that finds none again says 'Still unavailable' once", () => {
    mount();
    emit(C.noWebgl2);
    fireEvent.click(screen.getByRole("button", { name: COPY.noWebgl2.retry }));
    expect(engine.charts).toHaveLength(2);
    emit(C.noWebgl2);
    expect(screen.getAllByText(COPY.noWebgl2.retryFailed)).toHaveLength(2); // the line and the status
    expect(said()).toBe(COPY.noWebgl2.retryFailed);
  });
});

describe("<Chart onError> subscription", () => {
  it("forwards every error and unsubscribes on unmount", () => {
    const seen: string[] = [];
    const { unmount } = render(
      <ChartErrorSurface
        options={{ theme }}
        label="Price chart"
        onError={(e) => seen.push(e.code)}
      />,
    );
    emit("ENGINE_LOD_STEPDOWN");
    expect(seen).toEqual(["ENGINE_LOD_STEPDOWN"]);
    unmount();
    expect(engine.charts[0]?.on.error.size).toBe(0);
    expect(engine.charts[0]?.on.stats.size).toBe(0);
  });
});
