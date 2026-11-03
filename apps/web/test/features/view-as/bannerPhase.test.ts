import { describe, expect, it } from "vitest";
import {
  FIVE_MINUTES_S,
  ONE_MINUTE_S,
  PHASE_GLYPH,
  bannerAnnouncement,
  bannerPhase,
  nextPhaseInMs,
  secondsLeft,
  type BannerPhase,
} from "../../../src/features/view-as/bannerPhase";
import { VA_COPY, bannerSentences, fillUser } from "../../../src/features/view-as/copy";
import type { HeldViewAs } from "../../../src/shell/bootstrap/store";

/**
 * E42-S03 (SCR-124 V-4 to V-8): the banner's phase runs on the server's clock to its `expires_at`;
 * the glyph changes at 5:00 and 1:00 only, and an ended context is the server's `expired`.
 */
const EXPIRES = Date.parse("2026-09-14T10:30:00Z");
const held = (patch: Partial<HeldViewAs> = {}): HeldViewAs => ({
  kind: "held",
  targetId: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
  targetName: "alex",
  startedAtMs: EXPIRES - 1_800_000,
  expiresAtMs: EXPIRES,
  state: "active",
  offsetMs: 0,
  ...patch,
});
/** The client clock when `ms` are left on the server's, for a server `offsetMs` ahead. */
const at = (ms: number, offsetMs = 0): number => EXPIRES - ms - offsetMs;

describe("secondsLeft and bannerPhase", () => {
  it("counts whole seconds up, never below 0, on the server's clock", () => {
    expect(secondsLeft(held(), at(1_659_001))).toBe(1_660); // 27:40, rounded up
    expect(secondsLeft(held(), at(-5_000))).toBe(0);
    // the client's clock runs 7 s behind the server's: the server's count wins
    expect(secondsLeft(held({ offsetMs: 7_000 }), at(60_000, 7_000))).toBe(60);
  });

  it.each<[string, number, BannerPhase]>([
    ["27:40", 1_660_000, "normal"],
    ["5:01", 301_000, "normal"],
    ["5:00 (V-5)", FIVE_MINUTES_S * 1_000, "five"],
    ["1:01", 61_000, "five"],
    ["1:00 (V-6)", ONE_MINUTE_S * 1_000, "one"],
    ["0:00, before the server says it ended", 0, "one"],
  ])("reads %s left as %s", (_name, msLeft, phase) => {
    expect(bannerPhase(held(), at(msLeft))).toBe(phase);
  });

  it("reads the phase on the server's clock, whatever the client's says", () => {
    const ahead = held({ offsetMs: -20_000 }); // the client runs 20 s ahead
    expect(bannerPhase(ahead, at(310_000, -20_000))).toBe("normal");
    expect(bannerPhase(ahead, at(300_000, -20_000))).toBe("five");
  });

  it("is ended only when the server says so (V-8), never by the clock", () => {
    expect(bannerPhase(held({ state: "expired" }), at(1_000_000))).toBe("ended");
    expect(bannerPhase(held(), at(-60_000))).toBe("one");
  });

  it("draws no glyph, then the warning triangle, then the danger octagon", () => {
    expect(PHASE_GLYPH).toEqual({ normal: null, five: "warning", one: "danger", ended: null });
  });
});

describe("nextPhaseInMs: one timer per mark, never per tick", () => {
  it.each<[string, number, number | null]>([
    ["at 27:40, to 5:00", 1_660_000, 1_360_000],
    ["at 5:00:001, to 5:00", 300_001, 1],
    ["at 3:00, to 1:00", 180_000, 120_000],
    ["at 1:00, none left", 60_000, null],
    ["at 0:30, none left", 30_000, null],
  ])("%s", (_name, msLeft, next) => {
    expect(nextPhaseInMs(held(), at(msLeft))).toBe(next);
  });

  it("has none for an ended context", () => {
    expect(nextPhaseInMs(held({ state: "expired" }), at(1_000_000))).toBeNull();
  });

  it("lands the timer exactly on the mark it waits for", () => {
    for (const msLeft of [1_660_000, 299_999 + 61_000, 61_001]) {
      const wait = nextPhaseInMs(held(), at(msLeft)) ?? 0;
      expect(bannerPhase(held(), at(msLeft) + wait - 1)).toBe(bannerPhase(held(), at(msLeft)));
      expect(bannerPhase(held(), at(msLeft) + wait)).not.toBe(bannerPhase(held(), at(msLeft)));
    }
  });
});

describe("bannerAnnouncement: D03 §13's voice, once each", () => {
  it.each<[BannerPhase | null, BannerPhase, string | null, string | null]>([
    [null, "normal", "assertive", VA_COPY.announceRo],
    [null, "five", "assertive", VA_COPY.announceRo], // a mark passed before the page loaded is not said
    [null, "one", "assertive", VA_COPY.announceRo],
    [null, "ended", "assertive", VA_COPY.ended],
    ["normal", "five", "polite", VA_COPY.announce5min],
    ["five", "one", "assertive", VA_COPY.announce1min],
    ["normal", "one", "assertive", VA_COPY.announce1min], // back from sleep: the later mark alone
    ["one", "ended", "assertive", VA_COPY.ended],
    ["normal", "ended", "assertive", VA_COPY.ended],
    ["one", "five", null, null],
  ])("%s → %s", (prev, next, politeness, text) => {
    const said = bannerAnnouncement(prev, next);
    expect(said === null ? [null, null] : [said.politeness, said.text]).toEqual([politeness, text]);
  });

  it("says nothing while the phase holds: no announcement per countdown tick", () => {
    for (const phase of ["normal", "five", "one", "ended"] as const)
      expect(bannerAnnouncement(phase, phase)).toBeNull();
  });

  it("keys each announcement once per page load", () => {
    const keys = (["normal", "five", "one", "ended"] as const).map(
      (next, i, all) => bannerAnnouncement(i === 0 ? null : (all[i - 1] ?? null), next)?.key,
    );
    expect(keys).toEqual(["view-as:entry", "view-as:5min", "view-as:1min", "view-as:ended"]);
  });
});

describe("copy", () => {
  it("splits va.banner_ro around its countdown, verbatim", () => {
    const { lead, endsBefore, endsAfter } = bannerSentences("alex");
    expect(`${lead} ${endsBefore}27:40${endsAfter}`).toBe(
      fillUser(VA_COPY.bannerRo, "alex").replace("{m:ss}", "27:40"),
    );
    expect([lead, endsBefore, endsAfter]).toEqual([
      "Viewing as alex (read-only).",
      "Ends in ",
      ".",
    ]);
  });

  it("cuts before the fill: a name holding '. ' cannot move the cut", () => {
    expect(bannerSentences("A. Lex").lead).toBe("Viewing as A. Lex (read-only).");
  });

  it("fills every {user}", () => {
    expect(fillUser("{user} and {user}", "alex")).toBe("alex and alex");
  });
});
