/**
 * E47-S05 (#1319) slice 3: the focus-ring guard (WCAG 2.4.7, 2.4.11, 1.4.11; CMP-039, A11Y-P-01).
 *
 * 1. Every CSS rule in apps/web and packages/ui that removes the outline (`outline: none | 0`, `outline-style:
 *    none`, `outline-width: 0`) must be one of: a rule that also draws a replacement in the same rule, one whose
 *    selector excludes `:focus-visible` (it can never remove a keyboard ring), one whose element has its own
 *    `:focus-visible` ring rule in the same file, or a site registered in `SITES` below with its reason. A
 *    container-focus site names the selector that draws the ring instead, and that rule must still exist.
 * 2. No inline style, Tailwind class or markup attribute removes an outline.
 * 3. The ring token holds the contrast of every `color.focus.ring` pair of the tools/contrast registry
 *    (3:1 on each surface tier), in every theme. The pairs are read from there, never copied.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const REPO = resolve(import.meta.dirname, "../../..");

// ---------------------------------------------------------------------------------------------------------------
// A small CSS reader: rules with their selectors and declarations, at-rule nesting flattened.

interface CssRule {
  readonly selector: string;
  readonly decls: ReadonlyMap<string, string>;
}

function splitTop(text: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let from = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (c === "(" || c === "[") depth += 1;
    else if (c === ")" || c === "]") depth -= 1;
    else if (c === sep && depth === 0) {
      out.push(text.slice(from, i));
      from = i + 1;
    }
  }
  out.push(text.slice(from));
  return out;
}

const squash = (s: string): string => s.replace(/\s+/gu, " ").trim();

function parseCss(source: string): CssRule[] {
  const css = source.replace(/\/\*[\s\S]*?\*\//gu, "");
  const rules: CssRule[] = [];
  const stack: { prelude: string; decls: Map<string, string> }[] = [];
  let buf = "";
  let paren = 0;
  const flush = (): void => {
    const top = stack[stack.length - 1];
    const at = buf.indexOf(":");
    if (top !== undefined && at > 0) {
      top.decls.set(squash(buf.slice(0, at)).toLowerCase(), squash(buf.slice(at + 1)));
    }
    buf = "";
  };
  for (const c of css) {
    if (c === "(") paren += 1;
    else if (c === ")") paren -= 1;
    if (paren > 0 || (c !== "{" && c !== "}" && c !== ";")) {
      buf += c;
    } else if (c === ";") {
      flush();
    } else if (c === "{") {
      stack.push({ prelude: squash(buf), decls: new Map() });
      buf = "";
    } else {
      flush();
      const done = stack.pop();
      if (done !== undefined && !done.prelude.startsWith("@")) {
        for (const selector of splitTop(done.prelude, ",")) {
          rules.push({ selector: squash(selector), decls: done.decls });
        }
      }
    }
  }
  return rules;
}

const NONE = /^(?:none|0|0px|0 none|none 0)(?:\s*!important)?$/iu;

/** Whether a rule removes the outline. */
function removesOutline(rule: CssRule): boolean {
  const outline = rule.decls.get("outline");
  const style = rule.decls.get("outline-style");
  const width = rule.decls.get("outline-width");
  return (
    (outline !== undefined && NONE.test(outline)) ||
    (style !== undefined && /^none(?:\s*!important)?$/iu.test(style)) ||
    (width !== undefined && /^0(?:px)?(?:\s*!important)?$/iu.test(width))
  );
}

const drawsRing = (rule: CssRule): boolean => {
  const outline = rule.decls.get("outline");
  const shadow = rule.decls.get("box-shadow") ?? "";
  return (
    (outline !== undefined && !NONE.test(outline) && /focus-ring/u.test(outline)) ||
    /focus-ring/u.test(shadow)
  );
};

/** `:not(…, :focus-visible)` somewhere in the selector: the rule never applies while a keyboard ring should show. */
const excludesFocusVisible = (selector: string): boolean =>
  /:not\([^)]*:focus-visible[^)]*\)/u.test(selector);

// ---------------------------------------------------------------------------------------------------------------
// The registered sites.

