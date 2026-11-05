// E15-S03 (#476) PR-1: region names (E15-D03 D-5) and the delisted check's states.
import { expect, it, vi } from "vitest";
import { regionName, spellInterval } from "../../../src/features/workspace/mount/paneName";
import { createSymbolStatus } from "../../../src/features/workspace/mount/symbolStatus";
import type { Lookup } from "../../../src/features/symbol-search/instrumentIndex";

it("test_region_names_spell_time_intervals_and_add_the_environment_to_order_capable_kinds", () => {
  const codes = ["time:1", "time:15", "time:60", "time:240", "time:D", "tick:500", "time:0"];
  expect(codes.map(spellInterval)).toEqual([
    "1 minute",
    "15 minutes",
    "1 hour",
    "4 hours",
    "1 day",
    "tick:500",
    "time:0",
  ]);
  const f = (symbol: string | null, interval_code: string | null = null) =>
    ({ symbol, interval_code }) as Parameters<typeof regionName>[2];
  expect(regionName("chart", "Chart", f("BTCUSDT", "time:1"), "live")).toBe(
    "Chart, BTCUSDT 1 minute, Live",
  );
  expect(regionName("dom", "DOM", f("BTCUSDT"), "unknown")).toBe("DOM, BTCUSDT, unconfirmed");
  expect(regionName("positions", "Positions", f(null), "testnet")).toBe(
    "Positions, all symbols, Testnet",
  );
  expect(regionName("tape", "Tape", undefined, "demo")).toBe("Tape");
});

it("test_symbol_status_shares_lookups_maps_answers_and_drops_answers_after_stop", async () => {
  const closed = { kind: "status", instrument: { status: "Closed" } };
  const answers: Record<string, object> = {
    BTCUSDT: { kind: "listed" },
    LUNAUSDT: closed,
    PREUSDT: { kind: "status", instrument: { status: "PreLaunch" } },
    GONEUSDT: { kind: "not_listed" },
    ODDUSDT: { kind: "unchecked" },
  };
  const lookup = vi.fn((s: string) =>
    s in answers ? Promise.resolve(answers[s] as Lookup) : Promise.reject(new Error(s)),
  );
  const symbols = createSymbolStatus(lookup);
  const heard = vi.fn();
  symbols.subscribe(heard);
  const all = [...Object.keys(answers), "FAILUSDT"];
  for (const s of [...all, "BTCUSDT"]) symbols.check(s);
  expect(lookup).toHaveBeenCalledTimes(6);
  expect(symbols.get("BTCUSDT")).toBe("checking");
  await vi.waitFor(() => expect(heard).toHaveBeenCalledTimes(6));
  const states = ["listed", "delisted", "listed", "delisted", "unchecked", "unchecked"];
  expect(all.map((s) => symbols.get(s))).toEqual(states);
  let release: (a: Lookup) => void = () => undefined;
  const late = createSymbolStatus(() => new Promise((done) => (release = done)));
  late.check("ETHUSDT");
  late.stop();
  release(closed as Lookup);
  await Promise.resolve();
  expect(late.get("ETHUSDT")).toBe("checking");
});
