/**
 * E08-S08 (#4702): the panel owns no live region; it says one polite summary on entering a stale episode and one on
 * leaving it, never per tick, row or age change, flapping within 5 s collapsed (E08-D07 D17, §4.5; `15` CMP-239).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  EXIT_HOLD_MS,
  LIVE_AGAIN,
  createStaleEpisode,
  staleSummary,
} from "../../../src/features/watchlist/staleEpisode";

describe("staleSummary", () => {
  it("names up to three symbols, then 'and N more'", () => {
    expect(staleSummary(["SOLUSDT"])).toBe("1 watchlist symbol stale: SOLUSDT.");
    expect(staleSummary(["SOLUSDT", "DOGEUSDT", "PEPEUSDT"])).toBe(
      "3 watchlist symbols stale: SOLUSDT, DOGEUSDT, PEPEUSDT.",
    );
    expect(staleSummary(["A1USDT", "A2USDT", "A3USDT", "A4USDT", "A5USDT"])).toBe(
      "5 watchlist symbols stale: A1USDT, A2USDT, A3USDT and 2 more.",
    );
  });
});

describe("createStaleEpisode", () => {
  beforeEach(() => vi.useFakeTimers({ now: 0 }));
  afterEach(() => vi.useRealTimers());

  const make = () => {
    const said: string[] = [];
    const entered = vi.fn();
    const episode = createStaleEpisode({ say: (text) => said.push(text), entered });
    return { said, entered, episode };
  };

  it("says the entry once, with the names, however often the stale set is re-read or grows", () => {
    const { said, entered, episode } = make();
    episode.update([]);
    episode.update(["SOLUSDT"]);
    episode.update(["SOLUSDT"]);
    episode.update(["SOLUSDT", "ETHUSDT"]);
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT."]);
    expect(entered).toHaveBeenCalledOnce();
  });

  it("says the exit once the stale set has stayed empty for 5 s", () => {
    const { said, episode } = make();
    episode.update(["SOLUSDT"]);
    episode.update([]);
    vi.advanceTimersByTime(EXIT_HOLD_MS - 1);
    expect(said).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT.", LIVE_AGAIN]);
    expect(LIVE_AGAIN).toBe("Watchlist prices live again.");
  });

  it("collapses a flap within 5 s: the episode goes on, nothing more is said", () => {
    const { said, entered, episode } = make();
    episode.update(["SOLUSDT"]);
    episode.update([]);
    vi.advanceTimersByTime(3_000);
    episode.update(["SOLUSDT"]);
    vi.advanceTimersByTime(10_000);
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT."]);
    expect(entered).toHaveBeenCalledOnce();
  });

  it("a later episode is said again, entry and exit", () => {
    const { said, episode } = make();
    episode.update(["SOLUSDT"]);
    episode.update([]);
    vi.advanceTimersByTime(EXIT_HOLD_MS);
    episode.update(["ETHUSDT"]);
    expect(said).toEqual([
      "1 watchlist symbol stale: SOLUSDT.",
      LIVE_AGAIN,
      "1 watchlist symbol stale: ETHUSDT.",
    ]);
  });

  it("while held (Disconnected) it says nothing, and resumes on release", () => {
    const { said, episode } = make();
    episode.update(["SOLUSDT"]);
    episode.hold(true);
    episode.update([]);
    vi.advanceTimersByTime(EXIT_HOLD_MS * 2);
    episode.update(["ETHUSDT"]);
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT."]);
    episode.hold(false);
    episode.update([]);
    vi.advanceTimersByTime(EXIT_HOLD_MS);
    expect(said).toEqual(["1 watchlist symbol stale: SOLUSDT.", LIVE_AGAIN]);
  });

  it("dispose leaves no timer behind", () => {
    const { episode } = make();
    episode.update(["SOLUSDT"]);
    episode.update([]);
    episode.dispose();
    expect(vi.getTimerCount()).toBe(0);
  });
});
