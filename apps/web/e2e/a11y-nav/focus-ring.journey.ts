import { openScreen } from "../a11y/open";
import { assertFocusIndicator } from "./focusVisibility";
import { expect, test } from "./fixtures";
import { MOUNTED, trapLimit } from "./screens.support";

// E47-TC-117 on the mounted surfaces: every Tab stop shows a focus ring of at least 3:1 against its background
// (the token linter's contrastRatio). SCR-030, SCR-050 and SCR-063 are not mounted (see unmounted.journey.ts).
for (const s of MOUNTED) {
  test(`E47-TC-117 ${s.id} ${s.path}: every focus stop has a ring of at least 3:1`, async ({
    page,
  }) => {
    await openScreen(page, s);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    const weak: string[] = [];
    for (let i = 0; i < trapLimit(s.id); i++) {
      await page.keyboard.press("Tab");
      if (await page.evaluate(() => document.activeElement === document.body)) break;
      const ring = await assertFocusIndicator(page);
      if (!ring.ok) weak.push(`stop ${i + 1}: ratio ${ring.ratio?.toFixed(2) ?? "none"}`);
    }
    expect(weak).toEqual([]);
  });
}
