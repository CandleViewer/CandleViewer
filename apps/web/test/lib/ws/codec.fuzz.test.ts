// #415 (E17-X02) slice g: seeded mutation fuzz of the web client's WS codec (SR-155). Invariant:
// `decodeFrame` and `validateCvwb` never throw, stay inside a time and allocation cap, refuse only with
// the typed `frame_malformed`, on text (JSON frames, and the shared CVWB corpus wrapped as `b64`
// data frames) and on binary (tests/fuzz/ws-frames/*.json), every input mutated. Same engine as
// packages/protocol's CVWB fuzz: a seeded PRNG loop, no fuzzing dependency.
// CV_FUZZ_SEED seeds it; CV_FUZZ_SECONDS time-boxes it (else CV_FUZZ_EXAMPLES inputs, default 20 000).
// A failure reports only its target and a sha256 digest of (seed, input); the pair goes to
// CV_FUZZ_ARTIFACT_DIR, which CI uploads only encrypted (fuzz-nightly.yml).
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import * as P from "@candleviewer/protocol";
import { expect, it } from "vitest";
import { decodeFrame, isTopic, validateCvwb } from "../../../src/lib/ws/protocol/codec";
import { MAX_ID_LENGTH } from "../../../src/lib/ws/protocol/frames";
import { checked, kindOf } from "./support/fuzzCaps";

const CORPORA = fileURLToPath(new URL("../../../../../tests/fuzz/ws-frames/", import.meta.url));
const corpus = (file: string): number[][] =>
  (JSON.parse(readFileSync(join(CORPORA, file), "utf8")) as { hex: string }[]).map((s) => [
    ...Buffer.from(s.hex, "hex"),
  ]);
const CVWB = corpus("corpus.json");
const BINARY_SEEDS = [...CVWB, ...corpus("msgpack-client.json")];

const N = Number(process.env["CV_FUZZ_EXAMPLES"] ?? 20_000);
const SECONDS = Number(process.env["CV_FUZZ_SECONDS"] ?? 0);
if (!(Number.isFinite(SECONDS) && SECONDS >= 0)) {
  throw new Error("CV_FUZZ_SECONDS must be a finite number of seconds, 0 or more");
}
const SEED = BigInt(process.env["CV_FUZZ_SEED"] ?? 0xc0ffee); // up to 64 bits
// Per-call caps: a trip-wire for a future allocation or loop sized from a count in the input
// (every count is checked against the buffer first today, SR-128), not a perf assert. The inputs are
// a few KiB, so a legitimate call stays far inside both. GC is not forced, so a heap delta can only
// under-report. A time trip is run once more before it fails (support/fuzzCaps.ts).
const CAPS = { ms: 500, bytes: 64 * 1024 * 1024 };

const FRAMES = [
  '{"t":"auth_ok","id":"c-2","p":{"user_id":"u","session_id":"s","token_expires_at_ms":1,"roles":["owner"],"permissions":[],"account_scope":[],"kill_switch":{"engaged":true,"scope":"accounts","exchange_account_ids":["a1"]}}}',
  // a welcome two limits short: refused as it stands, and edits to its nested fields reach
  // their guards
  '{"t":"welcome","p":{"connection_id":"c","server_time_ms":1,"heartbeat":{"interval_ms":1,"timeout_ms":2},"limits":{"max_subscriptions":200}}}',
  '{"t":"permission_change","p":{"roles":["viewer"],"account_scope":["a1"]}}',
  '{"t":"sub_ok","id":"c-3","p":{"results":[{"ch":"book.BTCUSDT.50","ok":true},{"ch":"orders","ok":false}]}}',
  '{"t":"unsub_ok","id":"c-4","p":{"results":[{"ch":"orders","ok":true}]}}',
  '{"t":"ctl_ok","id":"c-5","p":{"effective":{"time_bucket_ms":1000}}}',
  '{"t":"revoked","ch":"orders","p":{"reason":"grant_withdrawn","message":"m","resubscribe_allowed":false}}',
  '{"t":"err","id":"c-6","ch":"orders","p":{"code":"account_scope_denied","message":"m"}}',
  '{"t":"bye","p":{"code":4429,"reason":"client_rate_limited","message":"m"}}',
  '{"t":"ping","id":"s-1","p":{"server_ms":1}}',
  '{"t":"pong","id":"c-7"}',
  `{"t":"snap","id":"set-7","ch":"book.BTCUSDT.50","s":null,"ts":1,"p":{"levels":[]},"meta":{"reason":"initial","source":"live","previous_seq":null,"include_delta":false,"spec_hash":"${"a".repeat(64)}"}}`,
  '{"t":"d","ch":"book.BTCUSDT.50","s":2,"ts":2,"rs":"bb000000-0000-4000-8000-000000000001","sp":"0123456789abcdef","p":{}}',
];
/** The corpus frames as `b64` data frames: the text path ends in `validateCvwb` too. */
const wrap = (bytes: number[], i: number): string =>
  JSON.stringify({
    ...(i % 2 === 0 ? { t: "d", s: i } : { t: "snap", id: "set-1", s: null }),
    ...{ ch: "book.BTCUSDT.50", ts: 1, e: "b64", p: Buffer.from(bytes).toString("base64") },
  });
