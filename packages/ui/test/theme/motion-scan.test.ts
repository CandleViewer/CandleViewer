import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/*
 * E05-D03 C-7, the static scan: every animated or transitioned rule in packages/ui/src/**\/*.css has a
 * `:root[data-motion="reduce"]` counterpart (the attribute, never the OS query), or is in the committed
 * allowlist below with its reason. #1318's full lint builds on `scanCss`.
 */

const REPO = resolve(import.meta.dirname, "../../../..");
/*
 * E47-S04 (#1318, BQ-4): the lint covers packages/ui and apps/web CSS (CSS modules included). The scan
 * reads both trees from this one test by path: a test-time file read is not an import, so no package
 * boundary is crossed and the parser has a single copy. apps/web has no stylesheet today (its motion is
 * inline TS, a PR 3 register row), so its baseline is empty and any new rule there is held to the pairing.
 */
const ROOTS: ReadonlyArray<{ readonly label: string; readonly dir: string }> = [
  { label: "packages/ui/src", dir: join(REPO, "packages/ui/src") },
  { label: "apps/web/src", dir: join(REPO, "apps/web/src") },
];
const SRC = ROOTS[0]?.dir ?? "";

export interface Finding {
  readonly rule: "os-gate" | "os-only-reduce" | "no-counterpart";
  readonly selector: string;
}

interface Block {
  readonly selector: string;
  readonly atrules: readonly string[];
  readonly decls: ReadonlyMap<string, string>;
}

const MOTION_PROPS = ["animation", "animation-name", "transition", "transition-property"];
const REDUCE = ':root[data-motion="reduce"]';
const OS_FALLBACK = ":root:not([data-motion])";
const squash = (text: string): string => text.replace(/\s+/g, " ").trim();

