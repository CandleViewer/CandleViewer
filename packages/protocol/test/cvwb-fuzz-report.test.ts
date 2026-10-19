// A failing fuzz case reports its target and a digest, never its input or its seed (#415,
// E17-X02). The real fuzz project runs in a child vitest, under CI, against decoders that break
// their contract on any input of 24 bytes or more and quote the input in the breakage. Everything
// the child printed is then read: no form of a failing input may be in it (hex, base64, decimals, a
// window of any of them), nor the seed, nor the error the decoder threw; the digest must be; and
// the local file holds the seed and the input. The seed is 64 bits wide: the digest and the file
// take all of it.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..");
const VITEST = join(
  dirname(createRequire(import.meta.url).resolve("vitest/package.json")),
  "vitest.mjs",
);
const SEED = 17391827364509182736n;
const RUNTIME = join(PKG, "src", "runtime", "index.ts");
// decodeBars breaks on every input (the mutation loop); decodeBookDelta only on a count past 1 000
// (the targeted count probes), where it should refuse. Both throw an untyped error that quotes
// the input, and leave the input and the decoder in the log.
const PLANTED = `import { appendFileSync } from "node:fs";
import * as real from ${JSON.stringify(RUNTIME)};
export * from ${JSON.stringify(RUNTIME)};
function plant(target, data) {
  const hex = Buffer.from(data).toString("hex");
  appendFileSync(process.env.PLANTED_LOG, JSON.stringify({ target, hex }) + "\\n");
  throw new Error(\`\${hex} \${Buffer.from(data).toString("base64")} [\${data.join(", ")}]\`);
}
export function decodeBars(data) {
  if (data.length >= 24) plant("decodeBars", data);
  return real.decodeBars(data);
}
export function decodeBookDelta(data) {
  const count = data.length >= 24 && new DataView(data.buffer, data.byteOffset).getUint32(12, true);
  if (count > 1000) plant("decodeBookDelta", data);
  return real.decodeBookDelta(data);
}
`;

let scratch = "";
afterEach(() => {
  if (scratch) rmSync(scratch, { recursive: true, force: true });
});

/** The ways a report could print `data`, with whitespace removed (as the report is). */
function forms(data: Buffer): string[] {
  const b64 = data.toString("base64");
  return [
    data.toString("hex"),
    data.toString("hex").toUpperCase(),
    b64,
    b64.replace(/=+$/, ""),
    data.toString("base64url"),
    [...data].join(","),
  ];
}

it("a failing input reaches no report", { timeout: 60_000 }, () => {
  scratch = mkdtempSync(join(tmpdir(), "cv-fuzz-report-"));
  const planted = join(scratch, "planted.mjs");
  const config = join(scratch, "vitest.config.mjs");
  writeFileSync(planted, PLANTED);
  writeFileSync(
    config,
    `export default ${JSON.stringify({
      root: PKG,
      cacheDir: join(scratch, ".vite"),
      resolve: { alias: [{ find: "../src/runtime/index.js", replacement: planted }] },
      test: { include: ["test/cvwb-fuzz.fuzz.test.ts"], testTimeout: 600_000 },
    })};`,
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
  });
  const done = spawnSync(process.execPath, [VITEST, "run", "--config", config], {
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
    .map((line) => JSON.parse(line) as { target: string; hex: string });
  const digestOf = (data: Buffer): string =>
    createHash("sha256").update(`${SEED}:`).update(data).digest("hex");
  expect(out.match(/^ FAIL /gm)?.length).toBe(2); // each of the two tests failed, once
  expect(out).not.toContain("planted.mjs"); // nor the error the decoder threw
  expect(out).not.toContain(String(SEED)); // nor the seed (it stays in the failure file)
  // each failure line is a reason, then the target and the digest: nothing else
  const reported = [...out.matchAll(/^Error: [\w ()-]+: (\w+) sha256=([0-9a-f]{64})$/gm)];
  expect(reported.length, out).toBe(2);
  for (const [, target, digest] of reported) {
    const hit = seen.find(
      (s) => s.target === target && digestOf(Buffer.from(s.hex, "hex")) === digest,
    );
    const data = Buffer.from(hit?.hex ?? "", "hex");
    expect(data.length).toBeGreaterThanOrEqual(24); // the digest names a planted input
    const saved = readFileSync(join(scratch, "out", `${target}-${digest}.json`), "utf8");
    const input = data.toString("base64");
    expect(JSON.parse(saved)).toEqual({ seed: String(SEED), target, input });
  }
  const flat = out.replace(/\s+/g, "");
  for (const { hex } of seen) {
    const data = Buffer.from(hex, "hex");
    for (const window of [data, data.subarray(0, 12), data.subarray(-12)]) {
      expect(forms(window).filter((form) => flat.includes(form.replace(/\s+/g, "")))).toEqual([]);
    }
  }
});
