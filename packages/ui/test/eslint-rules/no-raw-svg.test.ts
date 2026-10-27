import path from "node:path";
import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, it } from "vitest";
import noRawSvg from "../../eslint-rules/no-raw-svg.mjs";

RuleTester.describe = describe;
RuleTester.it = it;

const tester = new RuleTester({
  languageOptions: { parser: tseslint.parser, parserOptions: { ecmaFeatures: { jsx: true } } },
});
// The rule names a file by its path from ESLint's cwd (RuleTester's is vitest's), so every case
// sits under it and the expected name is the path as written here, wherever the repo lives.
const at = (file: string): string => path.resolve(file);
const raw = (file: string) => [{ messageId: "raw", data: { file } }];
const SVG = '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>;';

tester.run("no-raw-svg", noRawSvg, {
  valid: [
    { code: SVG, filename: at("packages/ui/src/icons/IconSvg.tsx") },
    { code: SVG, filename: at("packages/ui/src/icons/generated/CheckIcon.tsx") },
    { code: '<Icon name="check" />;', filename: at("packages/ui/src/components/Button.tsx") },
    { code: "<Svg />;", filename: at("packages/ui/src/components/Button.tsx") },
    { code: 'const markup = "<svg></svg>";', filename: at("packages/ui/test/icons/Icon.test.tsx") },
  ],
  invalid: [
    {
      code: SVG,
      filename: at("packages/ui/src/components/Leak.tsx"),
      errors: [
        {
          message:
            'Raw <svg> in packages/ui/src/components/Leak.tsx: draw icons with <Icon name="…"> from the icon registry, packages/ui/src/icons/ (16-design-system-brief.md §5); a missing glyph joins registry.ts there, never inline.',
        },
      ],
    },
    // Stories and tests are held to it too: no reason to draw a raw glyph in either.
    {
      code: SVG,
      filename: at("packages/ui/src/components/Leak.stories.tsx"),
      errors: raw("packages/ui/src/components/Leak.stories.tsx"),
    },
    {
      code: SVG,
      filename: at("packages/ui/test/Leak.test.tsx"),
      errors: raw("packages/ui/test/Leak.test.tsx"),
    },
    // The registry is packages/ui/src/icons/ itself: not a look-alike, not another package's icons/.
    {
      code: SVG,
      filename: at("packages/ui/src/icons-legacy/Old.tsx"),
      errors: raw("packages/ui/src/icons-legacy/Old.tsx"),
    },
    {
      code: SVG,
      filename: at("apps/web/src/icons/Glyph.tsx"),
      errors: raw("apps/web/src/icons/Glyph.tsx"),
    },
    // A spread or a computed child does not make it less raw.
    {
      code: "<svg {...glyph}>{shapes}</svg>;",
      filename: at("packages/ui/src/components/Spread.tsx"),
      errors: raw("packages/ui/src/components/Spread.tsx"),
    },
    {
      code: "<span>{open ? <svg /> : <svg />}</span>;",
      filename: at("packages/ui/src/components/Twice.tsx"),
      errors: [
        ...raw("packages/ui/src/components/Twice.tsx"),
        ...raw("packages/ui/src/components/Twice.tsx"),
      ],
    },
  ],
});