const TEXT_SEEDS = [...FRAMES, ...CVWB.map(wrap)];

const units = (s: string): number[] => Array.from({ length: s.length }, (_, i) => s.charCodeAt(i));
const le32 = (v: number): number[] => [v, v >>> 8, v >>> 16, v >>> 24].map((b) => b & 255);
const BYTE_TOKENS = [0, 1, 2, 0x7fffffff, 0x80000000, 0xffffffff, 0xfffffffe].map(le32);
const TEXT_TOKENS = String.raw`{"__proto__":{"polluted":1}} 1e999 \ud800 \u0000 null -`
  .split(" ")
  .concat("[".repeat(5000))
  .map(units);
const HOSTILE: unknown[] = JSON.parse(
  '[null,true,0,-1,1.5,9007199254740992,1e21,"",[],{},[[]],"__proto__","constructor","d","snap","err"]',
);
HOSTILE.push(undefined, "x".repeat(65), "m".repeat(1001), "\u0000\ud800");
const DECODERS = Object.entries(P)
  .filter(([name]) => name.startsWith("decode"))
  .map(([, decode]) => decode as (view: ArrayBufferView) => unknown);
const KINDS =
  /^(auth_ok|permission_change|sub_ok|unsub_ok|ctl_ok|revoked|err|bye|welcome|ping|pong|snap|d)$/;

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

/** Edits of a list of bytes (`bits` 8) or UTF-16 units (16): flip, truncate, extend, set, splice a token. */
function mutate(seed: number[], bits: number, tokens: number[][], rnd: () => number): number[] {
  const int = (n: number): number => Math.floor(rnd() * n);
  const out = [...seed];
  for (let ops = 1 + int(6); ops > 0; ops--) {
    const at = int(out.length + 1);
    const kind = int(5);
    const token = tokens[int(tokens.length)] ?? [];
    if (kind === 0) out[at] = (out[at] ?? 0) ^ (1 << int(bits));
    else if (kind === 1) out.length = at;
    else if (kind === 2) out.push(...new Array<number>(int(65)).fill(int(2 ** bits)));
    else if (kind === 3) out[at] = int(2 ** bits);
    else out.splice(at, Math.min(token.length, 4), ...token);
  }
  return out;
}

/** The frame with about one node in ten replaced by a hostile value (or dropped), or no frame at all. */
function mutateJson(seed: string, rnd: () => number): string {
  const pick = (): unknown => structuredClone(HOSTILE[Math.floor(rnd() * HOSTILE.length)]);
  if (rnd() < 1 / 16) return JSON.stringify(pick() ?? null);
  return JSON.stringify(JSON.parse(seed), (key, value) => (key && rnd() < 0.1 ? pick() : value));
}

