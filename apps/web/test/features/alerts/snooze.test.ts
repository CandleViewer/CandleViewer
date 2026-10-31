import { describe, expect, it } from "vitest";
import {
  SNOOZE_PRESETS,
  snoozeFromIso,
  snoozeFromPreset,
  snoozeUntil,
} from "../../../src/features/alerts/snooze.js";

const NOW = Date.parse("2026-10-31T12:00:00Z");
const clock = { now: () => NOW };

describe("snooze math", () => {
  it("maps each preset to now plus its span as a UTC ISO string", () => {
    const got = SNOOZE_PRESETS.map((p) => snoozeFromPreset(p, clock));
    expect(got).toEqual([
      { ok: true, until: "2026-10-31T12:15:00.000Z" },
      { ok: true, until: "2026-10-31T13:00:00.000Z" },
      { ok: true, until: "2026-10-31T16:00:00.000Z" },
      { ok: true, until: "2026-11-01T12:00:00.000Z" },
    ]);
  });
  it("uses the injected clock at call time", () => {
    let t = NOW;
    const c = { now: () => t };
    t += 60_000;
    expect(snoozeFromPreset("15m", c)).toEqual({ ok: true, until: "2026-10-31T12:16:00.000Z" });
  });
  it("refuses a past or equal instant", () => {
    expect(snoozeUntil(NOW - 1, clock)).toEqual({ ok: false, reason: "past" });
    expect(snoozeUntil(NOW, clock)).toEqual({ ok: false, reason: "past" });
    expect(snoozeUntil(NOW + 1, clock).ok).toBe(true);
  });
  it("refuses a non-finite instant", () => {
    expect(snoozeUntil(Number.NaN, clock)).toEqual({ ok: false, reason: "invalid" });
  });
  it("parses ISO strings, requiring an offset", () => {
    expect(snoozeFromIso("2026-10-31T14:00:00+02:00", clock)).toEqual({
      ok: false,
      reason: "past",
    });
    expect(snoozeFromIso("2026-10-31T15:00:00+02:00", clock)).toEqual({
      ok: true,
      until: "2026-10-31T13:00:00.000Z",
    });
    expect(snoozeFromIso("2026-10-31T15:00:00Z", clock)).toEqual({
      ok: true,
      until: "2026-10-31T15:00:00.000Z",
    });
    expect(snoozeFromIso("2026-10-31T15:00:00", clock)).toEqual({ ok: false, reason: "invalid" });
    expect(snoozeFromIso("garbage", clock)).toEqual({ ok: false, reason: "invalid" });
    expect(snoozeFromIso("2026-10-31T11:00:00Z", clock)).toEqual({ ok: false, reason: "past" });
  });
});
