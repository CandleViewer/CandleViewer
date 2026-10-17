// @vitest-environment node
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { createServer, type ViteDevServer } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const WEB_ROOT = resolve(import.meta.dirname, "..");
const UI_DIST = resolve(WEB_ROOT, "../../packages/ui/dist");
const FILES = ["theme.css", "tokens.dark.css", "tokens.light.css", "tokens.high-contrast.css"];
const same = (a: string, b: string): boolean =>
  a.replaceAll("\\", "/").toLowerCase() === b.replaceAll("\\", "/").toLowerCase();

// Resolves the way the app's bundler does, from the real config files (their aliases included). Without an
// exact alias the specifier becomes `packages/ui/src/index.ts/<file>`; without a build there is no `dist/`.
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
