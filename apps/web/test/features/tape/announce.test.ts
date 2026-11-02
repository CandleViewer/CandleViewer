// E22-S01 (#714) PR-B: the panel's status node (E22-D04 §7, A38): whale opt-in off by default,
// the half-open 5 s window (leading + trailing), suppression while a row is focused or verbosity is
// low (dropped, never held), and the user-action sentences.
import { beforeEach, describe, expect, it } from "vitest";
import { NEVER_WHALE, TapeAnnouncer, WHALE_WINDOW_MS } from "../../../src/features/tape/announce";
import {
  FLAG_BIG,
  SIDE_BUY,
  SIDE_SELL,
  TapeRing,
  type TapeSide,
} from "../../../src/features/tape/model/ring";

let ring: TapeRing;
let node: HTMLElement;
const writes: string[] = [];

/** A fixture tier-2 predicate (BQ-210): the server's flag stands in for S02's rule. */
const flagged = (r: TapeRing, seq: number): boolean =>
  ((r.flags[r.slot(seq)] ?? 0) & FLAG_BIG) !== 0;

const add = (whale: boolean, side: TapeSide = SIDE_SELL, size = "6.4", price = "64012.0"): number =>
  ring.push({
    id: undefined,
    tsMs: 0,
    price,
    size,
    side,
    flags: whale ? FLAG_BIG : 0,
    clusterSize: 1,
  }) ?? -1;

const watch = (a: TapeAnnouncer): void => {
  writes.length = 0;
  node = document.createElement("div");
  new MutationObserver(() => writes.push(node.textContent ?? "")).observe(node, {
    childList: true,
    characterData: true,
    subtree: true,
  });
  a.attach(node);
};

/** Lets the MutationObserver's microtask run: no timer, no wall clock (C-13.7). */
const flush = () => new Promise<void>((r) => queueMicrotask(r));

beforeEach(() => {
  ring = new TapeRing(100);
});

describe("tape announcer", () => {
  it("S01-u-08 / AN-07: off by default: whales never write, the node stays empty", async () => {
    const a = new TapeAnnouncer({ isWhale: flagged });
    watch(a);
    const seq = add(true);
    a.observe(ring, seq, seq, 0);
    a.tick(WHALE_WINDOW_MS * 3);
    await flush();
    expect(node.textContent).toBe("");
    expect(writes).toEqual([]);
    expect(NEVER_WHALE(ring, seq)).toBe(false);
  });

  it("AN-01 / AN-02: the first whale at once; the rest summed at the window's close", () => {
    const a = new TapeAnnouncer({ whaleOptIn: true, isWhale: flagged });
    watch(a);
    const s1 = add(true, SIDE_SELL, "6.4");
    a.observe(ring, s1, s1, 1_000);
    expect(node.textContent).toBe("Whale sell, 409.7k at 64,012.0");
    const s2 = add(true, SIDE_SELL, "2");
    add(true, SIDE_BUY, "3");
    const s4 = add(false);
    a.observe(ring, s2, s4, 2_000);
    a.tick(5_999);
    expect(a.writes).toBe(1); // half-open: not before t + 5 000
    a.tick(6_000);
    expect(node.textContent).toBe(
      "2 whale prints in 5 s: 1 sell, 1 buy, largest buy 192k at 64,012.0",
    );
    a.tick(11_000); // a window that closes with no whale ends the run
    const s5 = add(true, SIDE_SELL, "1");
    a.observe(ring, s5, s5, 11_500);
    expect(node.textContent).toBe("Whale sell, 64k at 64,012.0"); // leading again
    expect(a.writes).toBe(3);
  });

  it("sums same-side whales in the deck's form", () => {
    const a = new TapeAnnouncer({ whaleOptIn: true, isWhale: flagged });
    watch(a);
    const s0 = add(true);
    a.observe(ring, s0, s0, 0);
    const from = add(true, SIDE_SELL, "1");
    add(true, SIDE_SELL, "2");
    const to = add(true, SIDE_SELL, "6.4");
    a.observe(ring, from, to, 100);
    a.tick(5_000);
    expect(node.textContent).toBe("3 whale sells in 5 s, largest 409.7k at 64,012.0");
  });

  it("AN-08: a focused row drops whales and the open window's sum, keeping its clock", () => {
    const a = new TapeAnnouncer({ whaleOptIn: true, isWhale: flagged });
    watch(a);
    const s0 = add(true);
    a.observe(ring, s0, s0, 0);
    const s1 = add(true);
    a.observe(ring, s1, s1, 1_000); // pending in the window
    a.setRowFocused(true); // drops the pending sum
    const s2 = add(true);
    a.observe(ring, s2, s2, 2_000); // dropped, not held
    a.setRowFocused(false);
    a.tick(5_000);
    expect(a.writes).toBe(1);
    const s3 = add(true);
    a.observe(ring, s3, s3, 6_000);
    expect(a.writes).toBe(2);
  });

  it("AN-08: low verbosity suppresses whales as a focused row does", () => {
    const a = new TapeAnnouncer({ whaleOptIn: true, isWhale: flagged });
    watch(a);
    a.setVerbosity("low");
    const s = add(true);
    a.observe(ring, s, s, 0);
    expect(a.writes).toBe(0);
    a.setVerbosity("normal");
    a.observe(ring, s, s, 10);
    expect(a.writes).toBe(1);
  });

  it("says a user-action sentence at once, replacing the text, and nothing with no node", () => {
    const a = new TapeAnnouncer();
    a.say("lost");
    expect(a.writes).toBe(0);
    watch(a);
    a.say("Resumed, 412 prints inserted");
    expect(node.textContent).toBe("Resumed, 412 prints inserted");
  });
});
