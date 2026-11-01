import { test as base, expect, type Page } from "@playwright/test";
import { guardContextEgress } from "@candleviewer/fixtures/e2e";

// E10-Q02 shell suite: every test runs behind the egress guard (C-13.5, C-13.7). The guard aborts
// any non-loopback request and the test fails on it after its body has run.
export const test = base.extend<{ egressGuard: void }>({
  egressGuard: [
    async ({ context }, use) => {
      const guard = await guardContextEgress(context);
      await use();
      expect(guard.hits(), "a request left the loopback interface (C-13.5)").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };

/** The DEMO/LIVE badge in the top bar, by its accessible name (E10-S01). */
export const badge = (page: Page) =>
  page.getByRole("banner").getByRole("img", { name: "Trading environment: Demo" });
