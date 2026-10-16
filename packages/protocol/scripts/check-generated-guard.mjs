#!/usr/bin/env node
// Generated-file guard (E02-T03 acceptance criterion #3, #2743).
// Every file under src/generated/ must start with the GENERATED FILE header and, once
// `pnpm generate` has recorded what it wrote (update-manifest.mjs, in the git-ignored
// .cache/generated-manifest.json), still match those hashes: a hand edit since then fails here
// and points the author at `pnpm generate`. Without a recorded manifest (a fresh clone, CI) only
// the headers are checked, and the output says so. A committed hand edit is what CI's
// gen-freshness check catches: it regenerates and diffs (tools/ci/check_gen_freshness.py).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const generatedDir = join(packageRoot, "src", "generated");
const manifestPath = join(packageRoot, ".cache", "generated-manifest.json");
const HEADER_MARKER = "GENERATED FILE — DO NOT EDIT BY HAND";

function listFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listFiles(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

function sha256(content) {
  // Line-ending agnostic: a Windows checkout may present CRLF while the manifest
  // was recorded from LF content. Only bytes, never EOL style, decide "hand-edited".
  const normalised = content.split("\r\n").join("\n");
  return createHash("sha256").update(normalised).digest("hex");
}

function main() {
  const files = listFiles(generatedDir);
  const manifest = existsSync(manifestPath)
    ? JSON.parse(readFileSync(manifestPath, "utf8"))
    : undefined;
  const errors = [];

  for (const file of files) {
    const rel = relative(generatedDir, file).replace(/\\/g, "/");
    const content = readFileSync(file, "utf8");
    if (rel === ".manifest.json") {
      errors.push(`${rel}: no longer committed (#2743). Run \`pnpm generate\`, which removes it.`);
      continue;
    }
    if (!content.includes(HEADER_MARKER)) {
      errors.push(`${rel}: missing the "${HEADER_MARKER}" header.`);
      continue;
    }
    if (manifest === undefined) continue;
    const expected = manifest[rel];
    const actual = sha256(content);
    if (!expected) {
      errors.push(`${rel}: not recorded by the last \`pnpm generate\`; run it to regenerate.`);
    } else if (expected !== actual) {
      errors.push(
        `${rel}: hash mismatch (hand-edited?). Run \`pnpm generate\` instead of editing generated files.`,
      );
    }
  }

  if (errors.length > 0) {
    console.error("[generated-guard] FAILED:\n" + errors.map((e) => `  - ${e}`).join("\n"));
    process.exit(1);
  }
  if (manifest === undefined) {
    console.log(
      `[generated-guard] OK (${files.length} file(s), headers only: no ${relative(packageRoot, manifestPath)} yet; \`pnpm generate\` records one).`,
    );
    return;
  }
  console.log(`[generated-guard] OK (${files.length} file(s) verified against the last generate).`);
}

main();
