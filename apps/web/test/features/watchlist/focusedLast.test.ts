/**
 * E08-S08 (#4702), SR-31 / BG-02 (E08-D12; E08-D07 §4.5): the focused row's Last, spoken through PREF's gate
 * (`shouldAnnounce`), at most once per 2 s, the latest value, never the value focus landed on.
 */
import { describe, expect, it, vi } from "vitest";
import {
  LAST_CADENCE_MS,
  createFocusedLast,
  type PricePrefs,
} from "../../../src/features/watchlist/focusedLast";

const ALWAYS: PricePrefs = { announce_prices: "always", verbosity: "normal" };

function speaker(prefs: PricePrefs = ALWAYS) {
  const say = vi.fn<(text: string) => void>();
  const last = createFocusedLast(say, () => prefs);
  return { say, last };
}

describe("the focused row's Last (SR-31)", () => {
  it("'Always': a change is spoken once the 2 s since focus landed are up, the latest value, then one per 2 s", () => {
    const { say, last } = speaker();
    last.focus("BTCUSDT", "82,751.20", 0);
    last.update("82,751.20", 1_000); // the value focus landed on is the row's own reading
    last.update("82,751.30", 1_000); // within the 2 s
    expect(say).not.toHaveBeenCalled();
    last.update("82,751.40", LAST_CADENCE_MS);
    expect(say.mock.calls).toEqual([["82,751.40"]]);
    last.update("82,751.50", LAST_CADENCE_MS + 1_000);
    last.update("82,751.60", 2 * LAST_CADENCE_MS);
    expect(say.mock.calls).toEqual([["82,751.40"], ["82,751.60"]]);
    last.update("82,751.60", 4 * LAST_CADENCE_MS); // unchanged: nothing new to say
    expect(say).toHaveBeenCalledTimes(2);
  });

  it("'Off', 'On significant change' (E08 names no significant change of a Last) and a low verbosity speak none", () => {
    for (const prefs of [
      { announce_prices: "off", verbosity: "normal" },
      { announce_prices: "significant", verbosity: "normal" },
      { announce_prices: "always", verbosity: "low" },
    ] as const) {
      const { say, last } = speaker(prefs);
      last.focus("BTCUSDT", "1.00", 0);
      for (let t = 1_000; t <= 10_000; t += 1_000) last.update(`${t}.00`, t);
      expect(say, prefs.announce_prices).not.toHaveBeenCalled();
    }
  });

  it("focus on another row starts again from its own value; off every row nothing is spoken", () => {
    const { say, last } = speaker();
    last.focus("BTCUSDT", "1.00", 0);
    last.focus("ETHUSDT", "2.00", 5_000);
    last.update("2.00", 8_000);
    expect(say).not.toHaveBeenCalled();
    last.update("2.10", 8_000);
    expect(say.mock.calls).toEqual([["2.10"]]);
    last.focus(null, undefined, 9_000);
    last.update("2.20", 20_000);
    expect(say).toHaveBeenCalledTimes(1);
  });

  it("a row with no value says nothing", () => {
    const { say, last } = speaker();
    last.focus("XRPUSDT", undefined, 0);
    last.update(undefined, 5_000);
    expect(say).not.toHaveBeenCalled();
  });
});
