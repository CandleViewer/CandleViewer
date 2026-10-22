#!/usr/bin/env node
// Generates the TS mirror of the rule IR (ticket E37-T01, docs/plan/24-internal-schemas.md §11.2)
// so the rule editor's types cannot drift from the server's: the types, and the published JSON
// Schema itself, which the client-side canonical mirror reads its defaults and field kinds from.
//
// Source of truth: services/api/candleviewer/rules/ir/models.py. Pydantic renders it to the
// committed JSON Schema services/api/candleviewer/rules/ir/rule-ir.json, the document that
// GET /api/v1/schemas/rule-ir.json serves, via services/api/scripts/generate_rule_ir_schema.py:
// that step needs pydantic and is drift-checked on the Python side (the py lane). This script
// only compiles the committed schema to TypeScript, so it runs without a Python environment
// (same split as generate-bar-types.mjs).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { compile } from "json-schema-to-typescript";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..", "..");
const schemaPath = join(repoRoot, "services", "api", "candleviewer", "rules", "ir", "rule-ir.json");
const outDir = join(__dirname, "..", "src", "generated", "ruleIr");
const defaultOutPath = join(outDir, "index.ts");
// Usage: node scripts/generate-rule-ir-types.mjs [--out <path>]
// `--out` writes the same bytes elsewhere, so the drift test never rewrites the tracked file under
// src/generated while other test files read it (#2965). Any other argument is refused.
function outputPath(args) {
  if (args.length === 0) return defaultOutPath;
  if (args.length === 2 && args[0] === "--out" && args[1]) return resolve(args[1]);
  console.error("usage: node scripts/generate-rule-ir-types.mjs [--out <path>]");
  process.exit(2);
}
const outPath = outputPath(process.argv.slice(2));

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`.
// Source: services/api/candleviewer/rules/ir/rule-ir.json, the JSON Schema that
// \`GET /api/v1/schemas/rule-ir.json\` serves, rendered from
// services/api/candleviewer/rules/ir/models.py by
// services/api/scripts/generate_rule_ir_schema.py. Hand edits are rejected by
// the header-guard lint (packages/protocol/scripts/check-generated-guard.mjs).
// ==========================================================================
/* eslint-disable */

`;

async function main() {
  const doc = JSON.parse(readFileSync(schemaPath, "utf8"));
  // Compile a copy: `doc` itself is embedded verbatim below.
  const copy = JSON.parse(JSON.stringify(doc));
  // Fail clearly, not with a bare TypeError, if the schema no longer has what is stripped below.
  if (!copy.$defs?.Trigger?.allOf)
    throw new Error("rule-ir.json has no $defs.Trigger.allOf: update the strip in this script");
  // The published title ("CandleViewer Rule IR") would name the root interface after itself.
  copy.title = "RuleIr";
  // Strip per-property titles so scalar fields inline (no `Op`/`Type` alias clutter or name
  // collisions between the nodes' `op` enums); keep the $defs titles, which name the interfaces.
  for (const prop of Object.values(copy.properties ?? {})) delete prop.title;
  for (const def of Object.values(copy.$defs)) {
    for (const prop of Object.values(def.properties ?? {})) delete prop.title;
  }
  // Trigger's `allOf` is the if/then block "required per trigger type", which the compiler cannot
  // express (it would name the interface `Trigger1` and add an alias): the server enforces it.
  delete copy.$defs.Trigger.allOf;
  const types = await compile(copy, "RuleIr", {
    bannerComment: "",
    style: { semi: true, singleQuote: false },
    additionalProperties: false,
    unreachableDefinitions: false,
  });
  const data = `export const RULE_IR_SCHEMA_ID = ${JSON.stringify(doc.$id)};

// Freezes a value and everything reachable from it (plain JSON: no cycles).
function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/**
 * The published schema, verbatim; the canonical mirror reads defaults and field kinds from it.
 * Frozen at every depth, so no consumer can change what another reads.
 */
export const RULE_IR_SCHEMA: { readonly [key: string]: unknown } = deepFreeze(${JSON.stringify(doc)});
`;
  const chunks = [HEADER, types, data];
  mkdirSync(dirname(outPath), { recursive: true });
  // Format as the tracked file, whatever the output path, so both paths get identical bytes.
  const config = (await prettier.resolveConfig(defaultOutPath)) ?? {};
  writeFileSync(
    outPath,
    await prettier.format(chunks.join("\n"), { ...config, filepath: defaultOutPath }),
    "utf8",
  );
  console.log(`[generate-rule-ir-types] wrote ${outPath}.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
