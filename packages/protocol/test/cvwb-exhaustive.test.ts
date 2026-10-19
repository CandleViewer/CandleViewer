// #415 (E17-X02), SR-155 and SR-128: the deterministic seeds of the CVWB decoder fuzz, run in the unit
// lane (they take about a second): every one of the 24 header bits flipped on every valid corpus seed,
// every truncation length, the header `record_count` at each power of two up to 2^31, and a 256 KiB
// random frame with a valid magic (fixed bytes). Each of the six decoders returns or throws ONLY
// BinaryFrameError, inside a time and an allocation cap (loose: GC is not forced, and this is a PR lane).
// A failure reports only its target and a sha256 digest of the input, as the nightly fuzz does
// (cvwb-fuzz.fuzz.test.ts); with CV_FUZZ_ARTIFACT_DIR set the input is saved there too.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it } from "vitest";
import * as R from "../src/runtime/index.js";

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
const RECORD_COUNT = 12; // offset of the header's u32 `record_count` (cvwb-layout.json)
const MAX_MS = 1000;
const MAX_BYTES = 16 * 1024 * 1024;
const used = (): number => {
  const m = process.memoryUsage();
  return m.heapUsed + m.external; // external: the backing store of a typed array sized from a count
};

const failures: string[] = [];
afterEach(() => void (failures.length = 0));

/** Records a failure as its reason, target and digest alone; the input goes to the artefact dir. */
function report(why: string, target: string, data: Uint8Array): void {
  const digest = createHash("sha256").update("exhaustive:").update(data).digest("hex");
  let label = `${why}: ${target} sha256=${digest}`;
  const dir = process.env["CV_FUZZ_ARTIFACT_DIR"];
  if (dir) {
    try {
      mkdirSync(dir, { recursive: true });
      const input = Buffer.from(data).toString("base64");
      writeFileSync(join(dir, `${target}-${digest}.json`), JSON.stringify({ target, input }));
    } catch (e) {
      label += ` (not saved: ${e instanceof Error ? e.constructor.name : typeof e})`;
    }
  }
  failures.push(label);
}

/** Every decoder on `data`: a typed refusal or a result, in time and without a large allocation. */
function probe(data: Uint8Array): void {
  for (const [name, decode] of DECODERS) {
    const before = used();
    const t0 = performance.now();
    let why = "";
    try {
      decode(data);
    } catch (e) {
      if (!(e instanceof R.BinaryFrameError)) {
        why = `non-typed throw (${e instanceof Error ? e.constructor.name : typeof e})`;
      }
    }
    if (!why && performance.now() - t0 > MAX_MS) why = "decode exceeded time cap";
    if (!why && used() - before > MAX_BYTES) why = "decode exceeded allocation cap";
    if (why) report(why, name, data);
  }
}

it("flipping each header bit of every valid seed is decoded or refused in type", () => {
  expect(VALID.length).toBeGreaterThan(20); // the corpus filter selected seeds
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