/** One input: its canonical bytes name it in a report (text as UTF-16LE, so lone surrogates survive). */
interface Case {
  readonly form: "text" | "bytes";
  readonly canon: Buffer;
  readonly arg: unknown;
}
const textCase = (s: string): Case => ({ form: "text", canon: Buffer.from(s, "utf16le"), arg: s });
const bytesCase = (b: Uint8Array, arg: unknown = b): Case => ({
  form: "bytes",
  canon: Buffer.from(b),
  arg,
});

/** Fails with the target and the digest alone; the (seed, input) pair goes to the artefact dir. */
function fail(why: string, target: string, c: Case): never {
  const digest = createHash("sha256").update(`${SEED}:${c.form}:`).update(c.canon).digest("hex");
  let label = `${why}: ${target} sha256=${digest}`;
  const dir = process.env["CV_FUZZ_ARTIFACT_DIR"];
  if (dir) {
    try {
      mkdirSync(dir, { recursive: true });
      const input = c.canon.toString("base64");
      const record = JSON.stringify({ seed: String(SEED), target, form: c.form, input });
      writeFileSync(join(dir, `${target}-${digest}.json`), record);
    } catch (e) {
      label += ` (not saved: ${kindOf(e)})`;
    }
  }
  throw new Error(label);
}

/** One call of a target: a throw, a long run, an allocation jump or a touch of the prototype fails. */
function run<T>(target: string, c: Case, call: () => T): T {
  const r = checked(call, CAPS);
  if (!r.ok) return fail(r.why, target, c);
  if (Object.keys(Object.prototype).length > 0) fail("prototype touched", target, c);
  return r.out;
}

const isRec = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const WIRE = ["envelope", "payload"]; // what `decodeFrame` refuses with; `validateCvwb`'s are below
const BODY = ["cvwb", "unsupported_body_kind", "unsupported_format_version"];
const INT = String.raw`\d+`; // a header integer
const FITS = String.raw`count=${INT} x ${INT} bytes exceeds the ${INT} bytes left in the buffer`;
/**
 * What `validateCvwb` may say: the decoders' own diagnostics (src/runtime/index.ts), which are fixed
 * words and header integers, never payload bytes, and the codec's fallback for an untyped throw.
 */
const DIAGNOSTICS = [
  String.raw`binary frame too short for the ${INT}-byte common header \(got ${INT} bytes\)`,
  String.raw`bad magic 0x[0-9a-f]+, expected 0x[0-9a-f]+ \("CVWB"\)`,
  String.raw`unknown body_kind ${INT}`,
  String.raw`unsupported \(body_kind=${INT}, format_version=${INT}\); expected format_version ${INT}`,
  String.raw`(?:book levels|trades|footprint groups|footprint group ${INT}|heatmap rows): ${FITS}`,
  String.raw`(?:book|trade|bar) record ${INT} runs past the buffer \(record_count=${INT}\)`,
  String.raw`footprint group ${INT} prefix runs past the buffer \(record_count=${INT}\)`,
  String.raw`footprint cell ${INT} in group ${INT} runs past the buffer \(cell_count=${INT}\)`,
  String.raw`heatmap row ${INT} runs past the buffer \(row_count=${INT}\)`,
  String.raw`invalid (?:book|trade) side byte ${INT} at record ${INT}`,
  String.raw`book snapshot missing its ${INT}-byte xu/xseq trailer`,
  String.raw`bars body is ${INT} bytes, expected ${INT} for record_count=${INT}`,
  "heatmap column body shorter than its fixed prefix",
  "binary body is undecodable",
];
const DIAGNOSTIC = new RegExp(`^(?:${DIAGNOSTICS.join("|")})$`);

/**
 * A typed `frame_malformed` whose message is safe to log: a `decodeFrame` refusal is plain words, a
 * `validateCvwb` one is a known decoder diagnostic.
 */
