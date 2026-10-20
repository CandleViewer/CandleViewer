// #415 (E17-X02), SR-155 and SR-128: the deterministic seeds of the CVWB decoder fuzz, run in the
// unit lane (they take about a second), so on every PR that touches the package: each of the 192
// header bits (24 bytes) flipped on every valid corpus seed, every truncation length, the header
// `record_count` at each power of two up to 2^31, and a 256 KiB random frame with a valid magic
// (fixed bytes). Each of the six decoders returns or throws ONLY BinaryFrameError, inside a time
// and an allocation cap. A failure reports only its target and a sha256 digest of the input
// (support/fuzzReport.ts, pinned by cvwb-fuzz-report.test.ts); with CV_FUZZ_ARTIFACT_DIR set the
// input is saved there too.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it } from "vitest";
import { CVWB_HEADER } from "../src/generated/cvwb/index.js";
import * as R from "../src/runtime/index.js";
import { breach, report } from "./support/fuzzReport.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const corpus = JSON.parse(
  readFileSync(join(HERE, "../../../tests/fuzz/ws-frames/corpus.json"), "utf8"),
) as { expect: string; hex: string }[];
const VALID = corpus
  .filter((s) => s.expect === "ok")
  .map((s) => Uint8Array.from(Buffer.from(s.hex, "hex")));
const DECODERS = Object.entries(R).filter(([name]) => name.startsWith("decode")) as [
  string,
  (view: ArrayBufferView) => unknown,
][];
const RECORD_COUNT = CVWB_HEADER.offsets.recordCount;
// Caps: a trip-wire for a future allocation or loop sized from a count in the input, not a
// measurement. Every count is checked against the buffer first (assertFits, SR-128), so a decode
// here costs next to nothing; the caps sit above a legitimate decode of the largest frame (a valid
// 256 KiB one: about 10 ms and a few MiB).
const CAPS = { ms: 1000, bytes: 16 * 1024 * 1024 };

const failures: string[] = [];
afterEach(() => void (failures.length = 0));

/** Every decoder on `data`: a typed refusal or a result, in time and without a large allocation. */
function probe(data: Uint8Array): void {
  for (const [name, decode] of DECODERS) {
    const why = breach(decode, data, CAPS);
    if (why) failures.push(report(why, name, data, "exhaustive:"));
  }
}

it("flipping each header bit of every valid seed is decoded or refused in type", () => {
  expect(VALID.length).toBeGreaterThan(20); // the corpus filter selected seeds
  expect(DECODERS).toHaveLength(6); // found by name: a renamed decoder must not pass vacuously
  for (const seed of VALID) {
    for (let bit = 0; bit < R.COMMON_HEADER_BYTES * 8; bit++) {
      const data = seed.slice();
      data[bit >> 3] = (data[bit >> 3] ?? 0) ^ (1 << (bit & 7));
      probe(data);
    }
  }
  expect(failures).toEqual([]);
});

it("every truncation of every valid seed is decoded or refused in type", () => {
  for (const seed of VALID) {
    for (let length = 0; length < seed.length; length++) probe(seed.slice(0, length));
  }
  expect(failures).toEqual([]);
});

it("record_count at each power of two up to 2^31 is refused in type, or decoded in bounds", () => {
  for (const seed of VALID) {
    for (let power = 0; power <= 31; power++) {
      const data = seed.slice();
      new DataView(data.buffer).setUint32(RECORD_COUNT, 2 ** power, true);
      probe(data);
    }
  }
  expect(failures).toEqual([]);
});

it("a 256 KiB random frame with a valid magic is refused in type, or decoded in bounds", () => {
  // the bytes are sha256 over fixed labels: the same frame on every run
  const random = Buffer.concat(
    Array.from({ length: 8192 }, (_, i) => createHash("sha256").update(`cvwb-${i}`).digest()),
  );
  // the magic alone, then each decoder's own (format_version, body_kind): the body past the header
  const pairs = [...new Set(VALID.map((s) => `${s[4]},${s[5]}`))].map((p) =>
    p.split(",").map(Number),
  );
  for (const pair of [[], ...pairs]) {
    const data = Uint8Array.from(random);
    new DataView(data.buffer).setUint32(0, R.BINARY_FRAME_MAGIC, true);
    data.set(pair, 4);
    probe(data);
  }
  expect(failures).toEqual([]);
});
