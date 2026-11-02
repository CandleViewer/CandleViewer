import { test as base } from "@playwright/test";
import { badge, expect, test as guarded } from "../shell/fixtures";
import { seriousAxe } from "../support/axe";

// E49-Q01 (#1335) GA regression pack fixtures. Every web pack spec takes `test` from here, which
// tools/ga/health.py checks (BQ-07). In the nightly pack run only (CV_E2E_GA=1), each test runs
// behind the egress guard (any request past the loopback interface fails it, C-13.5) and its
// final screen gets the a11y gate's tagged axe scan (BQ-14): each serious or critical violation
// becomes a `ga-axe-p2` annotation that tools/ga/report.py counts per area at P2; it fails
// nothing, since the a11y gate stays the blocker.
//
// The PR lane is unchanged (#1335 code lens): outside the pack run the two exports are exactly
// what each spec imported before it joined the pack.
// - `test`: the shell suite's fixture (shell/fixtures.ts), whose egress guard is already the PR
//   lane's standard for the shell specs;
// - `packTest`: plain `@playwright/test`, for the specs that ran without a guard in the PR lane
//   (auth, hotkeys, invites, motion); they import it as `{ packTest as test }`.
const PACK_RUN = process.env["CV_E2E_GA"] === "1";

const withAxe = guarded.extend<{ gaAxe: void }>({
  gaAxe: [
    async ({ page }, use, testInfo) => {
      await use();
      if (testInfo.status !== "passed" || page.isClosed()) return;
      try {
        for (const violation of await seriousAxe(page))
          testInfo.annotations.push({ type: "ga-axe-p2", description: violation });
      } catch (error) {
        // A page left mid-navigation (or on about:blank) cannot be scanned: record that instead.
        testInfo.annotations.push({ type: "ga-axe-skipped", description: String(error) });
      }
    },
    { auto: true },
  ],
});

/** Shell-guarded in every lane; plus the per-scenario axe scan in the pack run. */
export const test: typeof guarded = PACK_RUN ? withAxe : guarded;
/** Plain `@playwright/test` in the PR lane; guarded and axe-scanned in the pack run. */
export const packTest: typeof base = PACK_RUN ? withAxe : base;
export { badge, expect };