function isTypedMalformed(r: unknown, diagnostics: string[]): boolean {
  if (!isRec(r)) return false;
  const { t, code, diagnostic, message, ch, id } = r;
  if (t !== "decode_error" || code !== "frame_malformed") return false;
  if (typeof diagnostic !== "string" || !diagnostics.includes(diagnostic)) return false;
  const text = typeof message === "string" ? message : "";
  const shape = WIRE.includes(diagnostic) ? /^[\w. -]{1,80}$/ : DIAGNOSTIC;
  if (text.length > 200 || !shape.test(text)) return false;
  return (
    (ch === undefined || isTopic(ch)) &&
    (id === undefined || (typeof id === "string" && id.length <= MAX_ID_LENGTH))
  );
}

/** `validateCvwb` accepts exactly what one of the protocol decoders accepts, and refuses in type. */
function checkCvwb(c: Case): void {
  const arg = c.arg as ArrayBuffer | ArrayBufferView;
  const verdict: unknown = run("validateCvwb", c, () => validateCvwb(arg));
  if (!isRec(verdict)) fail("not a verdict", "validateCvwb", c);
  const view = ArrayBuffer.isView(arg) ? arg : new Uint8Array(arg);
  const accepted = DECODERS.some((decode) => {
    try {
      decode(view);
      return true;
    } catch {
      return false;
    }
  });
  if ("ok" in verdict !== accepted) fail("verdict differs from the decoders", "validateCvwb", c);
  if (!("ok" in verdict) && !isTypedMalformed(verdict, BODY)) fail("not typed", "validateCvwb", c);
}

const timeout = SECONDS > 0 ? (SECONDS + 120) * 1000 : 600_000;
const box = SECONDS > 0 ? `${SECONDS} s` : `${N} inputs`;
const title = `decodeFrame and validateCvwb refuse only with frame_malformed over ${box}`;
// A box of 60 s or more must hand the event loop back now and then: while the loop holds it,
// vitest's worker-to-runner RPC times out ("Timeout calling onTaskUpdate", and the run exits 1).
const YIELD_EVERY = 5_000;
it(title, { timeout }, async () => {
  expect(DECODERS).toHaveLength(6); // found by name: a renamed decoder must not pass vacuously
  // the digest takes the whole seed; the PRNG state is folded from it
  const rnd = prng(Number(BigInt.asUintN(32, SEED ^ (SEED >> 32n))));
  const pick = <T>(list: readonly T[]): T => list[Math.floor(rnd() * list.length)] as T;
  const end = performance.now() + SECONDS * 1000;
  let runs = 0;
  for (let i = 0; SECONDS > 0 ? performance.now() < end : i < N; i++, runs++) {
    if (runs % YIELD_EVERY === 0) await new Promise<void>((resolve) => setImmediate(resolve));
    if (rnd() < 0.5) {
      const bytes = Uint8Array.from(mutate(pick(BINARY_SEEDS), 8, BYTE_TOKENS, rnd));
      const c = bytesCase(bytes, rnd() < 0.5 ? bytes : bytes.slice().buffer);
      const refused = run("decodeFrame", c, () => decodeFrame(c.arg)); // binary on cv.v1.json
      if (!isTypedMalformed(refused, WIRE)) fail("binary message not refused", "decodeFrame", c);
      checkCvwb(c);
      continue;
    }
    const seed = pick(TEXT_SEEDS);
    const edited = String.fromCharCode(...mutate(units(seed), 16, TEXT_TOKENS, rnd));
    const c = textCase(rnd() < 0.5 ? edited : mutateJson(seed, rnd));
    const frame: unknown = run("decodeFrame", c, () => decodeFrame(c.arg));
    if (isTypedMalformed(frame, WIRE)) continue;
    if (!isRec(frame)) fail("not a frame", "decodeFrame", c);
    const { t, ch, size, body } = frame;
    const data = t === "snap" || t === "d";
    const sound = KINDS.test(String(t)) && (!data || (isTopic(ch) && size === c.canon.length / 2));
    if (!sound) fail("neither a frame nor a typed refusal", "decodeFrame", c);
    if (data && isRec(body) && body["e"] === "b64") {
      checkCvwb(bytesCase(new Uint8Array(body["bytes"] as ArrayBuffer), body["bytes"]));
    }
  }
  expect(runs).toBeGreaterThan(0); // a malformed time box or count must not pass by running nothing
});
