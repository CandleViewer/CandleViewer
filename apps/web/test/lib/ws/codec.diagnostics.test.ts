// #4112: every refusal `validateCvwb` can give must pass the fuzz property's check (a known decoder
// diagnostic, support/cvwbDiagnostics). That property runs only in the nightly fuzz project, which
// went red when a decoder gained a diagnostic the list lacked (`heatmap column record_count=2,
// expected 1`). These checks run in the unit project, so such a gap fails the PR that adds it.
import { describe, expect, it } from "vitest";
import { validateCvwb } from "../../../src/lib/ws/protocol/codec";
import { DIAGNOSTIC } from "./support/cvwbDiagnostics";
import { repoFile } from "./support/schemaHarness";

const BODY = /^(?:cvwb|unsupported_body_kind|unsupported_format_version)$/;
const typed = {
  t: "decode_error",
  code: "frame_malformed",
  diagnostic: expect.stringMatching(BODY),
};

describe("validateCvwb's refusals are diagnostics the fuzz property accepts (#4112)", () => {
  type Seed = { name: string; expect: "ok" | "malformed"; hex: string };
  const corpus = JSON.parse(repoFile("tests/fuzz/ws-frames/corpus.json")) as Seed[];

  it.each(corpus.filter((s) => s.expect === "malformed").map((s) => [s.name, s.hex]))(
    "corpus case %s",
    (_name, hex) => {
      const verdict = validateCvwb(Buffer.from(hex, "hex"));
      expect(verdict).toEqual({ ...typed, message: expect.stringMatching(DIAGNOSTIC) });
    },
  );

  it("names the count of a heatmap column that is not one column (the nightly's body)", () => {
    const seed = corpus.find((s) => s.name === "heatmap-record-count-2");
    expect(validateCvwb(Buffer.from(seed?.hex ?? "", "hex"))).toEqual({
      ...typed,
      diagnostic: "cvwb",
      message: "heatmap column record_count=2, expected 1",
    });
  });

  it("every diagnostic the decoders throw is in the list", () => {
    const source = repoFile("packages/protocol/src/runtime/index.ts");
    const text = (lit: string): string => lit.slice(1, -1);
    // `assertFits(count, stride, available, what)` throws `${what}: count=...`: its labels
    const fits = /assertFits\([^;]*,\s*(`[^`]*`|"[^"]*")\s*,?\s*\);/g;
    const labels = [...source.matchAll(fits)].map((m) => text(m[1] ?? ""));
    const thrown = [...source.matchAll(/new BinaryFrameError\(\s*(`[^`]*`|"[^"]*")/g)]
      .map((m) => text(m[1] ?? ""))
      // a decoder's own body_kind check: `validateCvwb` picks the decoder by that body_kind
      .filter((t) => !t.startsWith("expected body_kind="));
    const sample = (t: string): string => t.replace(/\$\{[^}]*\}/g, "7");
    const messages = thrown.flatMap((t) =>
      t.startsWith("${what}") ? labels.map((w) => sample(t.replace("${what}", w))) : [sample(t)],
    );
    expect(labels).toHaveLength(5); // book levels, trades, footprint groups, footprint group, heatmap rows
    expect(thrown.length).toBeGreaterThanOrEqual(16);
    expect(messages.filter((m) => !DIAGNOSTIC.test(m))).toEqual([]);
  });
});
