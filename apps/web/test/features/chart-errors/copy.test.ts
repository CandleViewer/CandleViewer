// E11-T05 (BQ-91, #2701 ledger A51): the no-WebGL2 body is built from the reduced list.
import { describe, expect, it } from "vitest";
import { noWebgl2Body, REDUCED_FRAGMENTS } from "../../../src/features/chart-errors/copy";
import { REDUCED_ORDER, type ReducedCapability } from "../../../src/features/chart-errors/state";

const WORKS = "Basic rendering is on: candles, lines, axes, the crosshair and drawings work";
const END = ". Everything else in the workspace is unaffected.";

describe("noWebgl2Body", () => {
  it("footprint-text and heatmap give E11-D04 §19's sentence verbatim", () => {
    expect(noWebgl2Body(["footprint-text", "heatmap"])).toBe(
      "Basic rendering is on: candles, lines, axes, the crosshair and drawings work; footprint cells show colour only and the heatmap is off. Everything else in the workspace is unaffected.",
    );
  });

  it("all five name every fragment in the vocabulary order, joined without a serial comma", () => {
    expect(noWebgl2Body(REDUCED_ORDER)).toBe(
      `${WORKS}; footprint cells show colour only, the heatmap is off, bubbles are off, profile shading is off and GPU effects are off${END}`,
    );
  });

  it.each([
    ["footprint-text", "footprint cells show colour only"],
    ["heatmap", "the heatmap is off"],
    ["bubbles", "bubbles are off"],
    ["profile-shading", "profile shading is off"],
    ["gpu-effects", "GPU effects are off"],
  ] as const)("%s alone names the A51 / §19 fragment %j", (value, fragment) => {
    expect(REDUCED_FRAGMENTS[value]).toBe(fragment);
    expect(noWebgl2Body([value])).toBe(`${WORKS}; ${fragment}${END}`);
  });

  it("an empty list keeps the frame; a value without a fragment is not named", () => {
    expect(noWebgl2Body([])).toBe(`${WORKS}${END}`);
    const unknown = ["sparkles", "bubbles"] as unknown as ReducedCapability[];
    expect(noWebgl2Body(unknown)).toBe(`${WORKS}; bubbles are off${END}`);
  });

  // All 32 subsets, the expected string built here from §19's frame, not from the builder.
  const subsets = Array.from({ length: 32 }, (_, mask) =>
    REDUCED_ORDER.filter((_, i) => (mask & (1 << i)) !== 0),
  );
  const join = (parts: readonly string[]): string =>
    parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
  it.each(subsets.map((sub) => [sub.join(" + ") || "(empty)", sub] as const))(
    "subset %s: the frame, fragments in vocabulary order, no serial comma",
    (_, sub) => {
      const lost = join(sub.map((c) => REDUCED_FRAGMENTS[c]));
      // The builder keeps the frame for []; the state model never passes one (reducedOf).
      expect(noWebgl2Body(sub)).toBe(lost === "" ? `${WORKS}${END}` : `${WORKS}; ${lost}${END}`);
    },
  );
});
