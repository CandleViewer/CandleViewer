import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { RULE_IR_SCHEMA, RULE_IR_SCHEMA_ID, type RuleIr } from "../src/generated/ruleIr/index.js";

// E37-T01: the TS rule IR types and the published schema are generated from the committed JSON
// Schema (rendered from the pydantic models; the document GET /api/v1/schemas/rule-ir.json serves).
// Regenerating must reproduce the committed file byte-for-byte. The fresh copy goes to a temp dir:
// rewriting the tracked file in place would race the generated-guard test (#2965).

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const repoRoot = join(packageRoot, "..", "..");
const outPath = join(packageRoot, "src", "generated", "ruleIr", "index.ts");
const script = join(packageRoot, "scripts", "generate-rule-ir-types.mjs");
const schemaPath = join(repoRoot, "services", "api", "candleviewer", "rules", "ir", "rule-ir.json");

describe("generated rule IR surface", () => {
  it("matches a fresh generation from rule-ir.json (drift check)", () => {
    const committed = readFileSync(outPath, "utf8").split("\r\n").join("\n");
    const dir = mkdtempSync(join(tmpdir(), "cv-rule-ir-types-"));
    try {
      const freshPath = join(dir, "index.ts");
      execFileSync("node", [script, "--out", freshPath], { cwd: packageRoot, stdio: "pipe" });
      const fresh = readFileSync(freshPath, "utf8").split("\r\n").join("\n");
      expect(fresh).toBe(committed);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("carries the published schema verbatim", () => {
    const published = JSON.parse(readFileSync(schemaPath, "utf8")) as { $id: string };
    expect(RULE_IR_SCHEMA).toEqual(published);
    expect(RULE_IR_SCHEMA_ID).toBe(published.$id);
    expect(RULE_IR_SCHEMA_ID).toBe("https://candleviewer.local/schemas/rule-ir-v1.json");
  });

  it("types a minimal valid document", () => {
    const doc: RuleIr = {
      rule_id: "00000000-0000-4000-8000-000000000001",
      version: 1,
      name: "minimal",
      enabled: false,
      mode: "disabled",
      scope: { level: "global" },
      trigger: { type: "on_price_update" },
      conditions: { node_id: "c1", op: "is_true", left: { metric: "position_open" } },
      actions: [{ node_id: "a1", type: "send_notification", params: {} }],
    };
    expect(doc.actions).toHaveLength(1);
  });
});
