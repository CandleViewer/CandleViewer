import { describe, expect, it, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";

// This test binds docs/plan/ws-schema.json (machine-authoritative) to
// docs/plan/23-ws-protocol.md (human-authoritative) — the "doc-drift" pattern
// required by E02-T09 AC4 and documented at the top of
// scripts/extract-ws-schema.mjs. It must fail whenever the committed
// artefact disagrees with a fresh extraction of the markdown, and whenever
// the markdown's §6 topic catalogue names a topic the schema doesn't cover.
// The tamper cases check a temp copy (`--check --schema <path>`): no test
// writes the tracked artefact, which other readers may be reading (#2970).

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const repoRoot = join(packageRoot, "..", "..");
const extractScript = join(packageRoot, "scripts", "extract-ws-schema.mjs");
const schemaPath = join(repoRoot, "docs", "plan", "ws-schema.json");

let tempDir: string | undefined;

afterEach(() => {
  if (tempDir !== undefined) {
    rmSync(tempDir, { recursive: true, force: true });
    tempDir = undefined;
  }
});

function run(args: string[]): void {
  execFileSync("node", [extractScript, ...args], { cwd: packageRoot, stdio: "pipe" });
}

function copyOfArtefact(contents: string): string {
  tempDir = mkdtempSync(join(tmpdir(), "cv-ws-schema-"));
  const copy = join(tempDir, "ws-schema.json");
  writeFileSync(copy, contents, "utf8");
  return copy;
}

function exitStatus(args: string[]): number | null {
  try {
    run(args);
    return 0;
  } catch (err) {
    return (err as { status: number | null }).status;
  }
}

describe("ws-schema.json drift", () => {
  it("matches a fresh extraction of docs/plan/23-ws-protocol.md", () => {
    expect(() => run(["--check"])).not.toThrow();
  });

  it("passes --check on an untouched copy, so the copy is compared as the tracked file", () => {
    const copy = copyOfArtefact(readFileSync(schemaPath, "utf8"));
    expect(() => run(["--check", "--schema", copy])).not.toThrow();
  });

  it("fails --check when the committed artefact is hand-edited out of sync", () => {
    const committed = readFileSync(schemaPath, "utf8");
    const tampered = committed.replace('"schemaCount":', '"schemaCount_TAMPERED":');
    expect(tampered).not.toBe(committed);

    expect(() => run(["--check", "--schema", copyOfArtefact(tampered)])).toThrow();
  });

  it("fails --check when the markdown's §6 topic catalogue gains a row missing from the artefact", () => {
    // Simulates AC4: a new topic row in 23-ws-protocol.md that the committed
    // ws-schema.json does not yet know about. We can't (and mustn't) hand-edit
    // the markdown here, so we assert the mechanism directly: removing a known
    // topic row from a copy of the artefact must reproduce the same failure
    // mode --check reports for "markdown row present, artefact row absent".
    const artefact = JSON.parse(readFileSync(schemaPath, "utf8")) as {
      topicCatalogue: Array<{ topicPattern: string }>;
    };
    expect(artefact.topicCatalogue.length).toBeGreaterThan(0);
    artefact.topicCatalogue.pop();
    const copy = copyOfArtefact(JSON.stringify(artefact, null, 2) + "\n");

    expect(() => run(["--check", "--schema", copy])).toThrow();
  });

  it.each([[["--schema", "x.json"]], [["--check", "--schema"]], [["--check", "--bogus"]]])(
    "refuses %j with exit status 2",
    (args) => {
      expect(exitStatus(args)).toBe(2);
    },
  );
});
