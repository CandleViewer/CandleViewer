// @vitest-environment node
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const UI_ROOT = resolve(import.meta.dirname, "../..");

describe("theme.css package export", () => {
  it("resolves through the package self-reference to the built copy of src/theme/theme.css", () => {
    // The same script tsup runs after a build; `--no-tokens` because the token tests rebuild `build/`.
    execFileSync(process.execPath, [join(UI_ROOT, "scripts/copy-css.mjs"), "--no-tokens"], {
      cwd: UI_ROOT,
    });
    const built = createRequire(import.meta.url).resolve("@candleviewer/ui/theme.css");
    expect(built).toBe(join(UI_ROOT, "dist", "theme.css"));
    const source = readFileSync(join(UI_ROOT, "src/theme/theme.css"), "utf-8");
    expect(readFileSync(built, "utf-8")).toBe(source);
  });
});