interface Site {
  readonly kind: "programmatic-target" | "container-focus";
  /** `container-focus`: the file and selector of the rule that draws the ring instead. */
  readonly ring?: { readonly file: string; readonly selector: string };
  readonly reason: string;
}

const UI = "packages/ui/src/components";
const FIELD_RING = { file: `${UI}/fields.css`, selector: ".cv-field:focus-within" };
const MENU_RING = {
  file: `${UI}/menu.css`,
  selector: ".cv-menu__row:has(.cv-menu__item:focus-visible)",
};

/** Keyed `file|selector`. Every entry must still match a real rule, so none outlives its CSS. */
const SITES: Readonly<Record<string, Site>> = {
  [`${UI}/radio.css|.cv-radio`]: {
    kind: "container-focus",
    ring: {
      file: `${UI}/focusring.css`,
      selector: ".cv-focus-ring-host:focus-visible .cv-focus-ring-target",
    },
    reason:
      "the host never draws: the ring wraps the radio's own circle through the host/target classes",
  },
  [`${UI}/select.css|.cv-select__trigger`]: {
    kind: "container-focus",
    ring: FIELD_RING,
    reason:
      "the trigger sits in the field well; the well takes the ring while the trigger has focus",
  },
  [`${UI}/fields.css|.cv-field__input`]: {
    kind: "container-focus",
    ring: FIELD_RING,
    reason:
      "the input sits in the field well; the well takes the ring on any focus, pointer included",
  },
  [`${UI}/menu.css|.cv-menu__item`]: {
    kind: "container-focus",
    ring: MENU_RING,
    reason:
      "the menuitem holds the label; its row draws the inset ring so the scroll box never clips it",
  },
  [`${UI}/popover.css|.cv-popover:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 fallback target (conventions 32); not a control, never reached by Tab",
  },
  [`${UI}/popover.css|.cv-popover__heading:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 fallback target (conventions 32); not a control, never reached by Tab",
  },
  [`${UI}/drawer.css|.cv-drawer:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 fallback target (conventions 32); not a control, never reached by Tab",
  },
  [`${UI}/drawer.css|.cv-drawer__title:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 heading focused on open (conventions 32); not a control",
  },
  [`${UI}/dialog.css|.cv-dialog:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 fallback target (conventions 32); not a control, never reached by Tab",
  },
  [`${UI}/dialog.css|.cv-dialog__title:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 heading focused on open (conventions 32); not a control",
  },
  [`${UI}/infopanel.css|.cv-info-panel__title:focus`]: {
    kind: "programmatic-target",
    reason: "tabindex -1 heading focused on open (conventions 32); not a control",
  },
  [`${UI}/menu.css|.cv-menu:focus`]: {
    kind: "programmatic-target",
    reason: "the menu takes focus only when it has no item (conventions 32); not a control",
  },
};

// ---------------------------------------------------------------------------------------------------------------
// The corpus.

const SKIP = new Set(["node_modules", "dist", "build", "coverage", "storybook-static", ".turbo"]);

function walk(dir: string, accept: (name: string) => boolean): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    if (SKIP.has(e.name)) return [];
    const p = join(dir, e.name);
    if (e.isDirectory()) return walk(p, accept);
    return accept(e.name) ? [p] : [];
  });
}

const rel = (p: string): string => relative(REPO, p).split("\\").join("/");
const ROOTS = [join(REPO, "apps/web"), join(REPO, "packages/ui")];

const CSS_FILES = ROOTS.flatMap((r) => walk(r, (n) => n.endsWith(".css")));
const CORPUS = new Map(CSS_FILES.map((p) => [rel(p), parseCss(readFileSync(p, "utf8"))]));

interface Suppression {
  readonly file: string;
  readonly selector: string;
  readonly rule: CssRule;
}

/** Every outline-removing selector in the corpus. */
const SUPPRESSIONS: Suppression[] = [...CORPUS].flatMap(([file, rules]) =>
  rules.filter(removesOutline).map((rule) => ({ file, selector: rule.selector, rule })),
);

type Corpus = ReadonlyMap<string, readonly CssRule[]>;

function ringRuleExists(file: string, selector: string, corpus: Corpus = CORPUS): boolean {
  return (corpus.get(file) ?? []).some((r) => r.selector === selector && drawsRing(r));
}

