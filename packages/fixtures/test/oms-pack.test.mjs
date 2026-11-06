import { describe, expect, it } from "vitest";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { assertSupportedSchema, validateSchema } from "../scripts/accounts-pack.mjs";
import { KEY_SHAPE_DIRS, SCAN_DIRS, runVerify, verifyDirectories } from "../scripts/verify.mjs";

// E29-Q01: the OMS scenario pack (packages/fixtures/oms/) is inside the package redaction gate.
const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const OMS_DIR = join(packageRoot, "oms");

describe("the OMS scenario pack in the redaction gate", () => {
  it("is in verify.mjs's scan list, and the gate finds nothing in the pack", () => {
    expect(SCAN_DIRS).toContain(OMS_DIR);
    const { files, findings } = verifyDirectories([OMS_DIR]);
    expect(findings).toEqual([]);
    for (const file of ["README.md", "manifest.schema.json"]) {
      expect(files).toContain(join(OMS_DIR, file));
    }
    for (const file of ["manifest.json", "frames.jsonl"]) {
      expect(files).toContain(join(OMS_DIR, "ws_duplicate_exec", file));
    }
  });

  it("flags a credential-shaped field planted in a copy of the pack, naming the file, not the value", () => {
    const sandbox = mkdtempSync(join(tmpdir(), "oms-pack-"));
    try {
      const pack = join(sandbox, "oms");
      cpSync(OMS_DIR, pack, { recursive: true });
      expect(verifyDirectories([pack]).findings).toEqual([]);
      const value = "abcdef1234567890";
      const leak = join(pack, "ws_duplicate_exec", "leak.json");
      writeFileSync(leak, JSON.stringify({ api_key: value }));
      const { findings } = verifyDirectories([pack]);
      expect(findings).toEqual([{ file: leak, pattern: "Bybit-style api key/secret field" }]);
      expect(JSON.stringify(findings)).not.toContain(value);
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });

  it("refuses a bare key-shaped token planted in a copy of the pack, by file and shape, never the token", () => {
    expect(KEY_SHAPE_DIRS).toContain(OMS_DIR);
    const sandbox = mkdtempSync(join(tmpdir(), "oms-pack-"));
    try {
      const pack = join(sandbox, "oms");
      cpSync(OMS_DIR, pack, { recursive: true });
      expect(verifyDirectories([pack], [pack]).findings).toEqual([]);
      const token = "aB3".repeat(7).slice(0, 20); // 20 letters and digits: a key's shape
      const leak = join(pack, "ws_duplicate_exec", "notes.txt");
      writeFileSync(leak, `a retMsg that echoes ${token} in prose`);
      const { findings } = verifyDirectories([pack], [pack]);
      expect(findings).toEqual([{ file: leak, pattern: "bare api-key-shaped token at offset 21" }]);
      expect(JSON.stringify(findings)).not.toContain(token);
      // the gate the lint script runs reads its own list, not only the export: plant under a root
      const root = join(sandbox, "root");
      cpSync(pack, join(root, "oms"), { recursive: true });
      expect(runVerify(root).findings.map((f) => f.pattern)).toEqual([findings[0].pattern]);
    } finally {
      rmSync(sandbox, { recursive: true, force: true });
    }
  });

  it("keeps the manifest schema inside the accounts pack validator's keywords, and the scenario meets it", () => {
    const schema = JSON.parse(readFileSync(join(OMS_DIR, "manifest.schema.json"), "utf8"));
    const scenario = JSON.parse(
      readFileSync(join(OMS_DIR, "ws_duplicate_exec", "manifest.json"), "utf8"),
    );
    expect(() => assertSupportedSchema(schema)).not.toThrow();
    expect(validateSchema(schema, scenario)).toEqual([]);
    expect(validateSchema(schema, { ...scenario, surprise: 1 })).toEqual([
      '$: unexpected property "surprise"',
    ]);
  });

  it("is an input of lint and the tests, so no cached run can skip a change to it", () => {
    const turbo = JSON.parse(readFileSync(join(packageRoot, "turbo.json"), "utf8"));
    for (const task of ["lint", "test", "test:cov"]) {
      expect(turbo.tasks[task].inputs).toContain("oms/**");
    }
  });
});
