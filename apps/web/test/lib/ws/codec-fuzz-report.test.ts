// A failing web fuzz case reports its target and a digest, never its input or its seed (#415,
// E17-X02). The real fuzz project runs in a child vitest (CI=true) against a codec that breaks its
// contract on one target: it throws an untyped error that quotes the text or the bytes it was given.
// Everything the child printed is then read: no form of the failing input may be in it, nor the
// seed, nor the error the codec threw; the digest must be; and the local file holds the seed and the
// input. As packages/protocol/test/cvwb-fuzz-report.test.ts does for the CVWB decoders.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "../../..");
const VITEST = join(
  dirname(createRequire(import.meta.url).resolve("vitest/package.json")),
  "vitest.mjs",
);
const SEED = 17391827364509182736n;
const CODEC = join(PKG, "src", "lib", "ws", "protocol", "codec.ts");
// The planted target throws on any text of 40 characters or more, or any 24 bytes or more, and
// leaves the input and the target in a log: what the real run printed is compared with it.
const PLANTED = `import { appendFileSync } from "node:fs";
import * as real from ${JSON.stringify(CODEC)};
export * from ${JSON.stringify(CODEC)};
function plant(target, data) {
  const text = typeof data === "string";
  const bytes = text ? Buffer.from(data, "utf16le")
    : ArrayBuffer.isView(data) ? Buffer.from(data.buffer, data.byteOffset, data.byteLength) : Buffer.from(data);
  const form = text ? "text" : "bytes";
  appendFileSync(process.env.PLANTED_LOG, JSON.stringify({ target, form, canon: bytes.toString("base64") }) + "\\n");
  throw new Error(text ? data : \`\${bytes.toString("hex")} \${bytes.toString("base64")} [\${[...bytes].join(", ")}]\`);
}
export function decodeFrame(data) {
  if (process.env.PLANTED_TARGET === "decodeFrame" && typeof data === "string" && data.length >= 40) plant("decodeFrame", data);
  return real.decodeFrame(data);
}
export function validateCvwb(buf) {
  if (process.env.PLANTED_TARGET === "validateCvwb" && buf.byteLength >= 24) plant("validateCvwb", buf);
  return real.validateCvwb(buf);
}
`;

let scratch = "";
afterEach(() => {
  if (scratch) rmSync(scratch, { recursive: true, force: true });
});

/** The ways a report could print an input (whitespace removed, as the report is). */
function forms(entry: { form: string; canon: Buffer }): string[] {
  const { canon } = entry;
  if (entry.form === "text") return [canon.toString("utf16le")];
  const b64 = canon.toString("base64");
  return [
    canon.toString("hex"),
    canon.toString("hex").toUpperCase(),
    b64,
    b64.replace(/=+$/, ""),
    canon.toString("base64url"),
    [...canon].join(","),
  ];
}

it.each(["decodeFrame", "validateCvwb"])(
  "a failing %s input reaches no report",
  { timeout: 60_000 },
  (target) => {
    scratch = mkdtempSync(join(tmpdir(), "cv-web-fuzz-report-"));
    const planted = join(scratch, "planted.mjs");
    const config = join(scratch, "vitest.config.mjs");
    writeFileSync(planted, PLANTED);
    writeFileSync(
      config,
      `import real from ${JSON.stringify(join(PKG, "vitest.config.mjs"))};
export default {
  ...real,
  root: ${JSON.stringify(PKG)},
  cacheDir: ${JSON.stringify(join(scratch, ".vite"))},
  resolve: { alias: [...real.resolve.alias, { find: "../../../src/lib/ws/protocol/codec", replacement: ${JSON.stringify(planted)} }] },
};`,
    );
    const env = { ...process.env }; // without this run's own vitest and coverage settings
    for (const name of Object.keys(env)) {
      if (name.startsWith("VITEST") || name === "NODE_V8_COVERAGE") delete env[name];
    }
    Object.assign(env, {
      CI: "true",
      NO_COLOR: "1",
      CV_FUZZ_EXAMPLES: "200",
      CV_FUZZ_SEED: String(SEED),
      CV_FUZZ_ARTIFACT_DIR: join(scratch, "out"),
      PLANTED_LOG: join(scratch, "seen.jsonl"),
      PLANTED_TARGET: target,
    });
    const args = [VITEST, "run", "--config", config, "--project", "fuzz"];
    const done = spawnSync(process.execPath, args, {
      cwd: PKG,
      env,
      encoding: "utf8",
      timeout: 55_000,
    });
    const out = done.stdout + done.stderr;
    expect(done.status, out).toBe(1);
    const seen = readFileSync(join(scratch, "seen.jsonl"), "utf8")
      .trim()
      .split("\n")
      .map((line) => {
        const { form, canon } = JSON.parse(line) as { form: string; canon: string };
        return { form, canon: Buffer.from(canon, "base64") };
      });
    const digestOf = (e: { form: string; canon: Buffer }): string =>
      createHash("sha256").update(`${SEED}:${e.form}:`).update(e.canon).digest("hex");
    expect(out.match(/^ FAIL /gm)?.length).toBe(1);
    expect(out).not.toContain("planted.mjs"); // nor the error the codec threw
    expect(out).not.toContain(String(SEED)); // nor the seed (it stays in the failure file)
    // the failure line is a reason, then the target and the digest: nothing else
    const reported = [...out.matchAll(/^Error: [\w ()-]+: (\w+) sha256=([0-9a-f]{64})$/gm)];
    expect(reported.length, out).toBe(1);
    const [, name, digest] = reported[0] ?? [];
    const hit = seen.find((e) => digestOf(e) === digest);
    expect(name).toBe(target);
    expect(hit, "the digest names a planted input").toBeDefined();
    const saved = readFileSync(join(scratch, "out", `${target}-${digest}.json`), "utf8");
    const input = hit?.canon.toString("base64");
    expect(JSON.parse(saved)).toEqual({ seed: String(SEED), target, form: hit?.form, input });
    const flat = out.replace(/\s+/g, "");
    for (const entry of seen) {
      const w = entry.form === "text" ? 24 : 12; // 12 characters or 12 bytes
      for (const slice of [entry.canon, entry.canon.subarray(0, w), entry.canon.subarray(-w)]) {
        const found = forms({ form: entry.form, canon: slice }).filter((form) =>
          flat.includes(form.replace(/\s+/g, "")),
        );
        expect(found).toEqual([]);
      }
    }
  },
);
