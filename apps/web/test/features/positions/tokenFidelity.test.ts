// @vitest-environment node
/**
 * E29-D07 (#1146) token fidelity, the static leg, for the OMS blotter slice (`features/positions`: Positions,
 * Working orders, Fills and SCR-078). It mirrors `packages/ui/test/css-contract.ts`; the raw-value ESLint rule
 * covers `packages/ui/src` only, so nothing else holds `apps/web`. The slice's stylesheets bind no raw colour and
 * no raw px (px only as the token multiplier `* 1px`, and the literal 1px / 2px edges of a forced-colours block),
 * and every `var(--…)` names a token the build writes, a `theme.css` property or one the slice declares itself;
 * its components write no literal `style={{…}}`. "No raw transition" is read as no literal duration or easing: a
 * motion token or a `--cv-recipe-*` passes, because Mo-6, Mo-9 and E05-D03's recipes will animate (D04 §3.2). It
 * is not read as "nothing animates", which css-contract.ts asks of the static atoms. `main` holds no stylesheet
 * or component of the slice yet, so those scans cover nothing today; the fixtures below prove each scanner, so a
 * pass is not a no-op.
 *
 * What passes, as it does under css-contract.ts: a named colour (`red`), `color-mix()` over named colours, a `rem`
 * or `em` length and an upper-case unit (`150MS`, `12PX`). In a component the scan reads a `style` attribute that
 * is, or can evaluate to, an object literal (`{…}`, `on ? {…} : x`, `on && {…}`, `x ?? {…}`); it does not see a
 * style built outside the attribute (a helper, a `useMemo`, a name bound to an object) or an imperative
 * `ref.style.x = …`.
 */
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const WEB = resolve(import.meta.dirname, "../../..");
const SLICE = join(WEB, "src/features/positions");
const UI = resolve(WEB, "../../packages/ui");

const filesOf = (ext: string): string[] =>
  readdirSync(SLICE, { recursive: true, encoding: "utf8" })
    .filter((file) => file.endsWith(ext))
    .map((file) => join(SLICE, file));
const names = (css: string, re: RegExp): string[] =>
  [...css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(re)].flatMap((m) => (m[1] ? [m[1]] : []));
