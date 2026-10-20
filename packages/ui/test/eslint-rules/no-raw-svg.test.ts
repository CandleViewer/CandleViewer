import path from "node:path";
import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, it } from "vitest";
import noRawSvg from "../../eslint-rules/no-raw-svg.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester({
  languageOptions: {
    parser: tseslint.parser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});
/** A component file of the package, as ESLint names it from the package root. */
const COMPONENT = path.join(process.cwd(), "src", "components", "PanelHeader.tsx");
const raw = { messageId: "raw", data: { file: "src/components/PanelHeader.tsx" } };

tester.run("no-raw-svg", noRawSvg, {
  valid: [
    { code: "export const Close = () => <CloseIcon />;", filename: COMPONENT },
    { code: 'export const Close = () => <Icon name="close" size="sm" />;', filename: COMPONENT },
    { code: "export const Chart = () => <canvas aria-label='Chart' />;", filename: COMPONENT },
    { code: "export const Logo = () => <Svg />;", filename: COMPONENT },
    { code: 'createElement("div", null, "svg");', filename: COMPONENT },
    { code: 'const tag = "svg";', filename: COMPONENT },
  ],
  invalid: [
    {
      code: 'export const Close = () => <svg viewBox="0 0 24 24"><path d="M18 6 6 18" /></svg>;',
      filename: COMPONENT,
      errors: [raw],
    },
    {
      code: "export const Mark = () => <span><svg aria-hidden='true' /> Note</span>;",
      filename: COMPONENT,
      errors: [raw],
    },
    { code: 'createElement("svg", { viewBox: "0 0 24 24" });', filename: COMPONENT, errors: [raw] },
    { code: "React.createElement('svg');", filename: COMPONENT, errors: [raw] },
    { code: "jsx(`svg`, {});", filename: COMPONENT, errors: [raw] },
  ],
});
