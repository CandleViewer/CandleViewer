#!/usr/bin/env node
// No-hue-alone gate (E47-S06, US-SET-005 NFR, WCAG 1.4.1). Static registry validation.
//   node tools/contrast/no-hue-alone.mjs   exits 1 naming surface + encoding on violation (A11Y-C008)
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const REQUIRED_ENCODINGS = [
  "buy-sell",
  "bid-ask",
  "order-status",
  "pnl",
  "connection-health",
  "demo-live",
  "imbalance",
  "delta-sign",
  "risk-severity",
  // The rule graph (E37-D03 §9.4, EN-1 to EN-4).
  "node-type",
  "port-type",
  "edge-validity",
  "graph-diagnostic",
];
export const CHANNELS = ["glyph", "sign", "text", "pattern", "position"];

/** @returns {string[]} violation messages (empty = pass) */
export function validate(registry) {
  const errs = [];
  const encs = registry.encodings ?? {};
  for (const name of REQUIRED_ENCODINGS) {
    const e = encs[name];
    if (!e || Object.keys(e.surfaces ?? {}).length === 0)
      errs.push(`A11Y-C008 encoding "${name}" has no registered surface`);
  }
  for (const [name, e] of Object.entries(encs)) {
    for (const [surface, channels] of Object.entries(e.surfaces ?? {})) {
      const ok = (channels ?? []).filter((c) => CHANNELS.includes(c));
      if (ok.length === 0)
        errs.push(`A11Y-C008 surface "${surface}" renders "${name}" with no non-colour channel`);
    }
  }
  // Demo/live must be text on every surface (security note: never colour-only).
  for (const [surface, channels] of Object.entries(encs["demo-live"]?.surfaces ?? {})) {
    if (!channels.includes("text"))
      errs.push(`A11Y-C008 surface "${surface}" renders "demo-live" without a text channel`);
  }
  return errs;
}

export async function main() {
  const reg = JSON.parse(await readFile(path.join(__dirname, "encodings.json"), "utf-8"));
  const errs = validate(reg);
  for (const e of errs) console.error(`[no-hue-alone] ${e}`);
  console.log(`[no-hue-alone] ${errs.length === 0 ? "ok" : errs.length + " violation(s)"}`);
  if (errs.length) process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
