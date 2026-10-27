import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, it } from "vitest";
import {
  iconBesideTextHidden,
  iconLabelRequired,
  iconOnlyControlLabel,
} from "../../eslint-rules/icon-a11y.mjs";

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

const iconButton = [{ messageId: "iconButton" }];
const control = (tag: string) => [{ messageId: "control", data: { tag } }];

tester.run("icon-only-control-label", iconOnlyControlLabel, {
  valid: [
    '<IconButton icon="close" label="Close panel" />;',
    "<IconButton icon='close' label={t('close')} />;",
    '<IconButton icon="close" aria-labelledby="panel-title" />;',
    "<IconButton {...shared(args)} />;",
    // A spread after `label` may set it.
    '<IconButton icon="close" label="" {...rest} />;',
    '<button type="button" aria-label="Close"><Icon name="close" /></button>;',
    '<button type="button" aria-labelledby="t"><Icon name="close" /></button>;',
    '<a href="/help" aria-label="Help"><Icon name="info" /></a>;',
    "<button type='button' aria-label={label}><Icon name='close' /></button>;",
    '<button {...rest}><Icon name="close" /></button>;',
    // Not icon-only: visible text, a computed child or another element names it, or nothing is in it.
    '<button type="button"><Icon name="check" /> Save</button>;',
    '<button type="button"><Icon name="check" />{label}</button>;',
    '<button type="button"><Spinner /></button>;',
    '<button type="button" />;',
    "<button type='button'>\n</button>;",
    '<button type="button">{open ? null : false}</button>;',
    // Nor is a branch, an `||` or a fragment that may render something else.
    '<button type="button">{open ? <Icon name="chevron-down" /> : "More"}</button>;',
    '<button type="button">{open ? <Icon name="close" /> : label}</button>;',
    '<button type="button">{open ? <Icon name="close" /> : null} Close</button>;',
    '<button type="button">{label || <Icon name="close" />}</button>;',
    '<button type="button"><><Icon name="check" /> Save</></button>;',
    // Not a control, or not the plain JSX name.
    '<span><Icon name="close" /></span>;',
    '<Ui.IconButton icon="close" />;',
  ],
  invalid: [
    {
      code: '<IconButton icon="close" />;',
      errors: [
        {
          message:
            "<IconButton> is icon-only, so it needs a name: a non-blank `label`, which becomes its `aria-label`, or `aria-labelledby` (CMP-002, 16-design-system-brief.md §5). Its `label` overwrites an `aria-label` prop.",
        },
      ],
    },
    { code: '<IconButton icon="close" label="" />;', errors: iconButton },
    { code: '<IconButton icon="close" label="  " aria-labelledby="" />;', errors: iconButton },
    { code: '<IconButton icon="close" label={undefined} />;', errors: iconButton },
    // IconButton renders `aria-label={label}` after its rest props: an `aria-label` prop names nothing.
    { code: '<IconButton icon="close" aria-label="Close" />;', errors: iconButton },
    // A static `label` after the spread is the one it renders.
    { code: '<IconButton {...rest} icon="close" label="" />;', errors: iconButton },
    {
      code: '<button type="button"><Icon name="close" /></button>;',
      errors: [
        {
          message:
            "An icon-only <button> needs a name of its own: a non-blank `aria-label` or `aria-labelledby`, not `title` (16-design-system-brief.md §5). The <Icon> in it stays aria-hidden.",
        },
      ],
    },
    { code: '<a href="/help"><Icon name="info" /></a>;', errors: control("a") },
    // A `title` is no name here: the control carries aria-label (16-design-system-brief.md §5).
    { code: '<a href="/help" title="Help"><Icon name="info" /></a>;', errors: control("a") },
    {
      code: '<button aria-label=" " aria-labelledby=""><Icon name="close" /></button>;',
      errors: control("button"),
    },
    { code: "<button>\n  <Icon name='close' />\n</button>;", errors: control("button") },
    { code: '<button>{/* dismiss */}<Icon name="close" /></button>;', errors: control("button") },
    {
      code: '<button><Icon name="arrow-up" /><Icon name="arrow-down" /></button>;',
      errors: control("button"),
    },
    // Icons through `{…}`, `c && …`, `c ? … : …` and `<>…</>` are still all it holds.
    { code: '<button>{open && <Icon name="close" />}</button>;', errors: control("button") },
    {
      code: '<button>{open ? <Icon name="chevron-down" /> : <Icon name="chevron-right" />}</button>;',
      errors: control("button"),
    },
    { code: '<button><><Icon name="close" /></></button>;', errors: control("button") },
    // A branch that renders nothing (null, undefined, a boolean) leaves the icon alone in it.
    { code: '<button>{open ? <Icon name="close" /> : null}</button>;', errors: control("button") },
    {
      code: '<button>{busy ? undefined : <Icon name="check" />}</button>;',
      errors: control("button"),
    },
    { code: '<a href="/help">{busy ? false : <Icon name="info" />}</a>;', errors: control("a") },
  ],
});

const besideText = [{ messageId: "besideText" }];

tester.run("icon-beside-text-hidden", iconBesideTextHidden, {
  valid: [
    '<p><Icon name="check" /> Saved</p>;',
    '<p><Icon name="check" decorative /> Saved</p>;',
    '<p>\n  <Icon name="lock" decorative={false} label="Locked" />\n</p>;',
    '<span><Icon name="lock" decorative={false} label="Locked" /><Badge /></span>;',
    'const icon = <Icon name="lock" decorative={false} label="Locked" />;',
    // A prop is not a child, so the element's text is not beside it.
    '<Tip content={<Icon name="lock" decorative={false} label="Locked" />}>Locked</Tip>;',
    // Computed and spread props are trusted; only the plain JSX name `Icon` is matched.
    '<p><Icon name="lock" decorative={flag} label="Locked" /> Locked</p>;',
    '<p><Icon {...glyph} decorative={false} label="Locked" /> Locked</p>;',
    "<p><Other decorative={false} /> Locked</p>;",
  ],
  invalid: [
    {
      code: '<p><Icon name="lock" decorative={false} label="Locked" /> Locked</p>;',
      errors: [
        {
          message:
            "An <Icon> beside visible text is decorative: drop `decorative={false}` and its `label`, so it stays aria-hidden and the text alone names it (16-design-system-brief.md §5, CMP-019).",
        },
      ],
    },
    {
      code: '<button>Delete <Icon name="danger" decorative={false} label="Danger" /></button>;',
      errors: besideText,
    },
    {
      code: '<>Locked <Icon name="lock" decorative={false} label="Locked" /></>;',
      errors: besideText,
    },
    {
      code: '<li>\n  <Icon name="warning" decorative={false} label="Warning" />\n  Margin low\n</li>;',
      errors: besideText,
    },
    // Through `{…}`, `c && …` and `c ? … : …` it still renders beside the text.
    {
      code: '<p>{locked && <Icon name="lock" decorative={false} label="Locked" />} Locked</p>;',
      errors: besideText,
    },
    {
      code: '<p>{locked ? <Icon name="lock" decorative={false} label="Locked" /> : null} Locked</p>;',
      errors: besideText,
    },
  ],
});
