// E09-D08 bench runner (design evidence, not product code): drives the headless Chromium that
// Playwright installed over Playwright's own protocol, local files only, no network.
// Usage: node run-bench.mjs <chrome-headless-shell> [ms-per-window=500] [reps=3]
// Env: PLAYWRIGHT_CORE=<dir of the playwright-core package> when it is not resolvable from here
// (e.g. the pnpm store entry); RES=1280x800,2560x1440 selects the viewports.
// Writes bench-results-<date>-<WxH>.json beside this file: one `rows` entry per line (compact).
/* global process, console */
import { writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const [chrome, ms = "500", reps = "3"] = process.argv.slice(2);
if (!chrome) {
  console.error("usage: node run-bench.mjs <chrome-headless-shell> [ms] [reps]");
  process.exit(2);
}
const pw = process.env.PLAYWRIGHT_CORE;
const { chromium } = await import(
  pw ? pathToFileURL(join(pw, "index.mjs")).href : "playwright-core"
);
const here = dirname(fileURLToPath(import.meta.url));
const html = pathToFileURL(join(here, "auth-motion-bench.html")).href;
const date = new Date().toISOString().slice(0, 10);
const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: ["--no-sandbox"],
});
for (const res of (process.env.RES || "1280x800,2560x1440").split(",")) {
  const [w, h] = res.split("x").map(Number);
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  await page.goto(`${html}?ms=${ms}&reps=${reps}`);
  await page.waitForFunction(
    () => document.getElementById("out").textContent.startsWith("RESULT"),
    null,
    { timeout: 0, polling: 1000 },
  );
  const text = await page.evaluate(() => document.getElementById("out").textContent.slice(6));
  const { host, rows } = JSON.parse(text);
  host.binary = basename(chrome);
  host.date = date;
  const out = `{\n"host": ${JSON.stringify(host)},\n"rows": [\n${rows
    .map((r) => JSON.stringify(r))
    .join(",\n")}\n]\n}\n`;
  const file = join(here, `bench-results-${date}-${res}.json`);
  writeFileSync(file, out);
  console.log(
    `${res}: ${rows.length} rows -> ${basename(file)} (${host.ua}; ${host.cores} cores; ${host.gl})`,
  );
  await page.close();
}
await browser.close();
