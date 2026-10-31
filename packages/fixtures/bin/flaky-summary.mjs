// E10-Q02 (C-9.3): writes the Playwright JSON report's counts to the GitHub job summary, so a test
// that passed only on its retry (`flaky`) is visible on the PR rather than hidden by a green check.
// Run from the package directory after `playwright test`; CV_LANE names the lane in the line.
import { appendFileSync, existsSync, readFileSync } from "node:fs";

const REPORT = "playwright-report/results.json";
const lane = process.env.CV_LANE ?? "e2e";
const line = existsSync(REPORT)
  ? (({ expected, unexpected, flaky, skipped }) =>
      `${lane}: ${flaky} flaky (passed on retry), ${unexpected} failed, ${expected} passed, ${skipped} skipped`)(
      JSON.parse(readFileSync(REPORT, "utf8")).stats,
    )
  : `${lane}: no JSON report (the suite did not run to the end)`;
console.log(line);
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${line}\n`);
