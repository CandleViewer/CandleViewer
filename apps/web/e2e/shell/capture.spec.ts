import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { captureTwice, prepareCapture, VIEWPORTS } from "@candleviewer/fixtures/e2e";
import { json, stubSession } from "../support/api";
import { badge, expect, test } from "./fixtures";

// E10-Q02 screenshot corpus (plan step SC-1): shell surfaces × theme × density × viewport, with a
// frozen clock, no motion and seeded stubs. Each capture is taken twice and must match byte for
// byte; the PNGs are written under the test's output dir and uploaded as a CI artefact (no committed
// baseline: E49 is the first consumer). It runs in the normal e2e-web shards; `@capture` lets a
// local run select it (`--grep @capture`).

const SURFACES = ["/terminal/last", "/settings/appearance", "/risk"] as const; // shell, settings, 403
const THEMES = [
  ["dark", { theme: "dark" }],
  ["light", { theme: "light" }],
  ["high-contrast", { theme: "dark", high_contrast: true }],
] as const;
const DENSITIES = ["compact", "comfortable"] as const;

for (const [themeName, theme] of THEMES)
  for (const density of DENSITIES)
    test(`@capture @plan-SC-1 ${themeName} ${density}`, async ({ page }, testInfo) => {
      await prepareCapture(page);
      await stubSession(page, { role: "viewer" });
      await page.route("**/api/v1/me/preferences", (r) =>
        r.fulfill(json({ appearance: { ...theme, density } })),
      );
      for (const viewport of VIEWPORTS) {
        await page.setViewportSize(viewport);
        for (const surface of SURFACES) {
          await page.goto(surface);
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          await expect(badge(page)).toBeVisible();
          const png = await captureTwice(page);
          const name = `${themeName}-${density}-${viewport.name}${surface.replaceAll("/", "_")}.png`;
          // a file under the test's output dir (CI uploads `*/corpus/*.png`), attached by path
          const file = testInfo.outputPath("corpus", name);
          await mkdir(dirname(file), { recursive: true });
          await writeFile(file, png);
          await testInfo.attach(name, { path: file, contentType: "image/png" });
        }
      }
    });
