import { afterEach, describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  appendFileSync,
} from "node:fs";
import { devNull, tmpdir } from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
const repoRoot = join(packageRoot, "..", "..");
// Where update-manifest.mjs records the hashes, relative to the package root (#2743).
const MANIFEST = join(".cache", "generated-manifest.json");

let tmpDir: string | undefined;

afterEach(() => {
  if (tmpDir) {
    rmSync(tmpDir, { recursive: true, force: true });
    tmpDir = undefined;
  }
});

/** A scratch package root holding a copy of the real generated tree and both manifest scripts. */
function stagePackage(): string {
  tmpDir = mkdtempSync(join(tmpdir(), "protocol-guard-"));
  cpSync(join(packageRoot, "src", "generated"), join(tmpDir, "src", "generated"), {
    recursive: true,
  });
  mkdirSync(join(tmpDir, "scripts"));
  for (const script of ["update-manifest.mjs", "check-generated-guard.mjs"]) {
    cpSync(join(packageRoot, "scripts", script), join(tmpDir, "scripts", script));
  }
  return tmpDir;
}

/** The environment without user/system git config or a hook's GIT_DIR: hermetic git calls. */
function gitEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    GIT_CONFIG_GLOBAL: devNull,
    GIT_CONFIG_NOSYSTEM: "1",
  };
  for (const name of ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"]) delete env[name];
  return env;
}

function runScript(root: string, script: string): { status: number | null; output: string } {
  const result = spawnSync("node", [join(root, "scripts", script)], {
    cwd: root,
    encoding: "utf8",
    env: gitEnv(),
  });
  return { status: result.status, output: `${result.stdout}${result.stderr}` };
}

function git(root: string, ...args: string[]): void {
  const result = spawnSync("git", ["-c", "user.name=t", "-c", "user.email=t@t", ...args], {
    cwd: root,
    encoding: "utf8",
    env: gitEnv(),
  });
  expect(result.status, result.stderr).toBe(0);
}

describe("generated-file guard", () => {
  it("records the manifest under the git-ignored .cache/, never in src/generated", () => {
    const root = stagePackage();
    expect(runScript(root, "update-manifest.mjs").status).toBe(0);
    expect(existsSync(join(root, MANIFEST))).toBe(true);
    expect(existsSync(join(root, "src", "generated", ".manifest.json"))).toBe(false);

    const guard = runScript(root, "check-generated-guard.mjs");
    expect(guard.status).toBe(0);
    expect(guard.output).toContain("verified against the last generate");
  });

  it("keeps the manifest path out of git", () => {
    const ignored = spawnSync(
      "git",
      ["check-ignore", "-q", join("packages", "protocol", MANIFEST).replace(/\\/g, "/")],
      { cwd: repoRoot },
    );
    expect(ignored.status).toBe(0);
  });

  it.each(["rest/index.ts", "ws/index.ts"])(
    "fails when %s is hand-edited after generate (hash mismatch)",
    (rel) => {
      const root = stagePackage();
      expect(runScript(root, "update-manifest.mjs").status).toBe(0);
      // Header stays, content changes -> hash mismatch.
      appendFileSync(join(root, "src", "generated", rel), "export type HandEdited = true;\n");

      const guard = runScript(root, "check-generated-guard.mjs");
      expect(guard.status).toBe(1);
      expect(guard.output).toContain(`${rel}: hash mismatch`);
      expect(guard.output).toContain("pnpm generate");
    },
  );

  it("accepts what git wrote since the last generate, and still fails a hand edit on top", () => {
    const root = stagePackage();
    const rest = join(root, "src", "generated", "rest", "index.ts");
    writeFileSync(join(root, ".gitignore"), ".cache/\n", "utf8");
    git(root, "init", "-q", "-b", "main");
    git(root, "add", "-A");
    git(root, "commit", "-qm", "generated");
    expect(runScript(root, "update-manifest.mjs").status).toBe(0);
    // A pull brings in a merged contract PR: one generated file changed, one new.
    appendFileSync(rest, "export type Pulled = true;\n");
    writeFileSync(
      join(root, "src", "generated", "pulled.ts"),
      "// GENERATED FILE — DO NOT EDIT BY HAND.\nexport {};\n",
      "utf8",
    );
    git(root, "add", "-A");
    git(root, "commit", "-qm", "pulled");

    const pulled = runScript(root, "check-generated-guard.mjs");
    expect(pulled.status).toBe(0);
    expect(pulled.output).toContain("git has since written 2, matching HEAD");

    appendFileSync(rest, "export type HandEdited = true;\n");
    const edited = runScript(root, "check-generated-guard.mjs");
    expect(edited.status).toBe(1);
    expect(edited.output).toContain("rest/index.ts: hash mismatch");
    expect(edited.output).not.toContain("pulled.ts");
  });

  it("checks headers only, and says so, when no generate has run yet", () => {
    const root = stagePackage();
    const guard = runScript(root, "check-generated-guard.mjs");
    expect(guard.status).toBe(0);
    expect(guard.output).toContain("headers only");
  });

  it("fails on a generated file without the header even with no manifest", () => {
    const root = stagePackage();
    writeFileSync(join(root, "src", "generated", "index.ts"), "export {};\n", "utf8");
    const guard = runScript(root, "check-generated-guard.mjs");
    expect(guard.status).toBe(1);
    expect(guard.output).toContain("index.ts: missing the");
  });

  it("rejects the manifest committed before #2743, which generate removes", () => {
    const root = stagePackage();
    const legacy = join(root, "src", "generated", ".manifest.json");
    writeFileSync(legacy, "{}\n", "utf8");
    const before = runScript(root, "check-generated-guard.mjs");
    expect(before.status).toBe(1);
    expect(before.output).toContain(".manifest.json: no longer committed");

    expect(runScript(root, "update-manifest.mjs").status).toBe(0);
    expect(existsSync(legacy)).toBe(false);
    expect(runScript(root, "check-generated-guard.mjs").status).toBe(0);
  });
});
