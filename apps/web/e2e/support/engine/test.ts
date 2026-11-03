// E11-Q02 (#444): the engine suite's `test`: a `harness` page object, and every test runs under the
// shared egress guard (C-13.5): no non-loopback request leaves the page. (The Electron leg adds an
// `openShell` option in the next slice.)
import { guardContextEgress } from "@candleviewer/fixtures/e2e";
import { expect, test as base } from "@playwright/test";
import { EngineHarness } from "./harness";

export { expect };

export const test = base.extend<{ harness: EngineHarness; egress: undefined }>({
  egress: [
    async ({ context }, use) => {
      const guard = await guardContextEgress(context);
      await use(undefined);
      expect(guard.hits(), "the page sent a request past the loopback interface").toEqual([]);
    },
    { auto: true },
  ],
  harness: async ({ page, baseURL }, use) => {
    if (baseURL === undefined) throw new Error("engine e2e: baseURL is not set");
    await use(new EngineHarness(page, baseURL));
  },
});
