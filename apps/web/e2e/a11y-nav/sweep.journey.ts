import { openScreen } from "../a11y/open";
import { expect, test } from "./fixtures";
import { MOUNTED, trapLimit } from "./screens.support";
import { checkNoTrap } from "./trap";

// E47-TC-121 (sweep: no trap, every stop named) and E47-TC-213 (one h1 and one main per screen).
for (const s of MOUNTED) {
  test(`E47-TC-121/213 ${s.id} ${s.path}: Tab loop closes, every stop is named, one h1 and one main`, async ({
    page,
  }) => {
    await openScreen(page, s);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(page.getByRole("main")).toHaveCount(1);
    const verdict = await checkNoTrap(page, trapLimit(s.id));
    expect(verdict.failures).toEqual([]);
  });
}
