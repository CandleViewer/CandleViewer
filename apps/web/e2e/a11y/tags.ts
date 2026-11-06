/**
 * The axe rule tags that the a11y gate's tagged scans select (#3700): levels A and AA of WCAG
 * 2.0, 2.1 and 2.2 (C-14.1). The list lives in `@candleviewer/fixtures/e2e` (`axeTags.ts`), so the
 * Electron smoke scans with it too; this path is the web specs' entry, and
 * `test/e2e-axe-tags.test.ts` pins the list.
 */
export { AXE_GATE_TAGS } from "@candleviewer/fixtures/e2e";
