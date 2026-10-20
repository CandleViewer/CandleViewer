// E17-T02 part B: nightly mutation fuzz of the TS CVWB decoders (SR-155), seeded from
// tests/fuzz/ws-frames/corpus.json. Invariant: every decoder returns or throws ONLY
// BinaryFrameError. N via CV_FUZZ_EXAMPLES (default 20 000), seed via CV_FUZZ_SEED; CV_FUZZ_SECONDS
// (> 0) time-boxes the mutation loop instead. The deterministic seeds (every header bit, every
// truncation, every power-of-two count, a 256 KiB frame) are cvwb-exhaustive.test.ts, in the unit lane.
// A failure reports only its target and a sha256 digest of (seed, input), as the Python suite does:
// the pair goes to CV_FUZZ_ARTIFACT_DIR, which CI uploads only encrypted (fuzz-nightly.yml).
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { performance } from "node:perf_hooks";
import {
  BinaryFrameError,
  decodeBars,
  decodeBookDelta,
  decodeBookSnapshot,
  decodeFootprint,
  decodeHeatmapColumn,
  decodeTrades,
} from "../src/runtime/index.js";
import { breach, report, untyped } from "./support/fuzzReport.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const corpus = JSON.parse(
  readFileSync(join(HERE, "../../../tests/fuzz/ws-frames/corpus.json"), "utf8"),
) as { name: string; hex: string }[];
const SEEDS = corpus.map((s) => Uint8Array.from(Buffer.from(s.hex, "hex")));
const N = Number(process.env["CV_FUZZ_EXAMPLES"] ?? 20_000);
const SECONDS = Number(process.env["CV_FUZZ_SECONDS"] ?? 0);
if (!(Number.isFinite(SECONDS) && SECONDS >= 0)) {
  throw new Error("CV_FUZZ_SECONDS must be a finite number of seconds, 0 or more");
}
const BOX = SECONDS > 0 ? `${SECONDS} s of` : String(N);
const TIMEOUT = SECONDS > 0 ? (SECONDS + 120) * 1000 : 600_000;
const SEED = BigInt(process.env["CV_FUZZ_SEED"] ?? 0xc0ffee); // up to 64 bits
// Per-decode caps: a trip-wire for a future allocation or loop sized from a count in the input,
// not a perf assert. Inputs are <= ~300 B, so 16 MiB or 50 ms means a count sized it; the targeted
// SR-128 test below is the precise check.
const CAPS = { ms: 50, bytes: 16 * 1024 * 1024 };
const INTERESTING = [0, 1, 2, 0x7fffffff, 0x80000000, 0xffffffff, 0xfffffffe];
const DECODERS = [
  decodeBookSnapshot,
  decodeBookDelta,
  decodeTrades,
  decodeBars,
  decodeFootprint,
  decodeHeatmapColumn,
];

/** mulberry32: small seeded PRNG so a failing run is reproducible. */
function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function mutate(seed: Uint8Array, rnd: () => number): Uint8Array {
  const int = (n: number): number => Math.floor(rnd() * n);
  let buf = Uint8Array.from(seed);
  for (let ops = 1 + int(6); ops > 0; ops--) {
    const kind = int(5);
    if (kind === 1) {
      buf = buf.slice(0, int(buf.length + 1));
    } else if (kind === 3) {
      buf = Uint8Array.from([...buf, ...new Uint8Array(int(65)).fill(int(256))]);
    } else if (buf.length === 0) {
      continue;
    } else if (kind === 0) {
      const at = int(buf.length);
      buf[at] = (buf[at] ?? 0) ^ (1 << int(8));
    } else if (kind === 2) {
      buf[int(buf.length)] = int(256);
    } else if (buf.length >= 4) {
      new DataView(buf.buffer).setUint32(int(buf.length - 3), INTERESTING[int(7)] ?? 0, true);
    }
  }
  return buf;
}

