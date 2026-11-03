/* global process, console */
// Gate 2 collector (E47-T02, E47-Q04): Lighthouse accessibility score per screen ->
// reports/a11y/lighthouse.json:
//   {"lighthouse", "chromium", "runnerClass", "scores": {"<SCR-id>": 0..1 | null}, "pending": {"<SCR-id>": why}}
// null = runner failure for that screen, which gates.py reports as A11Y-INFRA (never a score
// failure). A screen the inventory lists as not mounted is `pending <ticket>`: counted, not run.
// The screen list comes from `python -m tools.a11y.gates lighthouse-plan` (tools/a11y/inventory.py).
// Lighthouse stays an exact-version `npx` fetch: its tree adds a licence the SR-136 allowlist does
// not know (parse-cache-control, "BSD") and ~1.4k lockfile lines, so pinning it is a separate decision.
// Usage: node lighthouse.collect.mjs   (expects `vite preview` on :4173, run from apps/web)
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "@playwright/test";

const LH = "lighthouse@12.2.1";
const BASE = process.env.A11Y_BASE_URL ?? "http://127.0.0.1:4173";
const OUT = process.env.A11Y_REPORT_DIR ?? "../../reports/a11y";
const PLAN = JSON.parse(readFileSync(process.env.A11Y_LH_PLAN ?? join(OUT, "lighthouse-plan.json"), "utf8"));

// What produced the scores: the Chromium build and the runner class (a score moves with both).
const browser = await chromium.launch();
const chromiumVersion = browser.version();
await browser.close();
const runnerClass = [
  process.env.RUNNER_ENVIRONMENT ?? "local",
  process.env.ImageOS ?? process.platform,
  process.env.ImageVersion ?? "unknown",
  process.env.RUNNER_ARCH ?? process.arch,
].join(" ");

const scores = {};
const pending = {};
const tmp = mkdtempSync(join(tmpdir(), "lh-"));
for (const { screen: id, path, pending: why } of PLAN.screens) {
  if (why) {
    pending[id] = why;
    continue;
  }
  const file = join(tmp, `${id}.json`);
  try {
    execFileSync(
      "npx",
      [
        "--yes",
        LH,
        `${BASE}${path}`,
        "--only-categories=accessibility",
        "--output=json",
        `--output-path=${file}`,
        "--chrome-flags=--headless=new --no-sandbox",
        "--quiet",
      ],
      {
        env: { ...process.env, CHROME_PATH: process.env.CHROME_PATH ?? chromium.executablePath() },
        stdio: "inherit",
        shell: process.platform === "win32",
        timeout: 120_000,
      },
    );
    scores[id] = JSON.parse(readFileSync(file, "utf8")).categories.accessibility.score ?? null;
  } catch (err) {
    console.error(`lighthouse failed for ${id}: ${err.message}`);
    scores[id] = null;
  }
}
mkdirSync(OUT, { recursive: true });
writeFileSync(
  join(OUT, "lighthouse.json"),
  JSON.stringify(
    { lighthouse: LH.split("@")[1], chromium: chromiumVersion, runnerClass, scores, pending },
    null,
    2,
  ),
);
