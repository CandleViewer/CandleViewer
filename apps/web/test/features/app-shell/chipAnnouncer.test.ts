// #5345: the chip's announcements (E17-D02 §11 rows 4 and 5; E17-D01 §7), written through the
// shell announcer by CMP-076's container, never by the chip, which owns no live region. A stale
// episode is said politely once on entry and once on exit (after 5 s of freshness, so a flap is
// one episode); T2 once per episode, assertively; Delayed once on entry and exit. The exchange's
// feed down is CMP-092's row (§6 routing row 8), the transport CMP-077's: the chip says neither.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REGION_BUDGET_MS, type Politeness } from "../../../src/features/app-shell/announcer";
import {
  CHIP_SAID,
  EXIT_HOLD_MS,
  createChipAnnouncer,
  type ChipSpeech,
} from "../../../src/features/app-shell/chipAnnouncer";
import type { ChipView } from "../../../src/lib/ws/state/chipState";

const LIVE: ChipView = { status: "live" };
const DELAYED: ChipView = { status: "delayed", throttleMultiplier: 4 };
const stale = (over: Partial<Extract<ChipView, { status: "stale" }>> = {}): ChipView => ({
  status: "stale",
  cause: "age",
  ageMs: 7_000,
  strong: false,
  lastGoodTs: 0,
  t2Symbols: [],
  ...over,
});
const STRONG = stale({ ageMs: 15_400, strong: true, t2Symbols: ["BTCUSDT"] });
const UPSTREAM = stale({ cause: "upstream", ageMs: undefined });
const SERVER = stale({ cause: "server", ageMs: undefined, lastGoodTs: null });
const DOWN: ChipView = { status: "reconnecting", attempt: 1, firstConnect: false, lastGoodTs: 0 };

let said: string[];
let written: Record<Politeness, number>;
const io: ChipSpeech = {
  announce: (politeness, text) => {
    said.push(`${politeness}: ${text}`);
    written[politeness] = Date.now();
    return true;
  },
  forget: () => undefined,
  lastWrittenAt: (politeness) => written[politeness],
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};
const wait = (ms: number): void => void vi.advanceTimersByTime(ms);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 10, 1, 13, 42, 5));
  said = [];
  written = { polite: -Infinity, assertive: -Infinity };
});
afterEach(() => vi.useRealTimers());

/** An announcer that has seen `views`, one a second. */
function seen(...views: ChipView[]) {
  const a = createChipAnnouncer(io);
  for (const view of views) {
    a.see(view);
    wait(1_000);
  }
  return a;
}

describe("the copy (PROPOSED for #325, §10 H; derived from §11 rows 4 and 5)", () => {
  it("names the age and the symbols past T2, with E17-D01 §7's closing words", () => {
    expect(CHIP_SAID.t2(15_400, ["BTCUSDT"])).toBe(
      "Price feed stale 15 s on BTCUSDT. New orders off.",
    );
    expect(CHIP_SAID.t2(16_000, ["ETHUSDT", "BTCUSDT"])).toBe(
      "Price feeds stale 16 s on 2 symbols, including ETHUSDT. New orders off.",
    );
    expect([CHIP_SAID.delayedEntry, CHIP_SAID.delayedExit]).toEqual([
      "Reduced rate.",
      "Full rate restored.",
    ]);
  });
});

describe("a stale episode (§11 row 5)", () => {
  it("the first view is the baseline: nothing is said for it", () => {
    seen(STRONG, STRONG);
    expect(said).toEqual([]);
  });

  it("is said once on entry, never per age, and once on exit after 5 s of freshness", () => {
    const a = seen(LIVE, stale(), stale({ ageMs: 8_000 }), stale({ ageMs: 9_000 }));
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
    a.see(LIVE);
    wait(EXIT_HOLD_MS - 1);
    expect(said).toHaveLength(1);
    wait(1);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`, `polite: ${CHIP_SAID.staleExit}`]);
  });

  it("a flap inside the 5 s continues the episode in silence (T5's spirit)", () => {
    const a = seen(LIVE, stale(), LIVE, stale(), LIVE);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`, `polite: ${CHIP_SAID.staleExit}`]);
    wait(REGION_BUDGET_MS);
    a.see(stale()); // a new episode
    expect(said.at(-1)).toBe(`polite: ${CHIP_SAID.staleEntry}`);
  });

  it("Stale (server) is said as a T1 stale is", () => {
    const a = seen(LIVE, SERVER);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`, `polite: ${CHIP_SAID.staleExit}`]);
  });

  it("the exchange's feed down says nothing on entry or exit: CMP-092's row is its one announcement", () => {
    const a = seen(LIVE, UPSTREAM, UPSTREAM);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([]);
  });

  it("a Disconnected episode ends it in silence, and the recovery is CMP-077's to say", () => {
    const a = seen(LIVE, stale(), DOWN, DOWN);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });
});

describe("T2 (§11 row 4): one assertive sentence per episode", () => {
  it("is said when the episode first reaches T2, and never again in it", () => {
    const a = seen(LIVE, stale(), STRONG, STRONG, stale(), STRONG);
    expect(said).toEqual([
      `polite: ${CHIP_SAID.staleEntry}`,
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
    ]);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    a.see(STRONG); // a new episode, straight to T2
    expect(said.slice(2)).toEqual([
      `polite: ${CHIP_SAID.staleExit}`,
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
    ]);
  });

  it("an episode that starts at T2 says the T2 sentence alone, and its exit", () => {
    const a = seen(LIVE, STRONG);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
      `polite: ${CHIP_SAID.staleExit}`,
    ]);
  });
});

describe("Delayed (§11 row 5; `15` CMP-076)", () => {
  it("is said once on entry and once on exit (T3 keeps them 5 s apart at least)", () => {
    const a = seen(LIVE, DELAYED);
    wait(REGION_BUDGET_MS);
    a.see(DELAYED);
    a.see(LIVE);
    expect(said).toEqual([`polite: ${CHIP_SAID.delayedEntry}`, `polite: ${CHIP_SAID.delayedExit}`]);
  });

  it("a stale episode supersedes it: no exit is said for a Delayed the episode covered", () => {
    const a = seen(LIVE, DELAYED);
    wait(REGION_BUDGET_MS);
    a.see(stale());
    wait(REGION_BUDGET_MS);
    a.see(DELAYED); // the stale exit waits its 5 s of freshness
    wait(EXIT_HOLD_MS);
    a.see(LIVE);
    expect(said).toEqual([
      `polite: ${CHIP_SAID.delayedEntry}`,
      `polite: ${CHIP_SAID.staleEntry}`,
      `polite: ${CHIP_SAID.staleExit}`,
    ]);
  });
});

describe("the region budget (§11: one message per region per 5 s)", () => {
  it("waits until 5 s after the region's last write, by whoever, then says it if it still holds", () => {
    const a = seen(LIVE);
    written.polite = Date.now(); // another writer just spoke
    a.see(stale());
    expect(said).toEqual([]);
    wait(REGION_BUDGET_MS);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });

  it("drops a waiting word whose state has gone, and the exit of an entry never said", () => {
    const a = seen(LIVE);
    written.polite = Date.now();
    a.see(stale());
    wait(1_000);
    a.see(LIVE);
    wait(REGION_BUDGET_MS + EXIT_HOLD_MS);
    expect(said).toEqual([]);
  });

  it("dispose cancels what waits", () => {
    const a = seen(LIVE, stale());
    a.see(LIVE);
    a.dispose();
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });
});