const declared = (css: string): string[] => names(css, /(--[\w-]+)\s*:/g);
const unresolved = (css: string, known: ReadonlySet<string>): string[] =>
  names(css, /var\(\s*(--[\w-]+)/g).filter((name) => !known.has(name));
const found = <R extends { file: string }>(rows: R[], scan: (row: R) => string[]): string[] =>
  rows.flatMap((row) => scan(row).map((hit) => `${row.file}: ${hit}`));

const FORCED = /@media[^{]*forced-colors[^{]*\{((?:[^{}]|\{[^{}]*\})*)\}/g; // every block, not the first only
const COLOUR = /#[0-9a-f]{3,8}\b|\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)a?\(|\bcolor\(/gi;
const MOTION = /(?:^|[;{}\s])(?:transition|animation)(?:-[a-z-]+)?\s*:([^;}]*)/g;
const RAW_TIMING =
  /\b\d*\.?\d+(?:ms|s)\b|\b(?:ease(?:-in)?(?:-out)?|linear|step-start|step-end)\b|(?:cubic-bezier|steps)\([^)]*\d/;

/** A function's text from its name through the matching `)`; one never closed ends with its declaration. */
const through = (text: string, at: number): string => {
  let depth = 0;
  for (let i = text.indexOf("(", at); i >= 0 && i < text.length; i++) {
    if (text[i] === "(") depth++;
    else if (text[i] === ")" && --depth === 0) return text.slice(at, i + 1);
  }
  return text.slice(at).split(/[;}]/, 1)[0] ?? "";
};
/** Every raw colour of `text`, as the value itself: `#fff`, `rgba(0, 0, 0, 0.5)`. */
const colours = (text: string): string[] =>
  [...text.matchAll(COLOUR)].map((m) => {
    const value = m[0].startsWith("#") ? m[0] : through(text, m.index ?? 0);
    return `colour ${value.replace(/\s+/g, " ").trim()}`;
  });
/** A motion value without its `var(--x)` calls; a `var(--x, fallback)` leaves its fallback, which may be a literal. */
const bare = (value: string): string => {
  let text = value;
  let before: string;
  do {
    before = text;
    text = text.replace(/var\(\s*--[\w-]+\s*(?:,([^()]*))?\)/g, "$1");
  } while (text !== before);
  return text.replace(/\b(?:0s|0ms|0\.01ms)\b/g, "");
};

/** What a stylesheet writes by hand where a token exists, one entry per raw colour, px or motion value. */
const rawIn = (source: string): string[] => {
  const css = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const normal = css.replace(FORCED, "");
  const forced = [...css.matchAll(FORCED)].map((m) => m[1]).join("\n");
  const hits = (kind: string, text: string, re: RegExp): string[] =>
    [...text.matchAll(re)].map((m) => `${kind} ${m[0].trim()}`);
  return [
    ...colours(`${normal}\n${forced}`),
    ...hits("px", normal.replace(/\* 1px/g, ""), /\d*\.?\d+px/g),
    ...hits(
      "px in forced-colours",
      forced.replace(/\* 1px|(?<![\d.])[12]px\b/g, ""),
      /\d*\.?\d+px/g,
    ),
    ...[...normal.matchAll(MOTION)]
      .filter(([, value = ""]) => RAW_TIMING.test(bare(value)))
      .map(([decl]) => `motion ${decl.trim()}`),
  ];
};

const LOGICAL = new Set<ts.SyntaxKind>([
  ts.SyntaxKind.AmpersandAmpersandToken,
  ts.SyntaxKind.BarBarToken,
  ts.SyntaxKind.QuestionQuestionToken,
]);
/** Whether an expression is, or can be, an object literal: `{…}`, `on ? {…} : x`, `on && {…}`, `x ?? {…}`. */
const holdsLiteral = (node: ts.Expression | undefined): boolean => {
  let e = node;
  while (
    e &&
    (ts.isParenthesizedExpression(e) ||
      ts.isAsExpression(e) ||
      ts.isSatisfiesExpression(e) ||
      ts.isNonNullExpression(e))
  )
    e = e.expression;
  if (!e) return false;
  if (ts.isObjectLiteralExpression(e)) return true;
  if (ts.isConditionalExpression(e)) return holdsLiteral(e.whenTrue) || holdsLiteral(e.whenFalse);
  return (
    ts.isBinaryExpression(e) &&
    LOGICAL.has(e.operatorToken.kind) &&
    (holdsLiteral(e.left) || holdsLiteral(e.right))
  );
};

/** The `style` attributes of a TSX source that are object literals (parsed: a comment or a string is not one). */
const literalStyles = (text: string): string[] => {
  const sf = ts.createSourceFile("x.tsx", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const literals: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isJsxAttribute(node) && node.name.getText(sf) === "style" && node.initializer) {
      if (ts.isJsxExpression(node.initializer) && holdsLiteral(node.initializer.expression))
        literals.push(
          `style={{…}} at line ${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1}`,
        );
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return literals;
};

let cached: Set<string> | undefined;
/** The custom properties the theme build writes, from the build's own functions (nothing is written to disk). */
const builtTokens = (): Set<string> => {
  if (cached) return cached;
  const load = (file: string): string =>
    `await import(${JSON.stringify(join(UI, "scripts", file))})`;
  const script = `const { loadResolvedThemes } = ${load("build-tokens.mjs")};
    const { cssDeclarations } = ${load("token-css.mjs")};
    const themes = await loadResolvedThemes();
    console.log(JSON.stringify(Object.values(themes).flatMap((tokens) =>
      Object.entries(tokens).flatMap(([name, token]) => cssDeclarations(name, token).map(([p]) => p)))));`;
  const argv = ["--input-type=module", "-e", script];
  cached = new Set(
    JSON.parse(execFileSync(process.execPath, argv, { cwd: UI, encoding: "utf8" })) as string[],
  );
  return cached;
};
const runtimeNames = (): string[] =>
  declared(readFileSync(join(UI, "src/theme/theme.css"), "utf8"));

describe("E29-D07 token fidelity: the OMS blotter slice (features/positions)", () => {
  const sheets = filesOf(".css").map((file) => ({ file, css: readFileSync(file, "utf8") }));
  const components = filesOf(".tsx").map((file) => ({ file, text: readFileSync(file, "utf8") }));

  // 60 s: `builtTokens()` starts a node child that loads the token build, which a loaded host stretches past 5 s.
  it(
    "scans the slice's tree and resolves against the build (neither is vacuous)",
    { timeout: 60_000 },
    () => {
      expect(filesOf(".ts").length).toBeGreaterThan(10);
      const built = builtTokens();
      for (const name of ["--color-text-primary", "--space-inset-sm", "--type-ui-body-font-size"])
        expect(built.has(name), name).toBe(true);
      expect(runtimeNames()).toContain("--cv-recipe-fade-out");
    },
  );

  it("binds no raw colour, px or motion in a stylesheet", () => {
    expect(found(sheets, ({ css }) => rawIn(css))).toStrictEqual([]);
  });

  it("writes no literal style={{…}} in a component", () => {
    expect(found(components, ({ text }) => literalStyles(text))).toStrictEqual([]);
  });

  it("names only built tokens in var(--…)", { timeout: 60_000 }, () => {
    const known = new Set([
      ...builtTokens(),
      ...runtimeNames(),
      ...sheets.flatMap(({ css }) => declared(css)),
    ]);
    expect(found(sheets, ({ css }) => unresolved(css, known))).toStrictEqual([]);
  });
});

describe("the scanners the guard rests on", () => {
  const forced = (rule: string): string => `@media (forced-colors: active) { .a { ${rule} } }`;
  const twoBlocks = `${forced("color: CanvasText;")} .b { width: 7px; } ${forced("outline: 4px solid CanvasText;")}`;

  it.each([
    [".a { color: #fff; }", ["colour #fff"]],
    [".a { color: rgba(0, 0, 0, 0.5); }", ["colour rgba(0, 0, 0, 0.5)"]],
    [
      ".a { color: rgb(1 2 3 / 50%); border-color: oklch(0.7 0.1 200); outline-color: rgb(from var(--c) r g b); }",
      ["colour rgb(1 2 3 / 50%)", "colour oklch(0.7 0.1 200)", "colour rgb(from var(--c) r g b)"],
    ],
    [".a { background: rgb(1,\n  2,\n  3); }", ["colour rgb(1, 2, 3)"]],
    [".a { color: rgb(1, 2, 3 }", ["colour rgb(1, 2, 3"]],
    [".a { padding: 12px; border: 1px solid var(--color-border-default); }", ["px 12px", "px 1px"]],
    [forced("outline: 3px solid CanvasText;"), ["px in forced-colours 3px"]],
    [twoBlocks, ["px 7px", "px in forced-colours 4px"]],
    [".a { transition: opacity 200ms ease; }", ["motion transition: opacity 200ms ease"]],
    [".a { animation: spin 1s linear infinite; }", ["motion animation: spin 1s linear infinite"]],
    [
      ".a { transition: opacity 0.2s cubic-bezier(0.2, 0, 0, 1); }",
      [expect.stringMatching(/^motion/)],
    ],
    [
      ".a { transition: opacity var(--motion-duration-fast, 150ms); }",
      ["motion transition: opacity var(--motion-duration-fast, 150ms)"],
    ],
    [
      ".a { transition: opacity var(--motion-duration-fast) var(--e, ease-out); }",
      ["motion transition: opacity var(--motion-duration-fast) var(--e, ease-out)"],
    ],
    [".a { margin: calc(var(--space-inset-sm) * 1px); color: var(--color-text-primary); }", []],
    [forced("outline: 2px solid CanvasText; border-color: ButtonBorder;"), []],
    ["/* color: #fff; padding: 12px; transition: all 1s */ .a { margin: 0; }", []],
    [
      ".a { transition: opacity var(--cv-recipe-fade-out); animation: var(--cv-recipe-drawer-in); }",
      [],
    ],
    [
      ".a { transition: opacity var(--motion-duration-fast) cubic-bezier(var(--motion-easing-standard)); }",
      [],
    ],
    [
      ".a { transition: opacity var(--motion-duration-fast, var(--motion-duration-normal)); animation: var(--cv-recipe-x, none); }",
      [],
    ],
    [".a { transition: none; animation-duration: 0.01ms !important; transition-delay: 0s; }", []],
    // What passes, as under css-contract.ts (the header comment): not an assertion of intent, a pin of today's reading.
    [
      ".a { color: red; background: color-mix(in srgb, red 50%, white); gap: 1rem; padding: 1em; }",
      [],
    ],
    [".a { margin: 12PX; transition: opacity 150MS; }", []],
  ])("reads %s", (css, expected) => {
    expect(rawIn(css)).toStrictEqual(expected);
  });

  it("resolves var(--…) against the known names and the sheet's own", () => {
    const known = new Set(["--space-inset-sm", "--x"]);
    expect(unresolved(".a { gap: var(--space-nonexistent); }", known)).toStrictEqual([
      "--space-nonexistent",
    ]);
    expect(
      unresolved(".a { --x: var(--space-inset-sm); gap: var( --x , 4px ); }", known),
    ).toStrictEqual([]);
  });

  it.each([
    ["<div style={{ width: 4 }} />", 1],
    ["<div style={{ ...rest } as CSSProperties} />", 1],
    ["<div style={on ? { width: 4 } : undefined} />", 1],
    ["<div style={on ? undefined : { width: 4 }} />", 1],
    ["<div style={on && { width: 4 }} />", 1],
    ["<div style={props.style ?? { width: 4 }} />", 1],
    ["<div style={a ? vars : (b && ({ width: 4 } as CSSProperties))} />", 1],
    ["<div style={vars} className={cx({ a: true })} />", 0],
    ["<div style={on ? vars : undefined} />", 0],
    ["<div style={on && vars} />", 0],
    ['// style={{ a: 1 }}\nconst s = "style={{"; <i />', 0],
    // Not seen, and said so in the header comment: a style set on a node by hand.
    ["const f = (el: HTMLElement) => { el.style.width = '4px'; }; <i />", 0],
  ])("finds the literal style in %s", (source, count) => {
    expect(literalStyles(source)).toHaveLength(count);
  });
});
