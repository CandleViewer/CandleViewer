// E17-T04 S2 (C10, S1 lens C): a CVWB decoder that throws something other than `BinaryFrameError`
// (a `RangeError` from a DataView read, say) still ends as a typed, non-fatal `frame_malformed`:
// `validateCvwb` never throws on untrusted bytes. The real decoders guard every read, so no input
// reaches that branch through them; one decoder is replaced here to pin it.
import { describe, expect, it, vi } from "vitest";
import { validateCvwb } from "../../../src/lib/ws/protocol/codec";
import { bookDelta } from "./support/cvwb";

vi.mock("@candleviewer/protocol", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  decodeBookDelta: () => {
    throw new RangeError("Offset is outside the bounds of the DataView");
  },
}));

describe("validateCvwb with a decoder that throws a RangeError", () => {
  it("returns a typed frame_malformed and does not repeat the engine's message", () => {
    const result = validateCvwb(bookDelta());
    expect(result).toMatchObject({
      t: "decode_error",
      code: "frame_malformed",
      diagnostic: "cvwb",
    });
    expect(JSON.stringify(result)).not.toContain("DataView");
  });
});
