import { describe, expect, it } from "vitest";

// Plain .mjs tooling lives outside the package; load it untyped.
const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as any; // eslint-disable-line @typescript-eslint/no-explicit-any

// #4639: tritanopia uses Machado, Oliveira & Fernandes (2009) at severity 1.0 in
// linear RGB; the pinned values match docs/design/_tools/e12_d06_series_audit.py.
describe("CVD simulation pins (#4639)", () => {
  it.each([
    ["#FF0000", "#FF000F"],
    ["#00FF00", "#00F7D9"],
    ["#0000FF", "#006B96"],
    ["#FFFF00", "#FFEED9"],
  ])("tritanopia maps %s to %s", (input, expected) => {
    expect(math.simulateCvd(input, "tritanopia")).toBe(expected);
  });

  it("tritanopia does not collapse red and green onto R = G", () => {
    for (const hex of ["#FF0000", "#00FF00"]) {
      const sim = math.simulateCvd(hex, "tritanopia") as string;
      expect(sim.slice(1, 3)).not.toBe(sim.slice(3, 5));
    }
    const de = math.deltaE76(
      math.simulateCvd("#FF0000", "tritanopia"),
      math.simulateCvd("#00FF00", "tritanopia"),
    );
    expect(de).toBeGreaterThan(math.CVD_JND_FLOOR);
  });

  it("tritanopia preserves greys", () => {
    expect(math.simulateCvd("#808080", "tritanopia")).toBe("#808080");
  });

  it.each([
    ["#2EBD59", "protanopia", "#B4B458"],
    ["#2EBD59", "deuteranopia", "#A3A35D"],
    ["#E5484D", "protanopia", "#6B6B4E"],
    ["#E5484D", "deuteranopia", "#8F8F44"],
  ])("keeps the Brettel/Vienot path: %s under %s is %s", (input, deficiency, expected) => {
    expect(math.simulateCvd(input, deficiency)).toBe(expected);
  });

  it("rejects an unknown deficiency", () => {
    expect(() => math.simulateCvd("#FF0000", "achromatopsia")).toThrow(/A11Y-C000/);
  });
});
