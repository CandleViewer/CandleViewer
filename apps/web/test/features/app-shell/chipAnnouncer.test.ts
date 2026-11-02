// #5345: the chip's announcements (E17-D02 §11 rows 4 and 5; E17-D01 §7), written through the
// shell announcer by CMP-076's container, never by the chip, which owns no live region. A stale
// episode is said politely once on entry and once on exit (after 5 s of freshness, so a flap is
// one episode); T2 once per episode, assertively; Delayed once on entry and exit. The exchange's
// feed down is entered by CMP-092's row (§6 routing row 8) and left by the chip's exit; the
// transport is CMP-077's, and ends the chip's episodes in silence. An ended episode's sentences
// leave the regions once its exit is written.
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
  t2AgeMs: undefined,
  strong: false,
  lastGoodTs: 0,
  t2Symbols: [],
  ...over,
});
const STRONG = stale({ ageMs: 15_400, t2AgeMs: 15_400, strong: true, t2Symbols: ["BTCUSDT"] });
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
  clear: (prefix) => void said.push(`clear: ${prefix}`),
  lastWrittenAt: (politeness) => written[politeness],
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};
const wait = (ms: number): void => void vi.advanceTimersByTime(ms);
/** What was said, without the clears. */
const spoken = (): string[] => said.filter((s) => !s.startsWith("clear: "));

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
  it("names the age and the symbols past T2, and claims no order gate (none enforces one yet)", () => {
    expect(CHIP_SAID.t2(15_400, ["BTCUSDT"])).toBe("Price feed stale 15 s on BTCUSDT.");
    expect(CHIP_SAID.t2(16_000, ["ETHUSDT", "BTCUSDT"])).toBe(
      "Price feeds stale 16 s on 2 symbols, including ETHUSDT.",
    );
    expect(CHIP_SAID.t2(16_000, [])).toBe("Price feeds stale 16 s.");
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
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
    a.see(LIVE);
    wait(EXIT_HOLD_MS - 1);
    expect(spoken()).toHaveLength(1);
    wait(1);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`, `polite: ${CHIP_SAID.staleExit}`]);
  });

  it("its end takes its sentences out of the regions, after its exit is written", () => {
    const a = seen(LIVE, stale(), STRONG);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([
      `polite: ${CHIP_SAID.staleEntry}`,
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
      `polite: ${CHIP_SAID.staleExit}`,
      "clear: chip:stale", // its entry and T2 keys; the exit's own key stays
    ]);
  });

  it("an exit that waits for the region's budget clears the episode once it is written", () => {
    const a = seen(LIVE, stale());
    a.see(LIVE);
    wait(EXIT_HOLD_MS - 1);
    written.polite = Date.now(); // another writer speaks just before the exit is due
    wait(1);
    expect(said).toHaveLength(1);
    wait(REGION_BUDGET_MS);
    expect(said.slice(1)).toEqual([`polite: ${CHIP_SAID.staleExit}`, "clear: chip:stale"]);
  });

  it("a flap inside the 5 s continues the episode in silence (T5's spirit)", () => {
    const a = seen(LIVE, stale(), LIVE, stale(), LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`, `polite: ${CHIP_SAID.staleExit}`]);
    wait(REGION_BUDGET_MS);
    a.see(stale()); // a new episode
    expect(spoken().at(-1)).toBe(`polite: ${CHIP_SAID.staleEntry}`);
  });

  it("Stale (server) is said as a T1 stale is", () => {
    const a = seen(LIVE, SERVER);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`, `polite: ${CHIP_SAID.staleExit}`]);
  });

  it("the exchange's feed down: CMP-092's row says its entry, and the chip its exit, once", () => {
    const a = seen(LIVE, UPSTREAM, UPSTREAM);
    expect(said).toEqual([]);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleExit}`]);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toHaveLength(1);
  });

  it("a feed down under way at the first view is the baseline: its exit is not said either", () => {
    const a = seen(UPSTREAM, UPSTREAM);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toEqual([]);
  });

  it("a Disconnected episode ends it in silence, clears the chip's sentences, and the recovery is CMP-077's to say", () => {
    const a = seen(LIVE, stale(), DOWN, DOWN);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`, "clear: chip:"]); // once, on entering
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });
});

describe("T2 (§11 row 4): one assertive sentence per episode", () => {
  it("is said when the episode first reaches T2, and never again in it", () => {
    const a = seen(LIVE, stale(), STRONG, STRONG, stale(), STRONG);
    expect(spoken()).toEqual([
      `polite: ${CHIP_SAID.staleEntry}`,
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
    ]);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    a.see(STRONG); // a new episode, straight to T2
    expect(spoken().slice(2)).toEqual([
      `polite: ${CHIP_SAID.staleExit}`,
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
    ]);
  });

  it("an episode that starts at T2 says the T2 sentence alone, and its exit", () => {
    const a = seen(LIVE, STRONG);
    a.see(LIVE);
    wait(EXIT_HOLD_MS);
    expect(spoken()).toEqual([
      `assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`,
      `polite: ${CHIP_SAID.staleExit}`,
    ]);
  });

  it("names the age of the topics past T2, not the oldest topic's past T1 only", () => {
    // book.ETHUSDT 7 s old (past its 6 s T2) beside trades.BTCUSDT 12 s old (past its T1 only)
    seen(LIVE, stale({ ageMs: 12_000, t2AgeMs: 7_000, strong: true, t2Symbols: ["ETHUSDT"] }));
    expect(spoken()).toEqual([`assertive: ${CHIP_SAID.t2(7_000, ["ETHUSDT"])}`]);
    expect(CHIP_SAID.t2(7_000, ["ETHUSDT"])).toBe("Price feed stale 7 s on ETHUSDT.");
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
    expect(spoken()).toEqual([
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
    expect(spoken()).toEqual([]);
  });

  it("dispose cancels what waits", () => {
    const a = seen(LIVE, stale());
    a.see(LIVE);
    a.dispose();
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });

  it("an exit that a newer polite sentence replaces still clears its episode's keys", () => {
    const a = seen(LIVE, STRONG); // the T2 sentence is said, assertively
    a.see(LIVE);
    wait(EXIT_HOLD_MS - 1);
    written.polite = Date.now(); // another writer speaks politely just before the exit is due
    wait(1); // the exit waits for the region's budget
    a.see(DELAYED); // and a Delayed entry takes its turn
    expect(said).toEqual([`assertive: ${CHIP_SAID.t2(15_400, ["BTCUSDT"])}`, "clear: chip:stale"]);
    wait(REGION_BUDGET_MS);
    expect(spoken().at(-1)).toBe(`polite: ${CHIP_SAID.delayedEntry}`);
    expect(spoken()).not.toContain(`polite: ${CHIP_SAID.staleExit}`);
  });
});

describe("the exit re-reads the chip when it falls due: the last render may be a second old", () => {
  it("a ticker that sends one frame every 6 s is one episode: its exit is not said as the chip reads Stale again", () => {
    // T1 is 5 s: Live for 5 s of each 6 and Stale for 1, so the exit's 5 s fall due as it reads Stale
    const start = Date.now();
    const chip = (): ChipView =>
      (Date.now() - start) % 6_000 >= 5_000 ? stale({ ageMs: 5_000 }) : LIVE;
    const a = createChipAnnouncer(io);
    for (let s = 0; s < 40; s += 1) {
      a.see(chip(), chip); // the container's render, once a second, and how to read the chip again
      wait(1_000);
    }
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });

  it("an exit waiting for the region's budget is dropped if the chip reads Stale again by then", () => {
    let current: ChipView = LIVE;
    const chip = (): ChipView => current;
    const a = createChipAnnouncer(io);
    a.see(LIVE, chip);
    wait(1_000);
    current = stale();
    a.see(current, chip); // the entry is said
    wait(1_000);
    current = LIVE;
    a.see(current, chip); // fresh: the exit's 5 s begin
    wait(EXIT_HOLD_MS - 1);
    written.polite = Date.now(); // another writer speaks just before the exit is due
    wait(1); // due: the chip still reads Live, so it waits for the budget
    current = stale(); // and reads Stale before the next render says so
    wait(REGION_BUDGET_MS);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
  });

  it("a chip that reads Live when it falls due says it, as before", () => {
    const chip = (): ChipView => LIVE;
    const a = createChipAnnouncer(io);
    a.see(LIVE, chip);
    wait(1_000);
    a.see(stale(), chip);
    wait(1_000);
    a.see(LIVE, chip);
    wait(EXIT_HOLD_MS);
    expect(said).toEqual([
      `polite: ${CHIP_SAID.staleEntry}`,
      `polite: ${CHIP_SAID.staleExit}`,
      "clear: chip:stale",
    ]);
  });

  it("a chip that reads Disconnected when it falls due ends the episode in silence", () => {
    let current: ChipView = LIVE;
    const chip = (): ChipView => current;
    const a = createChipAnnouncer(io);
    a.see(LIVE, chip);
    wait(1_000);
    a.see(stale(), chip);
    wait(1_000);
    a.see(LIVE, chip);
    wait(EXIT_HOLD_MS - 1);
    current = DOWN; // the link dropped since the last render
    wait(1);
    expect(spoken()).toEqual([`polite: ${CHIP_SAID.staleEntry}`]);
    expect(said.at(-1)).toBe("clear: chip:"); // the chip's sentences leave the regions, as a render of it would
  });
});
