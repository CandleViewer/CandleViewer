import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { AXE_GATE_TAGS } from "../a11y/tags";

/**
 * The serious and critical axe violations (WCAG 2.2 A and AA tags) of the page as it is now, as `id: help`
 * lines: `expect(await seriousAxe(page)).toEqual([])`. The one tagged scan the E09-Q02 specs call
 * (`test/e2e-axe-tags.test.ts` pins its site).
 */
export async function seriousAxe(page: Page): Promise<string[]> {
  const res = await new AxeBuilder({ page }).withTags([...AXE_GATE_TAGS]).analyze();
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help}`);
}
