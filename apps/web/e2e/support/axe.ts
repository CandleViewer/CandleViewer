import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { AXE_GATE_TAGS } from "../a11y/tags";

/**
 * The serious and critical axe violations (WCAG 2.2 A and AA tags) of the page as it is now, as `id: help`
 * lines: `expect(await seriousAxe(page)).toEqual([])`. The one tagged scan the E09-Q02 specs call
 * (`test/e2e-axe-tags.test.ts` pins its site). `include` scopes the scan to one part of the page (E24-Q02's panes).
 */
export async function seriousAxe(
  page: Page,
  opts: { readonly include?: string } = {},
): Promise<string[]> {
  const builder = new AxeBuilder({ page });
  if (opts.include !== undefined) builder.include(opts.include);
  const res = await builder.withTags([...AXE_GATE_TAGS]).analyze();
  return res.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help}`);
}
