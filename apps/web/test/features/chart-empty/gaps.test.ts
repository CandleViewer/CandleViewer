/** E16-S05: the gap carriers' facts and words (E16-D05 §3, §6–§8; D05-CG1; D05-G1). */
import { describe, expect, it } from "vitest";
import { AC4_COVERAGE, COVERAGE_FIXTURE, at } from "../../../src/features/chart-empty/fixtures";
import {
  coverageHorizon,
  gapCause,
  gapIntervals,
  missingSentence,
  type GapInterval,
} from "../../../src/features/chart-empty/gaps";

const AC4: GapInterval = {
  fromMs: at("2026-09-04T02:11:00Z"),
  toMs: at("2026-09-04T02:23:00Z"),
  reason: "ws_disconnect",
  backfilled: false,
};
const WIDE = { fromMs: at("2026-09-01T00:00:00Z"), toMs: at("2026-09-15T00:00:00Z") };
const g = (from: string, to: string, reason?: "seq_jump" | "ws_disconnect") =>
  reason === undefined ? { from, to } : { from, to, reason };

describe("gapIntervals", () => {
  it("clips to the window for the engine, whole when asked", () => {
    const w = { fromMs: at("2026-09-04T02:15:00Z"), toMs: at("2026-09-04T03:00:00Z") };
    expect(gapIntervals(AC4_COVERAGE, w)).toEqual([{ ...AC4, fromMs: w.fromMs }]);
    expect(gapIntervals(AC4_COVERAGE, w, false)).toEqual([AC4]);
  });

  it("dedupes across streams, drops the outside and the unreadable, in time order", () => {
    const extra = [
      g("2026-09-04T02:11:00Z", "2026-09-04T02:23:00Z", "ws_disconnect"),
      g("2026-09-02T00:00:00Z", "2026-09-02T00:01:00Z", "seq_jump"),
      g("2026-10-02T00:00:00Z", "2026-10-02T00:01:00Z", "seq_jump"),
      g("bad", "2026-10-02T00:01:00Z"),
    ];
    const streams = [...(AC4_COVERAGE.streams ?? []), { gaps: extra }];
    const got = gapIntervals({ ...AC4_COVERAGE, streams }, WIDE);
    expect(got.map((x) => x.reason)).toEqual(["seq_jump", "ws_disconnect"]);
  });

  it("never shows coverage older than the report's 90 days (D05-CG1)", () => {
    const gaps = [g("2026-09-04T00:00:00Z", "2026-10-04T00:00:00Z")];
    const old = { generated_at: "2026-12-31T00:00:00Z", streams: [{ gaps }] };
    const horizon = at("2026-10-02T00:00:00Z");
    expect(coverageHorizon(old)).toBe(horizon);
    expect(gapIntervals(old, { fromMs: 0, toMs: at("2027-01-01T00:00:00Z") })).toEqual([
      { fromMs: horizon, toMs: at("2026-10-04T00:00:00Z"), reason: null, backfilled: false },
    ]);
    expect(coverageHorizon({})).toBeNull();
  });

  it("reads `backfilled` by presence only (D05-G1, BQ-04 (a))", () => {
    const gaps = [{ ...g("2026-09-04T02:11:00Z", "2026-09-04T02:23:00Z"), backfilled: true }];
    expect(gapIntervals({ streams: [{ gaps }] }, WIDE)[0]?.backfilled).toBe(true);
    expect(gapIntervals(COVERAGE_FIXTURE, WIDE)[0]?.backfilled).toBe(false);
  });
});

describe("the words", () => {
  it("gapCause: the deck; an unknown reason takes the fallback (C-6.3)", () => {
    expect(gapCause("seq_jump")).toBe("Recording lost order-book updates (sequence gap).");
    for (const r of ["maintenance_pause", "toString", null])
      expect(gapCause(r)).toBe("Recording gap.");
    expect(gapCause("retention_purge")).toMatch(/\(30 days\)/);
  });

  it("ranges are symbol-info gapText's words; every range is listed (G-09)", () => {
    const night = { ...AC4, fromMs: at("2026-09-04T23:58:00Z"), toMs: at("2026-09-05T00:02:00Z") };
    expect(missingSentence(gapIntervals(COVERAGE_FIXTURE, WIDE))).toBe(
      "Missing: 4 Sep 02:11–02:15 UTC, connection lost.",
    );
    expect(missingSentence([AC4, { ...night, reason: "x" }])).toBe(
      "Missing: 4 Sep 02:11–02:23 UTC, connection lost; 4 Sep 23:58–5 Sep 00:02 UTC, a gap.",
    );
    expect(missingSentence([])).toBeNull();
  });

  it("a backfilled gap adds the PROPOSED tooltip line (D05-G1)", () => {
    expect(missingSentence([{ ...AC4, backfilled: true }])).toBe(
      "Missing: 4 Sep 02:11–02:23 UTC, connection lost " +
        "(Bars from exchange klines; order flow missing.).",
    );
  });
});
