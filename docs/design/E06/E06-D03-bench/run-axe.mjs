// Throwaway axe-core runner for E06-D03. No network: local file:// pages, the workspace's installed
// @axe-core/playwright + playwright-core (resolved through apps/web) and an explicit Chromium binary.
// Usage: node run-axe.mjs <workspace-root> <chromium-executable> <out.json>
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const [root, executablePath, out] = process.argv.slice(2);
const web = createRequire(resolve(root, "apps/web/package.json"));
const { AxeBuilder } = web("@axe-core/playwright");
const pw = createRequire(
  createRequire(web.resolve("@playwright/test/package.json")).resolve("playwright/package.json"),
);
const { chromium } = pw("playwright-core");
const here = dirname(fileURLToPath(import.meta.url));

const pages = [
  // The benchmark page after one short static run, so the 200-row table is populated.
  {
    file: "mirror-bench.html",
    query: "?ms=300&reps=1&only=200r%20diff%20static",
    ready: (p) =>
      p.waitForFunction(
        () => document.getElementById("out").textContent.startsWith("RESULT"),
        null,
        { timeout: 60_000 },
      ),
  },
  // Static realisation of the D4/D6 structure: roles, names, live region, table semantics.
  { file: "mirror-structure-fixture.html", query: "", ready: (p) => p.waitForLoadState("load") },
];

const browser = await chromium.launch({ headless: true, executablePath, args: ["--disable-gpu"] });
const context = await browser.newContext(); // @axe-core/playwright refuses the default context
const runs = [];
for (const spec of pages) {
  const page = await context.newPage();
  await page.goto(pathToFileURL(resolve(here, spec.file)).href + spec.query);
  await spec.ready(page);
  // resultTypes keeps full node detail for violations/incomplete; passes keep one node each.
  const result = await new AxeBuilder({ page })
    .options({ resultTypes: ["violations", "incomplete"] })
    .analyze();
  runs.push({ page: spec.file, query: spec.query, result });
  await page.close();
}
await browser.close();
writeFileSync(out, JSON.stringify({ generatedAt: new Date().toISOString(), runs }) + "\n");

const list = (xs) =>
  xs.map((x) => `${x.id}${x.impact ? `(${x.impact})` : ""}×${x.nodes.length}`).join(", ") || "none";
for (const r of runs) {
  const { violations, incomplete, passes, inapplicable, testEngine, testEnvironment } = r.result;
  console.log(
    `${r.page}: violations ${list(violations)} | incomplete ${list(incomplete)} | passes ${passes.length} | inapplicable ${inapplicable.length} | axe-core ${testEngine.version} | ${testEnvironment.userAgent}`,
  );
}
