// E11-T04 PR-2 property (AC4; C-38 style: seeded mulberry32 loops, no fast-check): over random
// token objects — slots dropped, values corrupted, extra keys added — `ThemeState.apply` either
// installs a complete theme equal to the parsed input or throws ENGINE_THEME_INVALID naming the
// first bad slot and keeps the previous theme. Never a partial theme.
import { describe, expect, it } from "vitest";
import { mulberry32 } from "../../bench/fixtures/rng.mjs";
import { THEME_SLOTS } from "../../src/theme/slots.js";
import { ThemeIngestError, ThemeState, parseHexColor } from "../../src/theme/ThemeIngest.js";
import { validInput } from "./fixture.js";

const CASES = 500;
const BAD = ["", "#12", "#12345", "red", "#zzzzzz", "#1234567", " #123456"];

// Under a loaded shared runner the 500 cases need more than vitest's 5 s default (C-9.3); the
// assertions are batched into one `expect` per case kind so the loop itself stays cheap.
const SLOW = 20_000;

/** A random accepted hex and its expected bytes (alpha 255 when absent), computed independently. */
function randomHex(rng: () => number): [hex: string, bytes: number[]] {
  const width = [3, 6, 8][Math.floor(rng() * 3)] ?? 6;
  const digits = Array.from({ length: width }, () => Math.floor(rng() * 16));
  const pairs =
    width === 3
      ? digits.map((d) => d * 17)
      : digits.flatMap((d, i) => (i % 2 ? [] : [d * 16 + (digits[i + 1] ?? 0)]));
  const hex = `#${digits.map((d) => d.toString(16)).join("")}`;
  return [rng() < 0.5 ? hex : hex.toUpperCase(), pairs.length === 4 ? pairs : [...pairs, 255]];
}

describe("Property: ingest is all-or-nothing", () => {
  it(
    `${CASES} seeded token objects → a full theme or a named throw, never partial`,
    () => {
      const rng = mulberry32(0x7404);
      const state = new ThemeState();
      const initial = state.apply(validInput());
      const violations: string[] = [];
      let thrown = 0;
      for (let n = 0; n < CASES; n += 1) {
        const colors: Record<string, unknown> = {};
        const expected = new Map<string, number[]>();
        let firstBad: string | null = null;
        for (const slot of THEME_SLOTS) {
          const roll = rng();
          if (roll < 0.01) {
            firstBad ??= slot; // dropped
          } else if (roll < 0.02) {
            firstBad ??= slot;
            colors[slot] = BAD[Math.floor(rng() * BAD.length)];
          } else {
            const [hex, bytes] = randomHex(rng);
            colors[slot] = hex;
            expected.set(slot, bytes);
          }
        }
        if (rng() < 0.3) colors[`color.extra.${n}`] = "not a colour";
        const before = state.current;
        try {
          const result = state.apply(validInput({ colors: colors as Record<string, string> }));
          if (firstBad !== null) violations.push(`#${n}: installed despite bad ${firstBad}`);
          if (state.current !== result) violations.push(`#${n}: result not installed`);
          const keys = Object.keys(result.slots).join();
          if (keys !== THEME_SLOTS.join()) violations.push(`#${n}: slots ${keys}`);
          for (const slot of THEME_SLOTS) {
            const got = result.slots[slot].map((v) => Math.round(v * 255)).join();
            if (got !== expected.get(slot)?.join()) violations.push(`#${n}: ${slot} = ${got}`);
          }
        } catch (e) {
          thrown += 1;
          const key = e instanceof ThemeIngestError ? e.key : String(e);
          if (key !== firstBad) violations.push(`#${n}: threw ${key}, expected ${firstBad}`);
          if (state.current !== before) violations.push(`#${n}: partial install`);
        }
      }
      expect(violations).toEqual([]);
      // Both branches are exercised (about half the cases carry a bad slot).
      expect(thrown).toBeGreaterThan(CASES / 5);
      expect(thrown).toBeLessThan(CASES - CASES / 5);
      expect(initial).not.toBe(state.current);
    },
    SLOW,
  );

  it("hex → rgba is exact on the 8-bit grid", () => {
    const rng = mulberry32(0x7405);
    for (let n = 0; n < CASES; n += 1) {
      const bytes = [0, 1, 2, 3].map(() => Math.floor(rng() * 256));
      const hex = `#${bytes.map((b) => b.toString(16).padStart(2, "0")).join("")}`;
      expect(parseHexColor(hex)?.map((v) => Math.round(v * 255))).toEqual(bytes);
    }
  });
});