/** The element's own `:focus-visible` rule in the same file draws the ring. */
function hasOwnRing(file: string, selector: string, corpus: Corpus): boolean {
  return ringRuleExists(file, `${selector}:focus-visible`, corpus);
}

/** The reason a suppression is acceptable, else `undefined`. */
function acceptedBy(
  s: Suppression,
  sites: Readonly<Record<string, Site>>,
  corpus: Corpus = CORPUS,
): string | undefined {
  if (drawsRing(s.rule)) return "replacement in the same rule";
  if (excludesFocusVisible(s.selector)) return "excludes :focus-visible";
  if (hasOwnRing(s.file, s.selector, corpus)) return "own :focus-visible ring";
  return sites[`${s.file}|${s.selector}`] === undefined ? undefined : "registered site";
}

describe("focus-ring guard: CSS", () => {
  it("scans the CSS of both apps/web and packages/ui", () => {
    const files = [...CORPUS.keys()];
    expect(files).toContain("apps/web/src/features/auth/login.css");
    expect(files).toContain(`${UI}/dialog.css`);
    expect(files).toContain(`${UI}/focusring.css`);
    expect(files.some((f) => /(^|\/)(dist|build|node_modules)\//u.test(f))).toBe(false);
    expect(SUPPRESSIONS.length).toBeGreaterThan(10);
  });

  it("every outline removal has a replacement ring, or is a registered site", () => {
    const bare = SUPPRESSIONS.filter((s) => acceptedBy(s, SITES) === undefined).map(
      (s) => `${s.file} | ${s.selector}`,
    );
    expect(
      bare,
      "outline removed with no focus ring: add one in the rule, or register the site",
    ).toEqual([]);
  });

  it("every registered site still matches a rule, states a reason and, if a container, its ring rule", () => {
    const live = new Set(SUPPRESSIONS.map((s) => `${s.file}|${s.selector}`));
    for (const [key, site] of Object.entries(SITES)) {
      expect(live.has(key), `stale site: ${key}`).toBe(true);
      expect(site.reason.length, `no reason: ${key}`).toBeGreaterThan(20);
      if (site.kind === "container-focus") {
        expect(site.ring, `no ring named: ${key}`).toBeDefined();
        expect(
          ringRuleExists(site.ring!.file, site.ring!.selector),
          `the ring rule ${site.ring!.selector} is gone from ${site.ring!.file} (${key})`,
        ).toBe(true);
      } else {
        const selector = key.slice(key.indexOf("|") + 1);
        expect(selector, `${key}: a programmatic target is :focus, never :focus-visible`).toMatch(
          /:focus$/u,
        );
      }
    }
  });

  it("registers no site that something else already covers", () => {
    const covered = SUPPRESSIONS.filter((s) => acceptedBy(s, {}) !== undefined).map(
      (s) => `${s.file}|${s.selector}`,
    );
    for (const key of Object.keys(SITES))
      expect(covered, `redundant site: ${key}`).not.toContain(key);
  });
});

describe("focus-ring guard: the checker itself", () => {
  const check = (css: string, sites: Record<string, Site> = {}): (string | undefined)[] => {
    const rules = parseCss(css);
    const corpus: Corpus = new Map([["x.css", rules]]);
    return rules
      .filter(removesOutline)
      .map((rule) =>
        acceptedBy({ file: "x.css", selector: rule.selector, rule }, sites, corpus) === undefined
          ? `bare:${rule.selector}`
          : undefined,
      );
  };

  it("flags a bare removal in every spelling", () => {
    for (const decl of [
      "outline: none",
      "outline: 0",
      "outline:0px",
      "outline: none !important",
      "outline-style: none",
      "outline-width: 0",
    ]) {
      expect(check(`.a:focus { ${decl}; }`), decl).toEqual(["bare:.a:focus"]);
    }
  });

  it("flags a removal inside an at-rule and one selector of a list", () => {
    expect(check("@media (forced-colors: active) { .a, .b:focus { outline: none } }")).toEqual([
      "bare:.a",
      "bare:.b:focus",
    ]);
  });

  it("ignores comments and a url() with a semicolon", () => {
    expect(
      check('/* .a { outline: none } */ .b { background: url("data:image/png;base64,AA"); }'),
    ).toEqual([]);
  });

  it("accepts a replacement in the same rule, a :not(:focus-visible) selector and an own ring", () => {
    expect(check(".a { outline: none; box-shadow: 0 0 0 2px var(--color-focus-ring); }")).toEqual([
      undefined,
    ]);
    expect(check(".a:hover:not(:disabled, :focus-visible) { outline: none }")).toEqual([undefined]);
    expect(
      check(
        ".a { outline: none } .a:focus-visible { outline: 2px solid var(--color-focus-ring); }",
      ),
    ).toEqual([undefined]);
  });

  it("does not take an own :focus-visible rule that draws nothing, or a ring in another rule", () => {
    expect(check(".a { outline: none } .a:focus-visible { color: red }")).toEqual(["bare:.a"]);
    expect(check(".a { outline: none } .b { outline: 2px solid var(--color-focus-ring) }")).toEqual(
      ["bare:.a"],
    );
  });

  it("accepts only the exact registered selector", () => {
    const sites = { "x.css|.a": { kind: "programmatic-target", reason: "x".repeat(21) } } as const;
    expect(check(".a { outline: none }", sites)).toEqual([undefined]);
    expect(check(".a .b { outline: none }", sites)).toEqual(["bare:.a .b"]);
  });
});

describe("focus-ring guard: no outline removal outside CSS files", () => {
  it("finds none in inline styles, Tailwind classes or markup", () => {
    const files = ROOTS.flatMap((r) =>
      walk(r, (n) => /\.(?:tsx?|html)$/u.test(n) && !/\.(?:test|stories)\.tsx?$/u.test(n)),
    ).filter((p) => !/\/(?:test|e2e|\.storybook|eslint-rules|scripts)\//u.test(rel(p)));
    const SPELLINGS =
      /outline(?:Style|Width)?["']?\s*[:=]\s*["'`]?(?:none|0)\b|\boutline-(?:none|0)\b|focus:outline-none/u;
    const hits = files
      .filter((p) =>
        readFileSync(p, "utf8")
          .split("\n")
          .some((l) => SPELLINGS.test(l) && !/^\s*(?:\*|\/\/)/u.test(l)),
      )
      .map(rel);
    expect(hits).toEqual([]);
  });
});

// ---------------------------------------------------------------------------------------------------------------
// The ring's contrast, per theme.

type Theme = Record<string, { $value: unknown } | undefined>;
interface Pair {
  readonly fg: string;
  readonly bg: string;
  readonly threshold: number;
  readonly themes?: readonly string[];
}
const math = (await import(
  /* @vite-ignore */ "../../../tools/contrast/color-math.mjs" as string
)) as { contrastRatio(a: string, b: string): number };
const registry = (await import(
  /* @vite-ignore */ "../../../tools/contrast/pairs.mjs" as string
)) as { PAIRS: readonly Pair[] };
const build = (await import(/* @vite-ignore */ "../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const themes = await build.loadResolvedThemes();
const RING_PAIRS = registry.PAIRS.filter((p) => p.fg === "color.focus.ring");

function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/u.test(v)) {
    throw new Error(`focus-ring guard: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}

describe("focus-ring guard: the ring's contrast per theme (WCAG 1.4.11)", () => {
  it("the registry declares ring pairs, none below 3:1", () => {
    expect(RING_PAIRS.length).toBeGreaterThanOrEqual(3);
    for (const p of RING_PAIRS) expect(p.threshold).toBeGreaterThanOrEqual(3);
  });

  it("builds light, dark and high-contrast", () => {
    expect(Object.keys(themes).sort()).toEqual(["dark", "high-contrast", "light"]);
  });

  describe.each(["light", "dark", "high-contrast"])("%s", (name) => {
    const theme = themes[name] as Theme;
    for (const p of RING_PAIRS.filter((x) => x.themes === undefined || x.themes.includes(name))) {
      it(`${p.fg} on ${p.bg} holds ${p.threshold}:1`, () => {
        const ratio = math.contrastRatio(hexOf(theme, p.fg), hexOf(theme, p.bg));
        expect(Math.floor(ratio * 1000) / 1000).toBeGreaterThanOrEqual(p.threshold);
      });
    }
  });
});
