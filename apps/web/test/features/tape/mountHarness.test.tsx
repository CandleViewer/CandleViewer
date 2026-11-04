// E22-S01 (#714) BQ-206 / BQ-215: a smoke test of the dev / Playwright harness mount, so its
// coverage is measured here and not only by the on-demand perf spec. It mounts SCR-053 with the
// seeded feeder, finds the grid and reads the probe the perf spec reads.
import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  TAPE_HARNESS_SYMBOL,
  mountTapeHarness,
} from "../../../src/features/tape/harness/mountHarness";

let unmount: (() => void) | undefined;

afterEach(() => {
  act(() => unmount?.());
  unmount = undefined;
  document.body.innerHTML = "";
});

describe("tape harness mount", () => {
  it("renders the panel for its symbol and exposes the read-only probe", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    act(() => {
      unmount = mountTapeHarness(container);
    });
    expect(await screen.findByRole("grid", { name: `Tape ${TAPE_HARNESS_SYMBOL}` })).toBeTruthy();
    const probe = window.__cvTapeHarness;
    if (probe === undefined) throw new Error("no probe");
    expect(probe.rows()).toBeGreaterThanOrEqual(1);
    expect(probe.rows()).toBeLessThanOrEqual(60);
    expect(probe.injected()).toBeGreaterThanOrEqual(0);
    expect(probe.appended()).toBeLessThanOrEqual(probe.injected());
    expect(probe.ringLength()).toBe(probe.appended());
    expect(probe.workP95Ms()).toBeGreaterThanOrEqual(0);
    expect(probe.maxIngestMs()).toBeGreaterThanOrEqual(0);
    expect(probe.rung()).toBe(0); // the BQ-218 ladder starts at full rate
  });

  it("removes the probe when unmounted", () => {
    const container = document.createElement("div");
    document.body.append(container);
    act(() => {
      unmount = mountTapeHarness(container);
    });
    expect(window.__cvTapeHarness).toBeDefined();
    act(() => unmount?.());
    unmount = undefined;
    expect(window.__cvTapeHarness).toBeUndefined();
  });
});
