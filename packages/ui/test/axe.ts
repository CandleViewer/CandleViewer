import { createRequire } from "node:module";

type Violation = { id: string; impact?: string | null };
type Axe = { run: (context: object, options?: object) => Promise<{ violations: Violation[] }> };

/** The axe-core the Storybook a11y addon runs, so a unit test and the story gate share one engine. */
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

/** The serious and critical violations in `context` (the gate's levels); contrast is the contrast gate's. */
export async function seriousViolations(context: object): Promise<Violation[]> {
  const { violations } = await axe.run(context, {
    rules: { "color-contrast": { enabled: false } },
  });
  return violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}
