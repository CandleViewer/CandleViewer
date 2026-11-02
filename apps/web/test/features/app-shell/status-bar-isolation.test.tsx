import { Profiler, type JSX } from "react";
import { act, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as AppShellModule from "../../../src/features/app-shell/AppShell";
import type * as StatusBarModule from "../../../src/features/app-shell/StatusBar";
import { clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { ShellLayout } from "../../../src/features/app-shell/ShellLayout";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
} from "../../../src/shell/bootstrap/store.js";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";
import type { TopicReading } from "../../../src/lib/ws/state/chipState";
import { reduce } from "../../../src/lib/ws/state/reducer";
import { OFF, authOk, connecting, quality, stream } from "../../lib/ws/support/engineEvents";
import { fakeActiveClient, runEvents } from "../../lib/ws/support/fakeActiveClient";

const renders = { shell: 0, statusBar: 0, statusSubtree: 0, outlet: 0 };

// Count the top-level shell's and the status bar's own renders (ESM exports cannot be spied).
vi.mock("../../../src/features/app-shell/AppShell", async (importOriginal) => {
  const real = await importOriginal<typeof AppShellModule>();
  return {
    ...real,
    AppShell: (props: Parameters<typeof real.AppShell>[0]) => {
      renders.shell += 1;
      return real.AppShell(props);
    },
  };
});
vi.mock("../../../src/features/app-shell/StatusBar", async (importOriginal) => {
  const real = await importOriginal<typeof StatusBarModule>();
  const onRender = (): void => {
    renders.statusSubtree += 1;
  };
  return {
    ...real,
    StatusBar: (props: Parameters<typeof real.StatusBar>[0]) => {
      renders.statusBar += 1;
      return (
        <Profiler id="status" onRender={onRender}>
          {real.StatusBar(props)}
        </Profiler>
      );
    },
  };
});

function Screen(): JSX.Element {
  renders.outlet += 1;
  return <h1>Workspace</h1>;
}

const T0 = Date.UTC(2026, 9, 27, 13, 42, 5);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
});
afterEach(() => {
  act(() => {
    resetShellState();
    clearAnnouncements();
  });
  resetMeClaims();
  vi.useRealTimers();
});

describe("E10-S01 S4: the 1 Hz status bar never re-renders the shell or the workspace", () => {
  it("re-renders only the clock and chip leaves over 60 simulated seconds", () => {
    act(() => setShellState({ connection: { kind: "live" }, latency: toLatencyIndicator(38) }));
    const router = createMemoryRouter(
      [{ element: <ShellLayout />, children: [{ path: "/", element: <Screen /> }] }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    expect(screen.getByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByText("13:42:05 UTC")).toBeInTheDocument();
    const base = { ...renders };
    expect(base.statusBar).toBeGreaterThan(0);

    for (let s = 1; s <= 60; s += 1) {
      act(() => {
        setShellState({ latency: toLatencyIndicator(38 + (s % 5)) }); // ≤ 1 Hz, as the store emits
        vi.advanceTimersByTime(1000);
      });
    }

    expect(within(footer).getByText("13:43:05 UTC")).toBeInTheDocument();
    expect(renders.outlet - base.outlet).toBe(0);
    expect(renders.shell - base.shell).toBe(0);
    expect(renders.statusBar - base.statusBar).toBe(0);
    // The leaves did re-render inside the status bar: the clock and latency chip, once per second.
    expect(renders.statusSubtree - base.statusSubtree).toBeGreaterThanOrEqual(60);
    router.dispose();
  });

  it("#5345: the chip's new sources (topics, the exchange's feed, the link quality) re-render no shell, status bar or workspace", () => {
    const up = runEvents(connecting, authOk(OFF), stream("live"));
    const ws = fakeActiveClient(up);
    const ticker = (freshAtMs: number): TopicReading => ({
      ch: "ticker.BTCUSDT",
      rs: undefined,
      source: "live",
      status: "live",
      freshAtMs,
      serverStale: false,
      awaitingReconnect: false,
    });
    ws.setTopics([ticker(T0)]);
    act(() => setShellState({ connection: { kind: "live" }, latency: toLatencyIndicator(38) }));
    const router = createMemoryRouter(
      [{ element: <ShellLayout />, children: [{ path: "/", element: <Screen /> }] }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    const header = screen.getByRole("banner");
    const base = { ...renders };

    for (let s = 1; s <= 60; s += 1) {
      act(() => {
        setShellState({ latency: toLatencyIndicator(38 + (s % 5)) });
        // 0-9 s: the ticker goes stale; 10 s: fresh; 20-29 s: the exchange's feed down; 30-39 s: saturated
        if (s === 10) ws.setTopics([ticker(Date.now())]);
        if (s === 20) applySystemUpdate({ kind: "exchange_state", public_ws: "disconnected" });
        if (s > 20 && s < 30)
          applySystemUpdate({ kind: "health", exchange: { public_ws: "disconnected" } });
        if (s === 30) {
          applySystemUpdate({ kind: "exchange_state", public_ws: "connected" });
          ws.setTopics([ticker(Date.now())]);
        }
        vi.advanceTimersByTime(1000);
      });
      if (s === 7) {
        expect(within(header).getByRole("button", { name: /^Connection: Stale 7/ })).toBeVisible();
      }
      if (s === 25) {
        expect(within(header).getByRole("button", { name: /exchange feed down/ })).toBeVisible();
      }
      if (s === 31) {
        ws.go(reduce(up, quality("saturated")));
        act(() => applySystemUpdate({ kind: "connection_quality", class: "saturated" }));
      }
      if (s === 33) {
        expect(
          within(header).getByRole("button", { name: /^Connection: Reduced rate/ }),
        ).toBeVisible();
      }
    }

    expect(renders.outlet - base.outlet).toBe(0);
    expect(renders.shell - base.shell).toBe(0);
    expect(renders.statusBar - base.statusBar).toBe(0);
    router.dispose();
    ws.detach();
  });
});
