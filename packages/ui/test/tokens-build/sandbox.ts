import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

export const UI_ROOT = path.resolve(import.meta.dirname, "..", "..");
const REPO_ROOT = path.resolve(UI_ROOT, "..", "..");

/** Runs `scripts/build-tokens.mjs` of the package rooted at `cwd`: the real one, or a sandbox copy. */
export function runBuild(cwd = UI_ROOT): string {
  const script = path.join(cwd, "scripts", "build-tokens.mjs");
  // Piped, so a build that fails on purpose keeps its stack out of the test log; the error carries it.
  return execFileSync(process.execPath, [script], { cwd, encoding: "utf-8", stdio: "pipe" });
}

/** The output (stdout then stderr) of a build that must fail; a build that succeeds fails the test. */
export function failedBuildOutput(cwd: string): string {
  try {
    runBuild(cwd);
  } catch (error) {
    const { stdout, stderr } = error as { stdout?: string; stderr?: string };
    return `${stdout ?? ""}${stderr ?? ""}`;
  }
  throw new Error("expected the token build to fail, but it succeeded");
}

/**
 * A temp copy of the files the token build reads; `<dir>/packages/ui` is where it builds. The real
 * `build/` feeds `dist/` (tsup's `onSuccess`) and other lanes, and `ui#build` may run beside the tests,
 * so no test builds into or deletes it. The copy lies outside the workspace, so it links the package's
 * `node_modules`: the build checks its CSS with esbuild, which the copy cannot resolve otherwise.
 */
export function makeSandbox(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "cv-tokens-"));
  const ui = path.join(dir, "packages", "ui");
  mkdirSync(ui, { recursive: true });
  cpSync(path.join(UI_ROOT, "tokens"), path.join(ui, "tokens"), { recursive: true });
  cpSync(path.join(UI_ROOT, "scripts"), path.join(ui, "scripts"), { recursive: true });
  symlinkSync(path.join(UI_ROOT, "node_modules"), path.join(ui, "node_modules"), "junction");
  const styleDictionary = path.join("tools", "style-dictionary");
  mkdirSync(path.join(dir, styleDictionary), { recursive: true });
  cpSync(
    path.join(REPO_ROOT, styleDictionary, "formats"),
    path.join(dir, styleDictionary, "formats"),
    { recursive: true },
  );
  cpSync(
    path.join(REPO_ROOT, styleDictionary, "package.json"),
    path.join(dir, styleDictionary, "package.json"),
  );
  return dir;
}
