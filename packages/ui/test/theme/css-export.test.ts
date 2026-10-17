// @vitest-environment node
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const UI_ROOT = resolve(import.meta.dirname, "../..");
const COPY_SCRIPT = join(UI_ROOT, "scripts/copy-css.mjs");

describe("theme.css package export", () => {
  it("resolves through the package self-reference to the built copy of src/theme/theme.css", () => {
    // The same script tsup runs after a build; `--no-tokens` because a bare `test` run has no `build/` yet.
    execFileSync(process.execPath, [COPY_SCRIPT, "--no-tokens"], { cwd: UI_ROOT });
    const built = createRequire(import.meta.url).resolve("@candleviewer/ui/theme.css");
    expect(built).toBe(join(UI_ROOT, "dist", "theme.css"));
    const source = readFileSync(join(UI_ROOT, "src/theme/theme.css"), "utf-8");
    expect(readFileSync(built, "utf-8")).toBe(source);
  });
});

describe("copy-css script", () => {
  // A copy of the package layout with the token CSS a build racing a cleanup would leave (two of three),
  // started by its real path and through a symlink to it (a junction on Windows) from another directory:
  // it must act the same, never exit 0 having copied nothing.
  it.each(["its real path", "a symlinked path"])(
    "fails and copies nothing while a token CSS file is missing, then copies, run through %s",
    (via) => {
      const base = mkdtempSync(join(tmpdir(), "cv-copy-css-"));
      try {
        const root = join(base, "pkg");
        for (const dir of ["scripts", "src/theme", "build/css"])
          mkdirSync(join(root, dir), { recursive: true });
        copyFileSync(COPY_SCRIPT, join(root, "scripts/copy-css.mjs"));
        copyFileSync(join(UI_ROOT, "src/theme/theme.css"), join(root, "src/theme/theme.css"));
        for (const theme of ["dark", "light"])
          writeFileSync(join(root, `build/css/tokens.${theme}.css`), "");
        const entry = via === "its real path" ? root : join(base, "link");
        if (entry !== root) symlinkSync(root, entry, "junction");
        const run = (): Buffer =>
          execFileSync(process.execPath, [join(entry, "scripts/copy-css.mjs")], {
            cwd: base,
            stdio: "pipe",
          });
        expect(run).toThrow(/lacks tokens\.high-contrast\.css/);
        expect(existsSync(join(root, "dist"))).toBe(false);
        writeFileSync(join(root, "build/css/tokens.high-contrast.css"), "");
        run();
        expect(readdirSync(join(root, "dist")).sort()).toEqual([
          "theme.css",
          "tokens.dark.css",
          "tokens.high-contrast.css",
          "tokens.light.css",
        ]);
      } finally {
        rmSync(base, { recursive: true, force: true });
      }
    },
  );
});
