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
import { CHART_ERROR_COPY as COPY, noWebgl2Body } from "../../../src/features/chart-errors/copy";
import { ENGINE_CODES as C, REDUCED_ORDER } from "../../../src/features/chart-errors/state";
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
  sessionStorage.clear(); // BQ-96's once-per-session flag lives here
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
    // The real engine names all five (BQ-89), so the body names all five fragments (BQ-91).
    expect(alert).toHaveTextContent(noWebgl2Body(REDUCED_ORDER));
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

describe("E11-T05 degraded-2d: the reduced list, once per session, the badge, the handoff", () => {
  const degrade = (reducedCapabilities: unknown[], reason = "no-webgl2") => ({
    details: { reducedCapabilities, reason } as NonNullable<ChartEvents["error"]["details"]>,
  });
  const badge = (): HTMLElement | null => screen.queryByText(COPY.badge);
  const HANDOVER = `${COPY.noWebgl2.heading} ${noWebgl2Body(REDUCED_ORDER)}`;
  /** Every text the surface's polite region receives from now on (one entry per announcement). */
  const listen = (): (() => string[]) => {
    const got: string[] = [];
    const node = document.querySelector("[data-chart-error] > [role='status']");
    const obs = new MutationObserver((ms) => {
      for (const m of ms) for (const n of m.addedNodes) got.push(n.textContent ?? "");
    });
    if (node !== null) obs.observe(node, { childList: true });
    restore.push(() => obs.disconnect());
    return () => {
      for (const m of obs.takeRecords())
        for (const n of m.addedNodes) got.push(n.textContent ?? "");
      return got;
    };
  };
  const recreate = (rerender: ReturnType<typeof mount>["rerender"], locale: string): void =>
    rerender(<ChartErrorSurface options={{ theme, locale }} label="Price chart" />);

  it("the card names the event's list in vocabulary order and ignores unknown values", () => {
    mount();
    emit(C.noWebgl2, degrade(["heatmap", "sparkles", "footprint-text"], "warp"));
    expect(screen.getByRole("alert")).toHaveTextContent(
      noWebgl2Body(["footprint-text", "heatmap"]),
    );
    expect(screen.queryByText(/sparkles|warp/)).toBeNull();
  });

  it("the badge is absent under the card, shown after Continue, gone when WebGL2 returns", async () => {
    mount();
    emit(C.noWebgl2, degrade([...REDUCED_ORDER]));
    frame("degraded-2d");
    expect(badge()).toBeNull();
    // Keyboard: Continue is the card's first stop, Retry WebGL2 follows; both take focus.
    const [go, retry] = [COPY.noWebgl2.continue, COPY.noWebgl2.retry].map((name) =>
      screen.getByRole("button", { name }),
    );
    expect(go?.compareDocumentPosition(retry as Node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    for (const b of [go, retry]) {
      b?.focus();
      expect(document.activeElement).toBe(b);
    }
    fireEvent.click(go as HTMLElement);
    const shown = badge();
    expect(shown).not.toBeNull();
    expect(shown?.closest("[aria-live],[role='alert'],[role='status']")).toBeNull();
    expect(stack()?.style.visibility).toBe(""); // the 2D chart keeps drawing, never suspended
    expect(said()).toBe("");
    await expectNoSeriousAxe();
    frame("full");
    expect(badge()).toBeNull();
  });

  it("once per session: a recreate and a new surface go straight to the badge", () => {
    const { rerender, unmount } = mount();
    emit(C.noWebgl2);
    frame("degraded-2d");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(sessionStorage.getItem("cv.chart.degradedCardShown.degraded-2d")).toBe("1");
    recreate(rerender, "de-DE");
    emit(C.noWebgl2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(badge()).not.toBeNull();
    unmount();
    mount();
    emit(C.noWebgl2);
    frame("degraded-2d");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(badge()).not.toBeNull();
  });

  it("storage that throws: the card still shows once and a recreate still never re-shows it", () => {
    const fail = (): never => {
      throw new DOMException("denied", "SecurityError");
    };
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(fail);
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(fail);
    restore.push(
      () => get.mockRestore(),
      () => set.mockRestore(),
    );
    const { rerender } = mount();
    emit(C.noWebgl2);
    frame("degraded-2d");
    expect(screen.getByRole("alert")).toHaveTextContent(COPY.noWebgl2.heading);
    fireEvent.click(screen.getByRole("button", { name: COPY.noWebgl2.continue }));
    expect(badge()).not.toBeNull();
    recreate(rerender, "fr-FR");
    emit(C.noWebgl2);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(set).toHaveBeenCalled();
  });

  it.each([C.shaderFailed, C.restoreFailed])(
    "%s then degraded-2d frames: the stopped card becomes the degraded card, alerted once",
    async (code) => {
      const shown: unknown[] = [];
      const on = (e: Event): void => {
        shown.push((e as CustomEvent).detail);
      };
      window.addEventListener(THEME_ANALYTICS_EVENT, on);
      restore.push(() => window.removeEventListener(THEME_ANALYTICS_EVENT, on));
      mount();
      emit(code, { recoverable: false });
      expect(screen.getByRole("alert")).toHaveTextContent(COPY.stopped.heading);
      const spoken = listen();
      const ref = screen.getByText(/· ref /).textContent;
      screen.getAllByRole("button")[0]?.focus(); // the user is on the stopped card
      frame("degraded-2d");
      frame("degraded-2d");
      // Focus stays inside the card across the handoff, never dropped to <body> (05 §3.4 item 3).
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement?.closest("[data-cmp='SCR-048']")).not.toBeNull();
      expect(screen.queryByText(COPY.stopped.heading)).toBeNull();
      expect(screen.getByRole("heading", { name: COPY.noWebgl2.heading })).toBeInTheDocument();
      expect(screen.getByText(noWebgl2Body(REDUCED_ORDER))).toBeInTheDocument();
      expect(screen.queryByRole("alert")).toBeNull(); // the fatal alert already spoke
      expect(said()).toBe(HANDOVER); // §19's heading and body, said once, politely
      expect(spoken()).toEqual([HANDOVER]);
      expect(screen.getByText(/· ref /).textContent).toBe(ref);
      expect(shown).toHaveLength(1);
      await expectNoSeriousAxe();
      fireEvent.click(screen.getByRole("button", { name: COPY.noWebgl2.continue }));
      expect(badge()).not.toBeNull();
    },
  );

  it.each([C.shaderFailed, C.restoreFailed])(
    "%s then degraded-2d frames with the card already seen: basic, §19 said once, no alert",
    (code) => {
      sessionStorage.setItem("cv.chart.degradedCardShown.degraded-2d", "1");
      mount();
      emit(code, { recoverable: false });
      const spoken = listen();
      frame("degraded-2d");
      frame("degraded-2d");
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText(COPY.noWebgl2.heading)).toBeNull();
      expect(badge()).not.toBeNull();
      expect(said()).toBe(HANDOVER);
      expect(spoken()).toEqual([HANDOVER]);
    },
  );

  it("two surfaces mounted together: one card, the second goes straight to the badge", () => {
    render(
      <>
        <ChartErrorSurface options={{ theme }} label="First chart" />
        <ChartErrorSurface options={{ theme }} label="Second chart" />
      </>,
    );
    const [a, b] = engine.charts.map((c) => c.on);
    const fire = (on: Listeners | undefined): void =>
      act(() => {
        for (const cb of on?.error ?? []) cb({ code: C.noWebgl2, message: "", recoverable: true });
        for (const cb of on?.stats ?? []) cb({ renderProfile: "degraded-2d" } as FrameStats);
      });
    fire(a);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    fire(b);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    const second = screen.getByRole("region", { name: "Second chart" });
    expect(within(second).queryByRole("alert")).toBeNull();
    expect(within(second).getByText(COPY.badge)).toBeInTheDocument();
  });

  it("frames read sessionStorage only at a fatal card's 2D handoff, never per frame", () => {
    mount();
    const get = vi.spyOn(Storage.prototype, "getItem");
    for (let i = 0; i < 5; i += 1) frame("degraded-2d");
    expect(get).not.toHaveBeenCalled();
    emit(C.shaderFailed, { recoverable: false });
    get.mockClear();
    frame("degraded-2d");
    expect(get).toHaveBeenCalledTimes(1);
    get.mockClear();
    for (let i = 0; i < 5; i += 1) frame("degraded-2d");
    expect(get).not.toHaveBeenCalled();
    get.mockRestore();
  });

  it("a final ENGINE_WORKER_LOST stays the stopped card whatever the frames say", () => {
    mount();
    emit(C.workerLost, { recoverable: false });
    frame("degraded-2d");
    expect(screen.getByRole("alert")).toHaveTextContent(COPY.stopped.heading);
    expect(badge()).toBeNull();
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
