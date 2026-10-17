// @vitest-environment node
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { createServer, type ViteDevServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const WEB_ROOT = resolve(import.meta.dirname, "..");
const UI_ROOT = resolve(WEB_ROOT, "../../packages/ui");
const UI_DIST = join(UI_ROOT, "dist");
const FILES = ["theme.css", "tokens.dark.css", "tokens.light.css", "tokens.high-contrast.css"];
const same = (a: string, b: string): boolean =>
  a.replaceAll("\\", "/").toLowerCase() === b.replaceAll("\\", "/").toLowerCase();

// The exports point at build output, but some lanes run `test` before any build (the a11y-axe lane, the cold
// `test:cov`). When the CSS is missing, make it with the two scripts `pnpm --filter @candleviewer/ui build`
// runs for it; both are deterministic and take about a second.
beforeAll(() => {
  if (FILES.every((file) => existsSync(join(UI_DIST, file)))) return;
  for (const script of ["build-tokens.mjs", "copy-css.mjs"]) {
    execFileSync(process.execPath, [join(UI_ROOT, "scripts", script)], {
      cwd: UI_ROOT,
      stdio: "pipe",
    });
  }
}, 60_000);

// Resolves the way the app's bundler does, from the real config files (their aliases included). Without an
// exact alias the specifier becomes `packages/ui/src/index.ts/<file>`.
describe.each(["vite.config.ts", "vitest.config.mjs"])(
  "@candleviewer/ui CSS exports via %s",
  (config) => {
    let server: ViteDevServer;
    beforeAll(async () => {
      server = await createServer({
        root: WEB_ROOT,
        configFile: resolve(WEB_ROOT, config),
        appType: "custom",
        logLevel: "silent",
        server: { middlewareMode: true, watch: null },
        optimizeDeps: { noDiscovery: true, include: [] },
      });
    });
    afterAll(() => server.close());

    it.each(FILES)(
      "resolves @candleviewer/ui/%s to the built file of this checkout",
      async (file) => {
        const importer = resolve(WEB_ROOT, "src/main.tsx");
        const resolved = await server.pluginContainer.resolveId(
          `@candleviewer/ui/${file}`,
          importer,
        );
        const hint = "build the package first: pnpm --filter @candleviewer/ui build";
        expect(same(resolved?.id ?? "", join(UI_DIST, file)), `${resolved?.id} (${hint})`).toBe(
          true,
        );
        expect(existsSync(join(UI_DIST, file)), hint).toBe(true);
      },
    );
  },
);
