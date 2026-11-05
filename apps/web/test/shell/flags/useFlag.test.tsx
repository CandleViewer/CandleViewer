import type { JSX } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames.js";
import {
  applySystemUpdate,
  clearFlags,
  resetShellState,
  setShellState,
} from "../../../src/shell/bootstrap/store.js";
import { getShellState } from "../../../src/shell/bootstrap/store.js";
import { readFlag, useFlag } from "../../../src/shell/flags/useFlag.js";
import { toLatencyIndicator } from "../../../src/lib/telemetry/latencyIndicator.js";

const send = (v: unknown): void => act(() => applySystemUpdate(v as SystemUpdate));
const push = (flags: unknown): void => send({ kind: "feature_flags", feature_flags: flags });

afterEach(() => act(() => resetShellState()));

const renders = { n: 0 };
function Probe(props: { name: string }): JSX.Element {
  renders.n += 1;
  const on = useFlag(props.name);
  return <output aria-label={props.name}>{on === undefined ? "unread" : String(on)}</output>;
}

describe("useFlag / readFlag", () => {
  it("reads undefined while the flags have not been read", () => {
    render(<Probe name="replay.enabled" />);
    expect(screen.getByRole("status", { name: "replay.enabled" })).toHaveTextContent("unread");
    expect(readFlag("replay.enabled")).toBeUndefined();
  });

  it("re-renders the component when its flag changes", () => {
    render(<Probe name="replay.enabled" />);
    const out = screen.getByRole("status", { name: "replay.enabled" });
    push({ "replay.enabled": true });
    expect(out).toHaveTextContent("true");
    push({ "replay.enabled": false });
    expect(out).toHaveTextContent("false");
    expect(readFlag("replay.enabled")).toBe(false);
  });

  it("does not re-render on another flag's change or an unrelated store update", () => {
    push({ "replay.enabled": true });
    render(<Probe name="replay.enabled" />);
    const before = renders.n;
    push({ "other.flag": true });
    act(() => setShellState({ latency: toLatencyIndicator(20) }));
    expect(renders.n).toBe(before);
  });

  it("reads undefined for a name no frame carried", () => {
    push({ "replay.enabled": true });
    expect(readFlag("unknown.flag")).toBeUndefined();
  });

  it("ignores a non-boolean value on the wire", () => {
    render(<Probe name="replay.enabled" />);
    push({ "replay.enabled": "yes" });
    expect(screen.getByRole("status", { name: "replay.enabled" })).toHaveTextContent("unread");
  });

  it("a health snapshot replaces the set the push built", () => {
    push({ a: true, b: true });
    send({ kind: "health", health: "healthy", feature_flags: { a: false } });
    expect(readFlag("a")).toBe(false);
    expect(readFlag("b")).toBeUndefined();
  });

  it("clearFlags and resetShellState return every flag to unread", () => {
    render(<Probe name="a" />);
    push({ a: true });
    act(() => clearFlags());
    expect(screen.getByRole("status", { name: "a" })).toHaveTextContent("unread");
    push({ a: true });
    act(() => resetShellState());
    expect(readFlag("a")).toBeUndefined();
  });

  it("keeps the same flags reference for frames that carry no flags", () => {
    push({ a: true });
    const held = getShellState().flags;
    send({ kind: "notice", message: "x" });
    send({ kind: "health", health: "healthy" });
    send({ kind: "feature_flags", feature_flags: "nope" });
    push({ a: true });
    expect(getShellState().flags).toBe(held);
  });
});
