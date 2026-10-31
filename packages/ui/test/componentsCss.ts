import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const UI_ROOT = resolve(import.meta.dirname, "..");

/**
 * `components.css` as the package ships it (apps import `@candleviewer/ui/components.css`): the real
 * `scripts/copy-css.mjs` run on a copy of the package's CSS in a temp directory, so no test writes the `dist/`
 * that `theme/css-export.test.ts` builds and reads.
 */
export function shippedComponentsCss(): string {
  const base = mkdtempSync(join(tmpdir(), "cv-components-css-"));
  try {
    for (const dir of ["scripts", "src/theme", "src/components"])
      mkdirSync(join(base, dir), { recursive: true });
    copyFileSync(join(UI_ROOT, "scripts/copy-css.mjs"), join(base, "scripts/copy-css.mjs"));
    copyFileSync(join(UI_ROOT, "src/theme/theme.css"), join(base, "src/theme/theme.css"));
    for (const name of readdirSync(join(UI_ROOT, "src/components"))) {
      if (name.endsWith(".css"))
        copyFileSync(join(UI_ROOT, "src/components", name), join(base, "src/components", name));
    }
    execFileSync(process.execPath, [join(base, "scripts/copy-css.mjs"), "--no-tokens"], {
      cwd: base,
      stdio: "pipe",
    });
    return readFileSync(join(base, "dist/components.css"), "utf-8");
  } finally {
    rmSync(base, { recursive: true, force: true });
  }
}

/** The component CSS files Storybook's preview imports, in its import order (`.storybook/theme-bundles.ts`). */
export function storybookComponentCss(): string[] {
  const bundles = readFileSync(join(UI_ROOT, ".storybook/theme-bundles.ts"), "utf-8");
  return [...bundles.matchAll(/^import "\.\.\/src\/components\/([\w-]+\.css)";$/gm)].map(
    (match) => match[1] ?? "",
  );
}

/** One component CSS file's text, as copy-css reads it. */
export const componentCss = (name: string): string =>
  readFileSync(join(UI_ROOT, "src/components", name), "utf-8");

/** Every component CSS file the package has. */
export const componentCssFiles = (): string[] =>
  readdirSync(join(UI_ROOT, "src/components")).filter((name) => name.endsWith(".css"));
