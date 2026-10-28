import type { JSX } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  resetShellState,
  setShellState,
  type ShellState,
} from "../../src/shell/bootstrap/store.js";
import type * as ShellStoreModule from "../../src/shell/bootstrap/store.js";
import { useShellSelector } from "../../src/shell/useShellSelector.js";
import { toLatencyIndicator } from "../../src/lib/telemetry/latencyIndicator.js";

// Counts the hook's live store subscriptions, for the teardown test.
const active = vi.hoisted(() => ({ n: 0 }));
vi.mock("../../src/shell/bootstrap/store.js", async (importOriginal) => {
  const real = await importOriginal<typeof ShellStoreModule>();
  return {
    ...real,
    subscribeShellState: (listener: () => void) => {
      active.n += 1;
      const off = real.subscribeShellState(listener);
      return () => {
        active.n -= 1;
        off();
      };
    },
  };
});

afterEach(() => act(() => resetShellState()));

const renders = { n: 0 };
const tick = (ms: number): void => act(() => setShellState({ latency: toLatencyIndicator(ms) }));
function Probe<T>(props: {
  select: (s: ShellState) => T;
  eq?: (a: T, b: T) => boolean;
}): JSX.Element {
  renders.n += 1;
  return <output>{JSON.stringify(useShellSelector(props.select, props.eq))}</output>;
}
const byConnection = (s: ShellState) => s.connection;
const byLatencyState = (s: ShellState) => ({ state: s.latency.state });
const byEnvironment = (s: ShellState) => s.environment;

describe("useShellSelector", () => {
  it("does not re-render a connection subscriber on a 1 Hz latency tick", () => {
    render(<Probe select={byConnection} />);
    const before = renders.n;
    for (let ms = 10; ms < 70; ms += 1) tick(ms);
    expect(renders.n).toBe(before);
    act(() => setShellState({ connection: { kind: "live" } }));
    expect(renders.n).toBe(before + 1);
    expect(screen.getByRole("status")).toHaveTextContent('{"kind":"live"}');
  });

  it("keeps the previous value when isEqual says the new selection is equal", () => {
    render(<Probe select={byLatencyState} eq={(a, b) => a.state === b.state} />);
    tick(20);
    const settled = renders.n;
    tick(30);
    expect(renders.n).toBe(settled);
    tick(300);
    expect(screen.getByRole("status")).toHaveTextContent('{"state":"breach"}');
  });

  it("reads the new selector when its identity changes between renders, with no store change", () => {
    const { rerender } = render(<Probe<unknown> select={byConnection} />);
    expect(screen.getByRole("status")).toHaveTextContent('{"kind":"connecting"}');
    rerender(<Probe<unknown> select={byEnvironment} />);
    expect(screen.getByRole("status")).toHaveTextContent('"unknown"');
  });

  it("unsubscribes on unmount: a later store change renders nothing and reaches no listener", () => {
    const before = active.n;
    const { unmount } = render(<Probe select={byConnection} />);
    expect(active.n).toBe(before + 1);
    unmount();
    expect(active.n).toBe(before);
    const settled = renders.n;
    act(() => setShellState({ connection: { kind: "live" } }));
    expect(renders.n).toBe(settled);
  });
});
