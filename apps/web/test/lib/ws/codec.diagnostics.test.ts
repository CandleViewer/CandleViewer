// #4112: every refusal `validateCvwb` can give must pass the fuzz property's check (a known decoder
// diagnostic, support/cvwbDiagnostics). That property runs only in the nightly fuzz project, which
// went red when a decoder gained a diagnostic the list lacked (`heatmap column record_count=2,
// expected 1`). These checks run in the unit project, so such a gap fails the PR that adds it.
import { describe, expect, it } from "vitest";
import { validateCvwb } from "../../../src/lib/ws/protocol/codec";
import { BODY, DIAGNOSTIC } from "./support/cvwbDiagnostics";
import { repoFile } from "./support/schemaHarness";

const typed = {
  t: "decode_error",
  code: "frame_malformed",
  diagnostic: expect.stringMatching(new RegExp(`^(?:${BODY.join("|")})$`)),
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
    expect(seed).toBeDefined();
    expect(validateCvwb(Buffer.from(seed?.hex ?? "", "hex"))).toEqual({
      ...typed,
      diagnostic: "cvwb",
      message: "heatmap column record_count=2, expected 1",
    });
  });

  it("every diagnostic the decoders throw is in the list", () => {
    const source = repoFile("packages/protocol/src/runtime/index.ts");
    const text = (lit: string): string => lit.slice(1, -1);
    const count = (re: RegExp): number => (source.match(re) ?? []).length;
    // Every construction is read as one literal message: a variable, a concatenation or the
    // `FrameMalformedError` alias fails here instead of going unchecked.
    const read = [...source.matchAll(/new BinaryFrameError\(\s*(`[^`]*`|"[^"]*")\s*[,)]/g)].map(
      (m) => text(m[1] ?? ""),
    );
    expect(read).toHaveLength(count(/new (?:BinaryFrameError|FrameMalformedError)\(/g));
    // a decoder's own body_kind check (6): `validateCvwb` picks the decoder by that body_kind
    const thrown = read.filter((t) => !t.startsWith("expected body_kind="));
    expect(read.length - thrown.length).toBe(6);
    // `assertFits(count, stride, available, what)` throws `${what}: count=...`: every call's label
    const fits = /assertFits\([^;]*,\s*(`[^`]*`|"[^"]*")\s*,?\s*\);/g;
    const labels = [...source.matchAll(fits)].map((m) => text(m[1] ?? ""));
    expect(labels).toHaveLength(count(/(?<!function )assertFits\(/g));
    // each `${...}` stands for a number (a header field, an index, a size); the corpus cases above
    // check the real values of the diagnostics they reach
    const sample = (t: string): string => t.replace(/\$\{[^}]*\}/g, "7");
    const messages = thrown.flatMap((t) =>
      t.startsWith("${what}") ? labels.map((w) => sample(t.replace("${what}", w))) : [sample(t)],
    );
    expect(messages.filter((m) => !DIAGNOSTIC.test(m))).toEqual([]);
  });
});