/** Fails with the target and the digest alone; the (seed, input) pair goes to the artefact dir. */
function fail(why: string, decode: { name: string }, data: Uint8Array): never {
  throw new Error(report(why, decode.name, data, `${SEED}:`, { seed: String(SEED) }));
}

const TITLE = `decoders throw only BinaryFrameError over ${BOX} mutated inputs`;
// A box of 60 s or more must hand the event loop back now and then: while the loop holds it,
// vitest's worker-to-runner RPC times out ("Timeout calling onTaskUpdate", and the run exits 1).
const YIELD_EVERY = 5_000;
it(TITLE, { timeout: TIMEOUT }, async () => {
  // the digest takes the whole seed; the PRNG state is folded from it
  const rnd = prng(Number(BigInt.asUintN(32, SEED ^ (SEED >> 32n))));
  const end = performance.now() + SECONDS * 1000;
  let runs = 0;
  for (let i = 0; SECONDS > 0 ? performance.now() < end : i < N; i++, runs++) {
    if (runs % YIELD_EVERY === 0) await new Promise<void>((resolve) => setImmediate(resolve));
    const data = mutate(SEEDS[Math.floor(rnd() * SEEDS.length)] ?? new Uint8Array(0), rnd);
    for (const decode of DECODERS) {
      const why = breach(decode, data, CAPS);
      if (why) fail(why, decode, data);
    }
  }
  expect(runs).toBeGreaterThan(0); // a malformed time box or count must not pass by running nothing
});

// SR-128 (targeted): a wire count that cannot fit must be rejected UP FRONT by assertFits ("exceeds"),
// before any per-record work. The per-record bounds checks in each loop would otherwise mask a
// removed pre-check (they throw "runs past the buffer"), so the message is the observable.
const VALUES = [0, 1, 0xffff, 0x7fffffff, 0xffffffff];
interface Site {
  decode: (b: Uint8Array) => unknown;
  kinds: number[];
  offset: number; // u32 count field
  stride: number;
  base: number; // bytes before the first counted record
  minLen: number;
}
const SITES: Site[] = [
  { decode: decodeBookSnapshot, kinds: [1], offset: 12, stride: 17, base: 24, minLen: 24 },
  { decode: decodeBookDelta, kinds: [2], offset: 12, stride: 17, base: 24, minLen: 24 },
  { decode: decodeTrades, kinds: [3], offset: 12, stride: 22, base: 24, minLen: 24 },
  // footprint v2 (#2529): group count x 28-byte prefix; first group's cell_count at 24 + 20.
  { decode: decodeFootprint, kinds: [5], offset: 12, stride: 28, base: 24, minLen: 24 },
  { decode: decodeFootprint, kinds: [5], offset: 44, stride: 33, base: 52, minLen: 52 },
  { decode: decodeHeatmapColumn, kinds: [6], offset: 44, stride: 16, base: 48, minLen: 48 },
];

it("every wire count that cannot fit is rejected up front (SR-128), per site and seed", () => {
  let probes = 0;
  for (const site of SITES) {
    for (const seed of SEEDS) {
      if (seed.length < site.minLen || seed.length < site.offset + 4) continue;
      if (!site.kinds.includes(seed[5] ?? 0)) continue;
      try {
        site.decode(seed);
      } catch {
        continue; // only seeds that are valid as declared
      }
      const avail = seed.length - site.base;
      const fit = Math.floor(avail / site.stride);
      for (const value of [...VALUES, fit + 1, fit + 2]) {
        if (value * site.stride <= avail) continue;
        const data = Uint8Array.from(seed);
        new DataView(data.buffer).setUint32(site.offset, value >>> 0, true);
        probes++;
        let msg = "";
        try {
          site.decode(data);
        } catch (e) {
          if (!(e instanceof BinaryFrameError)) fail(untyped(e), site.decode, data);
          msg = e.message;
        }
        if (!/exceeds/.test(msg)) fail("count not rejected up front", site.decode, data);
      }
    }
  }
  expect(probes).toBeGreaterThan(30);
});
