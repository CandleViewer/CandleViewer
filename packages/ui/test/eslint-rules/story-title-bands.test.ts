import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, it } from "vitest";
import storyTitleBands, { STORY_BANDS } from "../../eslint-rules/story-title-bands.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester({
  languageOptions: {
    parser: tseslint.parser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});
const allowed = STORY_BANDS.map((band) => `${band}/*`).join(", ");
const band = (title: string) => ({ messageId: "band", data: { title, allowed } });
const missing = { messageId: "missing", data: { allowed } };

tester.run("story-title-bands", storyTitleBands, {
  valid: [
    'export default { title: "Atoms/Button" };',
    'const meta: Meta = { title: "Trading/Order ticket/Default" };\nexport default meta;',
    'const meta = { title: "RuleEngine/Node" } satisfies Meta;\nexport default meta;',
    'export default { title: "ChartEngine/Axis" } as Meta;',
    "export default { title: `Foundations/Theme runtime` };",
    'export default { "title": "Molecules/Tabs", component: Tabs };',
    'const meta = { title: "Organisms/Dialog" };\nexport default meta as Meta;',
  ],
  invalid: [
    { code: 'export default { title: "Theme/Runtime" };', errors: [band("Theme/Runtime")] },
    {
      code: 'export default { title: "Scaffold/Placeholder" };',
      errors: [band("Scaffold/Placeholder")],
    },
    { code: 'export default { title: "atoms/Button" };', errors: [band("atoms/Button")] },
    { code: 'export default { title: "Atoms" };', errors: [band("Atoms")] },
    { code: 'export default { title: "Atoms//Button" };', errors: [band("Atoms//Button")] },
    {
      code: 'const meta = { title: "Widgets/Button" };\nexport default meta;',
      errors: [band("Widgets/Button")],
    },
    { code: "export default { component: Button };", errors: [missing] },
    { code: "export default { title: `Atoms/${name}` };", errors: [missing] },
    { code: "const title = 'Atoms/Button';\nexport default { title };", errors: [missing] },
    { code: "export default makeMeta();", errors: [missing] },
    { code: "export const Default = {};", errors: [missing] },
  ],
});
