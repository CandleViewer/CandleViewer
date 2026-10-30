// E11-S02 PR4: SCR-048's state model is driven by `code` and `details` only (never `message`).
// E11-T05: the reduced list (BQ-90), the once-per-session `seen` (BQ-96) and the 2D handoff.
import { describe, expect, it } from "vitest";
import type { ChartEvents } from "@candleviewer/chart-engine";
import {
  chartErrorReducer as reduce,
  ENGINE_CODES as C,
  INITIAL,
  REDUCED_ORDER,
  reducedOf,
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

  it("a loss without details, or with null details, shows the strip with no countdown", () => {
    const none = { kind: "restoring", attempt: 1, maxAttempts: 3, nextAt: null, nextTryMs: null };
    expect(on(INITIAL, err(C.lost))).toEqual(none);
    const nul = null as unknown as NonNullable<ChartEvents["error"]["details"]>;
    expect(on(INITIAL, err(C.lost, { details: nul }))).toEqual(none);
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
    expect(on(on(INITIAL, lost(3, 4000)), err(code, { recoverable: false }))).toMatchObject({
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

  it("a manual retry is pending until a failure or a frame: WebGL2 restores, 2D hands over", () => {
    const pending = reduce(on(INITIAL, err(C.restoreFailed)), { type: "retry" });
    expect(pending).toMatchObject({ kind: "failed", retry: "pending" });
    expect(on(pending, err(C.noWebgl2))).toMatchObject({
      kind: "failed",
      retry: "failed",
      ref: "urn:cv:ui:r",
    });
    // The ruled handoff: a retry that lands in 2D is the degraded card, its retry failed.
    expect(reduce(pending, { type: "frame", profile: "degraded-2d" })).toMatchObject({
      kind: "no-webgl2",
      retry: "failed",
      ref: "urn:cv:ui:r",
      handover: true,
    });
    const webgl = reduce(on(INITIAL, err(C.noWebgl2)), { type: "retry" });
    expect(reduce(webgl, { type: "frame", profile: "degraded-2d" })).toMatchObject({
      kind: "no-webgl2",
      retry: "failed",
      handover: false,
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

describe("E11-T05 reduced list, once per session and the 2D handoff", () => {
  const degrade = (reducedCapabilities: unknown, reason: unknown = "no-webgl2") =>
    ({ reducedCapabilities, reason }) as NonNullable<ChartEvents["error"]["details"]>;

  it("reducedOf keeps the vocabulary order, drops unknown values and defaults to all five", () => {
    expect(reducedOf(undefined)).toEqual(REDUCED_ORDER);
    expect(reducedOf({ attempt: 1, maxAttempts: 3, nextTryMs: 1000 })).toEqual(REDUCED_ORDER);
    expect(reducedOf(degrade(["gpu-effects", "heatmap", "sparkles", "heatmap"]))).toEqual([
      "heatmap",
      "gpu-effects",
    ]);
    // An empty filtered list is treated like a missing one: a body never names no reduction.
    expect(reducedOf(degrade(["sparkles"], "warp"))).toEqual(REDUCED_ORDER);
    expect(reducedOf(degrade([]))).toEqual(REDUCED_ORDER);
    expect(reducedOf(degrade("heatmap"))).toEqual(REDUCED_ORDER);
    // A null or non-object `details` from the worker is ignored, never a crash (PR 1 Low-3).
    for (const bad of [null, "heatmap", 7])
      expect(reducedOf(bad as unknown as ChartEvents["error"]["details"])).toEqual(REDUCED_ORDER);
  });

  it("ENGINE_NO_WEBGL2 carries the list onto the card; an unknown reason opens it unchanged", () => {
    expect(on(INITIAL, err(C.noWebgl2, { details: degrade(["heatmap"], "warp") }))).toEqual({
      kind: "no-webgl2",
      code: C.noWebgl2,
      ref: "urn:cv:ui:r",
      retry: "idle",
      recoverable: true,
      reduced: ["heatmap"],
      handover: false,
    });
    expect(on(INITIAL, err(C.noWebgl2))).toMatchObject({ reduced: REDUCED_ORDER });
  });

  it("a degraded card already shown this session goes straight to basic", () => {
    const action = { type: "error", error: err(C.noWebgl2), now: 0, ref: "r", seen: true } as const;
    expect(reduce(INITIAL, action)).toEqual({ kind: "basic" });
  });

  it.each([C.restoreFailed, C.shaderFailed])(
    "%s then a degraded-2d frame becomes the degraded card with all five, code and ref kept",
    (code) => {
      const card = on(INITIAL, err(code, { recoverable: false }));
      expect(reduce(card, { type: "frame", profile: "degraded-2d" })).toEqual({
        kind: "no-webgl2",
        code,
        ref: "urn:cv:ui:r",
        retry: "idle",
        recoverable: false,
        reduced: REDUCED_ORDER,
        handover: true,
      });
      const seen = { type: "frame", profile: "degraded-2d", seen: true } as const;
      expect(reduce(card, seen)).toEqual({ kind: "basic" });
      expect(reduce(card, { type: "frame", profile: "full" })).toBe(card);
    },
  );

  it("a worker that could not be restarted keeps the fatal card on any frame", () => {
    const card = on(INITIAL, err(C.workerLost, { recoverable: false }));
    expect(reduce(card, { type: "frame", profile: "degraded-2d" })).toBe(card);
  });
});