/** Rule blocks with their enclosing at-rules; `@keyframes` bodies are skipped (they animate nothing). */
function blocks(css: string): Block[] {
  const out: Block[] = [];
  const stack: string[] = [];
  let prelude = "";
  let body = "";
  let depth = 0;
  for (const ch of css.replace(/\/\*[\s\S]*?\*\//g, "")) {
    if (ch === "{") {
      if (depth === 0 || prelude !== "") {
        stack.push(squash(prelude));
        prelude = "";
      }
      depth += 1;
      body = "";
    } else if (ch === "}") {
      const selector = stack.pop() ?? "";
      if (body.trim() !== "" && !selector.startsWith("@")) {
        const decls = new Map<string, string>();
        for (const m of body.matchAll(/([\w-]+)\s*:\s*([^;]*?)\s*(?:;|$)/g)) {
          decls.set(m[1] ?? "", squash(m[2] ?? "").replace(/\s*!important$/, ""));
        }
        out.push({ selector, atrules: stack.filter((s) => s.startsWith("@")), decls });
      }
      body = "";
      depth -= 1;
    } else if (depth > 0 && stack.length > 0 && !stack[stack.length - 1]?.startsWith("@")) {
      body += ch;
    } else if (depth === 0 || stack[stack.length - 1]?.startsWith("@")) {
      prelude += ch;
    }
  }
  return out.filter((b) => !b.atrules.some((a) => a.startsWith("@keyframes")));
}

const noMotion = (value: string | undefined): boolean =>
  value === undefined || value === "none" || /^var\(--cv-recipe-[\w-]+\)$/.test(value);

/** Exactly the counterpart forms; any other `:root ...` selector is scanned like a component rule. */
const isCounterpart = (selector: string): boolean =>
  /^:root(\[data-motion|:not\(\[data-motion\]\)|\[data-theme-swap\])/.test(selector);

/** Findings for one stylesheet. A recipe variable resolves to `none` under reduce (theme.css), so it counts as paired. */
export function scanCss(css: string): Finding[] {
  const all = blocks(css);
  const reduceSelectors = new Set(
    all
      .filter(
        (b) => b.selector.startsWith(REDUCE) && MOTION_PROPS.some((p) => b.decls.get(p) === "none"),
      )
      .flatMap((b) => b.selector.split(/,(?![^(]*\))/).map(squash)),
  );
  const out: Finding[] = [];
  for (const b of all) {
    const animates = MOTION_PROPS.filter((p) => !noMotion(b.decls.get(p)));
    const fallback = b.selector.startsWith(OS_FALLBACK);
    if (b.atrules.some((a) => a.includes("prefers-reduced-motion: no-preference")) && !fallback) {
      if (animates.length > 0) out.push({ rule: "os-gate", selector: b.selector });
      continue;
    }
    if (b.atrules.some((a) => a.includes("prefers-reduced-motion: reduce")) && !fallback) {
      if (b.decls.size > 0) out.push({ rule: "os-only-reduce", selector: b.selector });
      continue;
    }
    if (animates.length === 0 || isCounterpart(b.selector) || fallback) continue;
    const selectors = b.selector.split(/,(?![^(]*\))/).map(squash);
    if (!selectors.every((s) => reduceSelectors.has(`${REDUCE} ${s}`))) {
      out.push({ rule: "no-counterpart", selector: b.selector });
    }
  }
  return out;
}

/**
 * The committed baseline: rules that animate or transition with a literal value and no per-rule reduce
 * counterpart yet (repo-relative file, selector, reason). Each is covered at runtime by the universal
 * reduce block (`theme.css`, durations 0.01 ms), so none is a precedence defect; #1318 shrinks this list
 * by moving each to a recipe. Never grow it. apps/web: no entry, it has no offender.
 */
const U = "packages/ui/src/components/";
const BASELINE: ReadonlyArray<readonly [file: string, selector: string, reason: string]> = [
  [
    `${U}combobox.css`,
    ".cv-combobox__popup",
    "opacity fade: held to 0.01 ms by the universal reduce block; per-rule recipe pending (#1318)",
  ],
  [
    `${U}progress.css`,
    ".cv-progress__fill",
    "determinate fill transform: held to 0.01 ms by the universal reduce block; recipe pending (#1318)",
  ],
  [
    `${U}toggle.css`,
    ".cv-switch",
    "state colour change: held to 0.01 ms by the universal reduce block; recipe pending (#1318)",
  ],
  [
    `${U}toggle.css`,
    ".cv-switch__knob",
    "knob slide: held to 0.01 ms by the universal reduce block; recipe pending (#1318)",
  ],
];

/** The component a stylesheet belongs to: `features/<name>/` in apps/web, else the file's base name. */
export function componentOf(file: string): string {
  const feature = /apps\/web\/src\/features\/([^/]+)\//.exec(file);
  if (feature) return feature[1] ?? file;
  return (file.split("/").pop() ?? file).replace(/\.module\.css$|\.css$/, "");
}

const describeFinding = (file: string, f: Finding): string =>
  `${file} | ${f.rule} | ${f.selector} | component: ${componentOf(file)}`;

/** AC 4: offenders outside the baseline, and stale baseline entries, each named with file, selector, component. */
export function lintSheets(
  sheets: ReadonlyArray<readonly [file: string, css: string]>,
  baseline: typeof BASELINE,
): { offenders: string[]; stale: string[] } {
  const found = sheets.flatMap(([file, css]) =>
    scanCss(css).map((f) => ({ file, f, line: describeFinding(file, f) })),
  );
  const allowed = (file: string, f: Finding): boolean =>
    f.rule === "no-counterpart" && baseline.some(([bf, bs]) => bf === file && bs === f.selector);
  return {
    offenders: found.filter(({ file, f }) => !allowed(file, f)).map((x) => x.line),
    stale: baseline
      .filter(
        ([bf, bs]) =>
          !found.some(({ file, f }) => file === bf && allowed(file, f) && f.selector === bs),
      )
      .map(
        ([bf, bs]) =>
          `${bf} | ${bs} | component: ${componentOf(bf)} | stale baseline entry, delete it`,
      ),
  };
}

const sheetsOf = (): Array<[string, string]> =>
  ROOTS.flatMap(({ label, dir }) =>
    readdirSync(dir, { recursive: true, encoding: "utf-8" })
      .filter((f) => f.endsWith(".css"))
      .sort()
      .map((f): [string, string] => [`${label}/${f}`, readFileSync(join(dir, f), "utf-8")]),
  );

describe("motion scan (E05-D03 C-7)", () => {
  const files = readdirSync(SRC, { recursive: true, encoding: "utf-8" })
    .filter((f) => f.endsWith(".css"))
    .sort();

  it("scans the stylesheets, theme.css included", () => {
    expect(files.length).toBeGreaterThan(20);
    expect(files).toContain(join("theme", "theme.css"));
  });

  it("every animated or transitioned rule, ui and web, has a data-motion reduce counterpart or is baselined", () => {
    const { offenders, stale } = lintSheets(sheetsOf(), BASELINE);
    expect(offenders).toEqual([]);
    // The baseline only shrinks: a stale entry fails here.
    expect(stale).toEqual([]);
    for (const [, , reason] of BASELINE) expect(reason.length).toBeGreaterThan(10);
  });

  it("the baseline names only packages/ui or apps/web stylesheets that exist", () => {
    const names = sheetsOf().map(([f]) => f);
    for (const [file] of BASELINE) expect(names).toContain(file);
  });

  it("the OS query never gates entrance motion (G-1): only the data-motion fallback may read it", () => {
    for (const [file, css] of sheetsOf()) {
      const rules = scanCss(css).map((f) => f.rule);
      expect(rules, file).not.toContain("os-gate");
      expect(rules, file).not.toContain("os-only-reduce");
    }
  });

  it("every recipe is a safe / reduce pair in theme.css, the reduce literally none", () => {
    const theme = readFileSync(join(SRC, "theme/theme.css"), "utf-8");
    const safe = [...theme.matchAll(/--cv-recipe-([\w-]+)-safe:/g)].map((m) => m[1] ?? "");
    expect(safe.length).toBeGreaterThanOrEqual(15);
    for (const name of safe) {
      expect(theme, name).toMatch(new RegExp(`--cv-recipe-${name}-reduce: none;`));
      expect(theme, name).toContain(`--cv-recipe-${name}: var(--cv-recipe-${name}-safe);`);
      // Resolved to the reduce value under the attribute and under the OS fallback, both.
      const resolved = `--cv-recipe-${name}: var(--cv-recipe-${name}-reduce);`;
      expect(theme.split(resolved), name).toHaveLength(3);
    }
  });

  it("the OS-reduce fallback zeroes --cv-motion-scale too, and the flash peak consumes it (G-2)", () => {
    const theme = readFileSync(join(SRC, "theme/theme.css"), "utf-8");
    expect(theme).toMatch(
      /@media \(prefers-reduced-motion: reduce\) \{\s*:root:not\(\[data-motion\]\) \{\s*--cv-motion-scale: 0;/,
    );
    expect(theme).toContain("--cv-flash-peak: calc(0.25 * var(--cv-motion-scale));");
  });

  it("a theme swap suppresses transitions for its frames (the #3140 lens finding)", () => {
    const theme = readFileSync(join(SRC, "theme/theme.css"), "utf-8");
    expect(theme).toMatch(/:root\[data-theme-swap\] \*::after \{\s*transition: none !important;/);
  });

  describe("the lint (AC 4)", () => {
    const web = "apps/web/src/features/orders/Ticket.module.css";
    const bad = ".row { transition: opacity 1s; }";

    it("fails an injected offending rule, naming file, selector and component", () => {
      const { offenders } = lintSheets([[web, bad]], []);
      expect(offenders).toEqual([`${web} | no-counterpart | .row | component: orders`]);
    });

    it("passes the same rule once its reduce counterpart exists", () => {
      const ok = `${bad} ${REDUCE} .row { transition: none; }`;
      expect(lintSheets([[web, ok]], [])).toEqual({ offenders: [], stale: [] });
    });

    it("fails a baseline entry whose rule is gone, naming it", () => {
      const { stale } = lintSheets([[web, ""]], [[web, ".row", "a long enough reason"]]);
      expect(stale).toEqual([
        `${web} | .row | component: orders | stale baseline entry, delete it`,
      ]);
    });

    it("lets a baselined rule through", () => {
      expect(lintSheets([[web, bad]], [[web, ".row", "a long enough reason"]])).toEqual({
        offenders: [],
        stale: [],
      });
    });

    it("names the ui component by its stylesheet", () => {
      expect(componentOf("packages/ui/src/components/toggle.css")).toBe("toggle");
    });
  });

  describe("the scanner itself", () => {
    it("flags a literal animation with no counterpart", () => {
      expect(scanCss(".a { animation: spin 1s linear; }")).toEqual([
        { rule: "no-counterpart", selector: ".a" },
      ]);
    });

    it("flags a :root descendant rule; only the counterpart forms are skipped", () => {
      expect(scanCss(":root .x { animation: spin 1s; }")).toEqual([
        { rule: "no-counterpart", selector: ":root .x" },
      ]);
      expect(scanCss(':root[data-motion="reduce"] .x { animation: none; }')).toEqual([]);
    });

    it("flags an entrance gated on the OS no-preference query", () => {
      const css = "@media (prefers-reduced-motion: no-preference) { .a { animation: spin 1s; } }";
      expect(scanCss(css).map((f) => f.rule)).toEqual(["os-gate"]);
    });

    it("flags a reduce rule keyed on the OS query alone", () => {
      const css = "@media (prefers-reduced-motion: reduce) { .a { transition: none; } }";
      expect(scanCss(css).map((f) => f.rule)).toEqual(["os-only-reduce"]);
    });

    it("accepts a data-motion reduce counterpart, a recipe variable, and the OS fallback", () => {
      const paired = `.a { transition: opacity 1s; } ${REDUCE} .a { transition: none; }`;
      expect(scanCss(paired)).toEqual([]);
      expect(scanCss(".a { animation: var(--cv-recipe-spinner); }")).toEqual([]);
      const fallback = `@media (prefers-reduced-motion: no-preference) { ${OS_FALLBACK} .a { animation: spin 1s; } }`;
      expect(
        scanCss(`.a { animation: spin 1s; } ${REDUCE} .a { animation: none; } ${fallback}`),
      ).toEqual([]);
    });
  });
});
