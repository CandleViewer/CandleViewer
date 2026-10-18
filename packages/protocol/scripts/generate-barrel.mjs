#!/usr/bin/env node
// Writes src/generated/index.ts, the barrel src/index.ts re-exports as `generated`. Every file
// under src/generated comes from a generator: CI's `gen` gate fails a committed file there
// that `pnpm generate` does not write (CI-GEN-005, #3299). To export another generated surface,
// add it to SURFACES. ./cvwb stays out of the barrel: src/runtime imports it directly.
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "src", "generated");
const outPath = join(outDir, "index.ts");

// Each surface is ./<name>/index.ts, written by its own generator; `about` is its comment.
const SURFACES = [
  { name: "rest", about: ["TS types for docs/plan/22-api-openapi.yaml (via openapi-typescript)"] },
  { name: "ws", about: ["TS types for docs/plan/23-ws-protocol.md §13-15 (via ws-schema.json)"] },
  {
    name: "policy",
    about: [
      "enum-value tables mirroring services/api/candleviewer/",
      "exchange/policy.py (tools/gen/export_instrument_policy_rules.py)",
    ],
  },
  {
    name: "bars",
    about: [
      "bar domain model mirroring services/api/candleviewer/bars/",
      "models.py (scripts/generate-bar-types.mjs)",
    ],
  },
];

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`. Hand
// edits are rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// \`linguist-generated\` in .gitattributes.
//
// Barrel for the generated surfaces, written by scripts/generate-barrel.mjs:`;
const FOOTER = "// ==========================================================================";

function render() {
  const width = Math.max(...SURFACES.map(({ name }) => name.length + 2));
  const bullets = SURFACES.flatMap(({ name, about: [first, ...more] }) => {
    const lead = `//  - ${`./${name}`.padEnd(width)} — `;
    return [lead + first, ...more.map((line) => `//${" ".repeat(lead.length - 2)}${line}`)];
  });
  const exports = SURFACES.map(({ name }) => `export * as ${name} from "./${name}/index.js";`);
  return [HEADER, ...bullets, FOOTER, ...exports].join("\n") + "\n";
}

async function main() {
  mkdirSync(outDir, { recursive: true });
  const config = (await prettier.resolveConfig(outPath)) ?? {};
  writeFileSync(outPath, await prettier.format(render(), { ...config, filepath: outPath }), "utf8");
  console.log(`[generate-barrel] wrote ${outPath}.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
