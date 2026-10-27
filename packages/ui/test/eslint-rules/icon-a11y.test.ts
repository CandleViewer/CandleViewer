import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, it } from "vitest";
import { iconLabelRequired } from "../../eslint-rules/icon-a11y.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester({
  languageOptions: { parser: tseslint.parser, parserOptions: { ecmaFeatures: { jsx: true } } },
});
const unlabelled = [{ messageId: "unlabelled" }];

tester.run("icon-label-required", iconLabelRequired, {
  valid: [
    '<Icon name="check" />;',
    '<Icon name="check" decorative />;',
    '<Icon name="check" decorative={true} />;',
    '<Icon name="warning" decorative={false} label="Order rejected" />;',
    "<Icon name='warning' decorative={false} label={t('rejected')} />;",
    '<Icon name="warning" decorative={false} {...rest} />;',
    '<Icon name="warning" decorative={flag} />;',
    "<Other decorative={false} />;",
    '<Ui.Icon name="check" decorative={false} />;',
  ],
  invalid: [
    { code: '<Icon name="check" decorative={false} />;', errors: unlabelled },
    { code: '<Icon name="check" decorative={false} label="" />;', errors: unlabelled },
    { code: '<Icon name="check" decorative={false} label="  " />;', errors: unlabelled },
    { code: '<Icon name="check" decorative={false} label />;', errors: unlabelled },
    { code: '<Icon name="check" decorative={false} label={undefined} />;', errors: unlabelled },
  ],
});
