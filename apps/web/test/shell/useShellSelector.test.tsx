import type { JSX } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  resetShellState,
  setShellState,
  type ShellState,
} from "../../src/shell/bootstrap/store.js";
import { useShellSelector } from "../../src/shell/useShellSelector.js";
import { toLatencyIndicator } from "../../src/lib/telemetry/latencyIndicator.js";

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
});
