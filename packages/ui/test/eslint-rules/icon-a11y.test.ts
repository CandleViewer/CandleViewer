import { readFileSync } from "node:fs";
import { Linter, RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";
import { iconBesideTextHidden, iconOnlyControlLabel } from "../../eslint-rules/icon-a11y.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const languageOptions = {
  parser: tseslint.parser,
  parserOptions: { ecmaFeatures: { jsx: true } },
};
const tester = new RuleTester({ languageOptions });
const unlabelled = (control: string, label = "an aria-label (or aria-labelledby)") => ({
  messageId: "unlabelled",
  data: { control, label },
});
const exposed = (icon: string) => ({ messageId: "exposed", data: { icon } });

tester.run("icon-only-control-label", iconOnlyControlLabel, {
  valid: [
    '<button type="button" aria-label="Close panel"><CloseIcon /></button>;',
    '<button aria-labelledby="close-hint"><CloseIcon /></button>;',
    "<a href={url} aria-label={t('docs')}><ExternalLinkIcon /></a>;",
    '<IconButton icon="close" label="Close panel" />;',
    '<IconButton icon="close" aria-label="Close panel" />;',
    "<button><DownloadIcon /> Download</button>;",
    "<button><DownloadIcon />{'Download'}</button>;",
    '<button><CloseIcon /><span className="sr-only">Close</span></button>;',
    '<Button iconLeft="close">Close</Button>;',
    "<button {...props}><CloseIcon /></button>;",
    "<div><CloseIcon /></div>;",
    "<button>{label}</button>;",
    "<button />;",
    '<div role="presentation"><CloseIcon /></div>;',
  ],
  invalid: [
    { code: "<button><CloseIcon /></button>;", errors: [unlabelled("button")] },
    {
      code: '<button type="button">\n  {/* dismiss */}\n  <CloseIcon />\n</button>;',
      errors: [unlabelled("button")],
    },
    { code: '<button aria-label=""><CloseIcon /></button>;', errors: [unlabelled("button")] },
    { code: "<button aria-label={' '}><CloseIcon /></button>;", errors: [unlabelled("button")] },
    // The control carries the name, not the icon inside it (brief §5).
    { code: '<button><CloseIcon aria-label="Close" /></button>;', errors: [unlabelled("button")] },
    { code: '<a href="/docs"><HelpIcon /></a>;', errors: [unlabelled("a")] },
    { code: "<Button><SearchIcon /><FilterIcon /></Button>;", errors: [unlabelled("Button")] },
    { code: "<Toolbar.Button><PinIcon /></Toolbar.Button>;", errors: [unlabelled("Button")] },
    { code: '<div role="button" tabIndex={0}><CloseIcon /></div>;', errors: [unlabelled("div")] },
    { code: '<span role="menuitem"><Icon name="copy" /></span>;', errors: [unlabelled("span")] },
    { code: "<button><svg aria-hidden='true' /></button>;", errors: [unlabelled("button")] },
    {
      code: '<IconButton icon="close" />;',
      errors: [unlabelled("IconButton", "a label (its aria-label) or an aria-label")],
    },
    {
      code: '<IconButton icon="close" label="" />;',
      errors: [unlabelled("IconButton", "a label (its aria-label) or an aria-label")],
    },
  ],
});

tester.run("icon-beside-text-hidden", iconBesideTextHidden, {
  valid: [
    "<button><DownloadIcon /> Download</button>;",
    '<button><DownloadIcon aria-hidden="true" /> Download</button>;',
    "<span><WarningIcon aria-hidden /> Degraded</span>;",
    '<span><svg aria-hidden="true" /> Note</span>;',
    "<span><svg aria-hidden={true} />{'Note'}</span>;",
    '<button aria-label="Close panel"><CloseIcon /></button>;',
    '<p><WarningIcon aria-label="Warning" /></p>;',
    "<li><CloseIcon aria-hidden={hidden} aria-label={name} /> Close</li>;",
    '<li><Icon name="close" label="Close" /> Close</li>;',
    '<p>{count}<WarningIcon aria-label="Warning" /></p>;',
    "<p><CloseIcon {...iconProps} /> Close</p>;",
    '<>{cond && <CloseIcon aria-label="Close" />}</>;',
  ],
  invalid: [
    {
      code: '<button><CloseIcon aria-label="Close" /> Close</button>;',
      errors: [exposed("CloseIcon")],
    },
    {
      code: '<button><CloseIcon aria-labelledby="close-text" /><span id="close-text">Close</span></button>;',
      errors: [exposed("CloseIcon")],
    },
    {
      code: "<span><WarningIcon aria-hidden={false} />Degraded</span>;",
      errors: [exposed("WarningIcon")],
    },
    {
      code: '<span><WarningIcon aria-hidden="false" />{"Degraded"}</span>;',
      errors: [exposed("WarningIcon")],
    },
    {
      code: '<span><InfoIcon role="img" /> <strong>Note</strong></span>;',
      errors: [exposed("InfoIcon")],
    },
    {
      code: "<>\n  <InfoIcon aria-label='Info' />\n  {`Note`}\n</>;",
      errors: [exposed("InfoIcon")],
    },
    {
      code: '<span><Icon name="warning" decorative={false} label="Warning" /> Degraded</span>;',
      errors: [exposed("Icon")],
    },
    { code: "<span><svg /> Note</span>;", errors: [exposed("svg")] },
  ],
});

describe("the icon a11y gate fixture", () => {
  it("fails icon-only-control-label as it fails axe's button-name (E05-T06 Gherkin)", () => {
    const fixture = new URL(
      "../../.storybook/__fixtures__/IconOnlyButton.stories.tsx",
      import.meta.url,
    );
    const messages = new Linter().verify(
      readFileSync(fixture, "utf-8"),
      [
        {
          files: ["**/*.tsx"],
          languageOptions,
          plugins: { candleviewer: { rules: { "icon-only-control-label": iconOnlyControlLabel } } },
          rules: { "candleviewer/icon-only-control-label": "error" },
        },
      ],
      { filename: "IconOnlyButton.stories.tsx" },
    );
    expect(messages.map(({ ruleId, message }) => [ruleId, message])).toEqual([
      [
        "candleviewer/icon-only-control-label",
        expect.stringContaining("Icon-only <button> has no accessible name"),
      ],
    ]);
  });
});
