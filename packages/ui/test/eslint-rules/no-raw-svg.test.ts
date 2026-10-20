import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, expect, it } from "vitest";
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
const dataUrl = { messageId: "dataUrl", data: { file: "src/components/PanelHeader.tsx" } };

tester.run("no-raw-svg", noRawSvg, {
  valid: [
    { code: "export const Close = () => <CloseIcon />;", filename: COMPONENT },
    { code: 'export const Close = () => <Icon name="close" size="sm" />;', filename: COMPONENT },
    { code: "export const Chart = () => <canvas aria-label='Chart' />;", filename: COMPONENT },
    { code: "export const Logo = () => <Svg />;", filename: COMPONENT },
    { code: 'createElement("div", null, "svg");', filename: COMPONENT },
    { code: 'const tag = "svg";', filename: COMPONENT },
    {
      code: 'export const Shot = () => <img src="data:image/png;base64,AAAA" alt="" />;',
      filename: COMPONENT,
    },
    {
      code: 'document.createElementNS("http://www.w3.org/1999/xhtml", "div");',
      filename: COMPONENT,
    },
    { code: "document.createElementNS(SVG_NS, tagName);", filename: COMPONENT },
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
    // The DOM's namespaced creator takes the tag second, as a qualified name.
    {
      code: 'document.createElementNS("http://www.w3.org/2000/svg", "svg");',
      filename: COMPONENT,
      errors: [raw],
    },
    { code: 'document.createElementNS(SVG_NS, "svg:svg");', filename: COMPONENT, errors: [raw] },
    // An SVG data URL brings a glyph past the registry as surely as a raw <svg> does.
    {
      code: 'export const Mark = () => <img src="data:image/svg+xml,%3Csvg%3E" alt="" />;',
      filename: COMPONENT,
      errors: [dataUrl],
    },
    {
      code: "const mark = { backgroundImage: 'url(\"data:image/svg+xml;base64,PHN2Zz4=\")' };",
      filename: COMPONENT,
      errors: [dataUrl],
    },
    {
      code: "const mark = `url(DATA:image/SVG+xml;utf8,${glyph})`;",
      filename: COMPONENT,
      errors: [dataUrl],
    },
  ],
});

describe("the docs pages (src/**/*.mdx), which ESLint does not read", () => {
  const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
  const pages = readdirSync(SRC, { recursive: true, encoding: "utf-8" }).filter((file) =>
    file.endsWith(".mdx"),
  );

  it("exist, so the check below reads something", () => {
    expect(pages.length).toBeGreaterThan(0);
  });

  it("draw no raw <svg> and no SVG data URL: their glyphs come from the registry too", () => {
    const leaks = pages.filter((file) =>
      /<svg\b|data:image\/svg\+xml/i.test(readFileSync(path.join(SRC, file), "utf-8")),
    );
    expect(leaks).toEqual([]);
  });
});
