// E24-S05 (#780) BQ 1 (ruled 6612481277): the one mapping from the print's side to the position it closed.
import { describe, expect, it } from "vitest";
import {
  liquidatedSide,
  SIDE_GLYPHS,
  SIDE_WORDS,
} from "../../../../src/features/derivatives/liquidations/side";

describe("liquidatedSide", () => {
  it("reads a sell print as a long liquidated (24 §2.5)", () => {
    expect(liquidatedSide("sell")).toBe("long");
    expect(SIDE_WORDS.long).toBe("Long liquidated");
    expect(SIDE_GLYPHS.long).toBe("▼");
  });

  it("reads a buy print as a short liquidated (22: buy = short liquidated)", () => {
    expect(liquidatedSide("buy")).toBe("short");
    expect(SIDE_WORDS.short).toBe("Short liquidated");
    expect(SIDE_GLYPHS.short).toBe("▲");
  });
});
