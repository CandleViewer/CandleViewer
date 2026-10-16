#!/usr/bin/env node
// Records the sha256 of every file under src/generated/, keyed by its path relative to
// src/generated/, in packages/protocol/.cache/generated-manifest.json. Consumed by
// check-generated-guard.mjs. The manifest is git-ignored, never committed (#2743): every
// contract PR changed the same hash line, so any two of them conflicted.
import { mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const generatedDir = join(packageRoot, "src", "generated");
const manifestPath = join(packageRoot, ".cache", "generated-manifest.json");

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
  const normalised = content.split("\r\n").join("\n");
  return createHash("sha256").update(normalised).digest("hex");
}

function main() {
  // The manifest committed before #2743; a branch cut before then may still carry it.
  rmSync(join(generatedDir, ".manifest.json"), { force: true });
  const files = listFiles(generatedDir).sort();
  const manifest = {};
  for (const file of files) {
    const rel = relative(generatedDir, file).replace(/\\/g, "/");
    manifest[rel] = sha256(readFileSync(file, "utf8"));
  }
  mkdirSync(dirname(manifestPath), { recursive: true });
  writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  console.log(`[update-manifest] wrote ${manifestPath} (${files.length} file(s)).`);
}

main();
