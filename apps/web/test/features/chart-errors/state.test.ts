// E11-S02 PR4: SCR-048's state model is driven by `code` and `details` only (never `message`).
import { describe, expect, it } from "vitest";
import type { ChartEvents } from "@candleviewer/chart-engine";
import {
  chartErrorReducer as reduce,
  ENGINE_CODES as C,
  INITIAL,
  type ChartErrorState,
} from "../../../src/features/chart-errors/state";

const err = (code: string, extra: Partial<ChartEvents["error"]> = {}): ChartEvents["error"] => ({
  code,
  message: "",
  recoverable: true,
  ...extra,
});
const on = (s: ChartErrorState, e: ChartEvents["error"], now = 0): ChartErrorState =>
  reduce(s, { type: "error", error: e, now, ref: "urn:cv:ui:r" });
const lost = (attempt: number, nextTryMs: number, message = ""): ChartEvents["error"] =>
  err(C.lost, { message, details: { attempt, maxAttempts: 3, nextTryMs } });

describe("SCR-048 state model", () => {
  it("restoring takes attempt, maxAttempts and the next try from details; message is ignored", () => {
    const a = on(INITIAL, lost(2, 4000, "attempt 9 of 9 · next try in 99 s"), 1000);
    expect(a).toEqual({
      kind: "restoring",
      attempt: 2,
      maxAttempts: 3,
      nextAt: 5000,
      nextTryMs: 4000,
    });
    expect(on(INITIAL, lost(2, 4000, "other words"), 1000)).toEqual(a);
  });

  it("a loss without details shows the strip with no countdown", () => {
    expect(on(INITIAL, err(C.lost))).toEqual({
      kind: "restoring",
      attempt: 1,
      maxAttempts: 3,
      nextAt: null,
      nextTryMs: null,
    });
  });

  it("restored closes a restoring episode and is ignored otherwise", () => {
    expect(on(on(INITIAL, lost(1, 1000)), err(C.restored))).toEqual({ kind: "restored" });
    expect(on(INITIAL, err(C.restored))).toBe(INITIAL);
  });

  it.each([
    [C.restoreFailed, "failed"],
    [C.shaderFailed, "shader-failed"],
    [C.noWebgl2, "no-webgl2"],
    [C.workerLost, "worker-lost"],
  ])("%s opens the %s card with the minted reference", (code, kind) => {
    expect(on(on(INITIAL, lost(3, 4000)), err(code, { recoverable: false }))).toEqual({
      kind,
      code,
      ref: "urn:cv:ui:r",
      retry: "idle",
      recoverable: false,
    });
  });

  it("a worker that is still restarting (recoverable) opens no card", () => {
    expect(on(INITIAL, err(C.workerLost))).toBe(INITIAL);
    const pending = reduce(on(INITIAL, err(C.restoreFailed)), { type: "retry" });
    expect(on(pending, err(C.workerLost))).toBe(pending);
  });

  it("restored after a card, or during its pending retry, holds the card", () => {
    const card = on(INITIAL, err(C.restoreFailed));
    expect(on(card, err(C.restored))).toBe(card);
    const pending = reduce(card, { type: "retry" });
    expect(on(pending, err(C.restored))).toBe(pending);
  });

  it("a recreate resets any state to ok", () => {
    for (const s of [on(INITIAL, lost(1, 1000)), on(INITIAL, err(C.shaderFailed))])
      expect(reduce(s, { type: "reset" })).toBe(INITIAL);
    expect(reduce(INITIAL, { type: "reset" })).toBe(INITIAL);
  });

  it("unknown codes and a loss under a card change nothing", () => {
    expect(on(INITIAL, err("ENGINE_LOD_STEPDOWN"))).toBe(INITIAL);
    expect(on(INITIAL, err("constructor"))).toBe(INITIAL); // a prototype key is not a card
    const card = on(INITIAL, err(C.restoreFailed));
    expect(on(card, lost(1, 1000))).toBe(card);
    expect(on(card, err(C.shaderFailed))).toBe(card);
  });

  it("a manual retry is pending until a failure or a frame: WebGL2 restores, 2D fails", () => {
    const pending = reduce(on(INITIAL, err(C.restoreFailed)), { type: "retry" });
    expect(pending).toMatchObject({ kind: "failed", retry: "pending" });
    expect(on(pending, err(C.noWebgl2))).toMatchObject({
      kind: "failed",
      retry: "failed",
      ref: "urn:cv:ui:r",
    });
    expect(reduce(pending, { type: "frame", profile: "degraded-2d" })).toMatchObject({
      kind: "failed",
      retry: "failed",
      ref: "urn:cv:ui:r",
    });
    expect(reduce(pending, { type: "frame", profile: "full" })).toEqual({ kind: "restored" });
    expect(reduce(INITIAL, { type: "frame", profile: "full" })).toBe(INITIAL);
    expect(reduce(INITIAL, { type: "retry" })).toBe(INITIAL);
  });

  it("continue dismisses only the no-WebGL2 card, and basic rendering stays quiet", () => {
    const basic = reduce(on(INITIAL, err(C.noWebgl2)), { type: "continue" });
    expect(basic).toEqual({ kind: "basic" });
    expect(on(basic, err(C.noWebgl2))).toBe(basic);
    expect(on(basic, err(C.restoreFailed))).toMatchObject({ kind: "failed" });
    const failed = on(INITIAL, err(C.restoreFailed));
    expect(reduce(failed, { type: "continue" })).toBe(failed);
  });
});
