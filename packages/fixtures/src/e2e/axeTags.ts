/**
 * The axe rule tags that the a11y gate's tagged scans select (#3700). C-14.1's target is WCAG 2.2
 * AA, and axe tags each rule with the version and level of its own success criterion only, so the
 * list needs levels A and AA of WCAG 2.0, 2.1 and 2.2. axe-core 4.14 has no `wcag22a` rule yet;
 * the tag is listed so a later one gates when it lands. It lives here, beside the stubs both e2e
 * suites share (the `./e2e` entry), so the Electron smoke scans with the web gate's list (E29-S01
 * #911); `apps/web/test/e2e-axe-tags.test.ts` pins it through `apps/web/e2e/a11y/tags.ts`.
 */
export const AXE_GATE_TAGS: readonly string[] = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22a",
  "wcag22aa",
];
