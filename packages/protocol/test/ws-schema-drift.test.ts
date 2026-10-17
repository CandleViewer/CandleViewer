import { describe, expect, it, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { format, resolveConfig } from "prettier";

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

type Artefact = { topicCatalogue: Array<{ topicPattern: string }> };

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function run(args: string[]): void {
  execFileSync("node", [extractScript, ...args], { cwd: packageRoot, stdio: "pipe" });
}

function copyOfArtefact(contents: string): string {
  const dir = mkdtempSync(join(tmpdir(), "cv-ws-schema-"));
  tempDirs.push(dir);
  const copy = join(dir, "ws-schema.json");
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

function readArtefact(): Artefact {
  return JSON.parse(readFileSync(schemaPath, "utf8")) as Artefact;
}

// Serialises `artefact` as extract-ws-schema.mjs does: Prettier, with the config and `filepath` of
// the tracked file. A bare JSON.stringify lays arrays out differently (Prettier keeps short ones on
// one line), so a check on it would fail on layout whatever the copy held.
async function formattedAsTracked(artefact: Artefact): Promise<string> {
  const config = (await resolveConfig(schemaPath)) ?? {};
  return format(JSON.stringify(artefact, null, 2) + "\n", { ...config, filepath: schemaPath });
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

    expect(exitStatus(["--check", "--schema", copyOfArtefact(tampered)])).toBe(1);
  });

  it("passes --check on the untouched artefact parsed, re-serialised and formatted as the generator does", async () => {
    // The control for the next case: that copy is built the same way, so only its removed row can
    // make --check fail.
    const copy = copyOfArtefact(await formattedAsTracked(readArtefact()));
    expect(() => run(["--check", "--schema", copy])).not.toThrow();
  });

  it("fails --check when the markdown's §6 topic catalogue gains a row missing from the artefact", async () => {
    // Simulates AC4: a new topic row in 23-ws-protocol.md that the committed
    // ws-schema.json does not yet know about. We can't (and mustn't) hand-edit
    // the markdown here, so we assert the mechanism directly: removing a known
    // topic row from a copy of the artefact must reproduce the same failure
    // mode --check reports for "markdown row present, artefact row absent".
    const artefact = readArtefact();
    expect(artefact.topicCatalogue.length).toBeGreaterThan(0);
    artefact.topicCatalogue.pop();
    const copy = copyOfArtefact(await formattedAsTracked(artefact));

    expect(exitStatus(["--check", "--schema", copy])).toBe(1);
  });

  // Each refused shape carries a `--check`, so a parser that regressed to accept it would run the
  // read-only check, never the generator that rewrites docs/plan/ws-schema.json.
  it.each([
    [["--schema", "x.json", "--check"]], // wrong order
    [["--schema", "--check"]], // --schema without a --check before it
    [["--check", "--schema"]], // no path
    [["--check", "--schema", "--check"]], // a flag where the path belongs
    [["--check", "--bogus"]], // an unknown flag
  ])("refuses %j with exit status 2", (args) => {
    expect(exitStatus(args)).toBe(2);
  });
});
