#!/usr/bin/env node
// Generates TS types for every WS envelope/message-kind/topic-payload schema
// declared in docs/plan/ws-schema.json (itself extracted from
// docs/plan/23-ws-protocol.md §13-15 by extract-ws-schema.mjs).
//
// Uses json-schema-to-typescript's compile() with a custom $ref resolver so
// the document-local `cv://ws/v1/...` URIs resolve against the in-memory
// schema map instead of hitting the network or filesystem.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { compile } from "json-schema-to-typescript";
import prettier from "prettier";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..", "..");
const schemaPath = join(repoRoot, "docs", "plan", "ws-schema.json");
const outDir = join(__dirname, "..", "src", "generated", "ws");
const outPath = join(outDir, "index.ts");

const HEADER = `// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with \`pnpm --filter @candleviewer/protocol generate\`.
// Source: docs/plan/ws-schema.json, extracted from docs/plan/23-ws-protocol.md
// §13-15. Hand edits are rejected by the header-guard lint
// (packages/protocol/scripts/check-generated-guard.mjs) and by
// \`linguist-generated\` in .gitattributes.
// ==========================================================================
/* eslint-disable */

`;

/** A resolver plugin: resolves any \`cv://...\` $ref against the in-memory schema map. */
function cvResolver(schemasById) {
  return {
    order: 1,
    canRead: /^cv:\/\//,
    read(file) {
      // file.url is the full $ref target, possibly with a #/ fragment already
      // stripped by json-schema-ref-parser before calling read(); the base
      // document id is what remains.
      const id = file.url.split("#")[0];
      const schema = schemasById[id];
      if (!schema) {
        throw new Error(`[generate-ws-types] unresolved $ref base: ${id}`);
      }
      return JSON.stringify(schema);
    },
  };
}

/** Turns a schema $id like cv://ws/v1/book.schema.json into a PascalCase type name. */
function typeNameFor(id, title) {
  if (title) {
    return title
      .replace(/[`{}./]/g, " ")
      .split(/[\s_-]+/)
      .filter(Boolean)
      .map((w) => w[0].toUpperCase() + w.slice(1))
      .join("");
  }
  const base = id.replace(/^cv:\/\/ws\/v1\//, "").replace(/\.schema\.json$/, "");
  return base
    .split(/[.\-_]/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join("");
}

/** The keywords of a root `allOf` member that only constrains values and adds no type. */
const CONDITIONAL_ONLY = new Set(["if", "then", "else", "description", "$comment"]);

/**
 * The schema as json-schema-to-typescript compiles it. A root `allOf` makes the root an anonymous
 * alias, so the comment on each of its `$defs` reads "`undefined`'s JSON-Schema". Where the root
 * has `$defs`, the root `allOf` members that hold only `if` / `then` / `else` are left out here:
 * the generator emits no type for them either way. The bundle the validators read keeps them.
 */
function forTypes(schema) {
  if (!schema.$defs || !Array.isArray(schema.allOf)) {
    return schema;
  }
  const typed = schema.allOf.filter((member) =>
    Object.keys(member).some((key) => !CONDITIONAL_ONLY.has(key)),
  );
  const rest = { ...schema };
  delete rest.allOf;
  return typed.length > 0 ? { ...rest, allOf: typed } : rest;
}

async function main() {
  const artefact = JSON.parse(readFileSync(schemaPath, "utf8"));
  const schemasById = artefact.schemas;

  mkdirSync(outDir, { recursive: true });

  const chunks = [HEADER];
  const exportedNames = [];

  // Deterministic order: sort by $id so output is byte-stable across runs.
  const ids = Object.keys(schemasById).sort();

  for (const id of ids) {
    const schema = schemasById[id];
    const typeName = typeNameFor(id, schema.title);
    if (exportedNames.includes(typeName)) {
      throw new Error(
        `[generate-ws-types] duplicate generated type name "${typeName}" (from ${id})`,
      );
    }
    exportedNames.push(typeName);

    const ts = await compile(forTypes(schema), typeName, {
      cwd: repoRoot,
      bannerComment: "",
      style: { semi: true, singleQuote: false },
      $refOptions: {
        resolve: { cv: cvResolver(schemasById) },
      },
      unreachableDefinitions: true,
      additionalProperties: false,
    });
    chunks.push(`// Source: ${id}\n${ts}`);
  }

  // A stable lookup table from topic pattern -> generated payload type name,
  // for runtime code that needs to pick a decoder by topic. The topic's first
  // dot-segment (its "family", e.g. "book" out of "book.{symbol}.{depth}")
  // matches the schema file's basename 1:1 by construction (§6 vs §14/§15).
  chunks.push(
    "export type WsTopicPayloadMap = {\n" +
      artefact.topicCatalogue
        .map((t) => {
          const family = t.topicPattern.split(".")[0];
          const id = `cv://ws/v1/${family}.schema.json`;
          const schema = schemasById[id];
          if (!schema) {
            throw new Error(
              `[generate-ws-types] topic family "${family}" (from "${t.topicPattern}") has no ` +
                `matching schema at ${id}.`,
            );
          }
          return `  ${JSON.stringify(t.topicPattern)}: ${typeNameFor(id, schema.title)};`;
        })
        .join("\n") +
      "\n};\n",
  );

  const config = (await prettier.resolveConfig(outPath)) ?? {};
  writeFileSync(
    outPath,
    await prettier.format(chunks.join("\n"), { ...config, filepath: outPath }),
    "utf8",
  );
  console.log(`[generate-ws-types] wrote ${outPath} (${exportedNames.length} types).`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
