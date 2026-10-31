import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/*
 * E05-D03 C-7, the static scan: every animated or transitioned rule in packages/ui/src/**\/*.css has a
 * `:root[data-motion="reduce"]` counterpart (the attribute, never the OS query), or is in the committed
 * allowlist below with its reason. #1318's full lint builds on `scanCss`.
 */

const SRC = resolve(import.meta.dirname, "../../src");

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
    if (animates.length === 0 || b.selector.startsWith(":root") || fallback) continue;
    const selectors = b.selector.split(/,(?![^(]*\))/).map(squash);
    if (!selectors.every((s) => reduceSelectors.has(`${REDUCE} ${s}`))) {
      out.push({ rule: "no-counterpart", selector: b.selector });
    }
  }
  return out;
}

/**
 * Rules that animate or transition with a literal value and no per-rule reduce counterpart yet. Each is
 * covered at runtime by the universal reduce block (`theme.css`, durations 0.01 ms), so none is a
 * precedence defect; #1318 shrinks this list by moving each to a recipe. Never grow it.
 */
const ALLOWLIST: ReadonlyArray<readonly [file: string, selector: string, reason: string]> = [
  [
    "components/combobox.css",
    ".cv-combobox__popup",
    "opacity fade: held to 0.01 ms by the universal reduce block; per-rule recipe pending (#1318)",
  ],
  [
    "components/progress.css",
    ".cv-progress__fill",
    "determinate fill transform: held to 0.01 ms by the universal reduce block; recipe pending (#1318)",
  ],
  [
    "components/toggle.css",
    ".cv-switch",
    "state colour change: held to 0.01 ms by the universal reduce block; recipe pending (#1318)",
  ],
  [
    "components/toggle.css",
    ".cv-switch__knob",
    "knob slide: held to 0.01 ms by the universal reduce block; recipe pending (#1318)",
  ],
];

const key = (file: string, f: Finding): string => `${file} | ${f.rule} | ${f.selector}`;

describe("motion scan (E05-D03 C-7)", () => {
  const files = readdirSync(SRC, { recursive: true, encoding: "utf-8" })
    .filter((f) => f.endsWith(".css"))
    .sort();

  it("scans the stylesheets, theme.css included", () => {
    expect(files.length).toBeGreaterThan(20);
    expect(files).toContain(join("theme", "theme.css"));
  });

  it("every animated or transitioned rule has a data-motion reduce counterpart or is allowlisted", () => {
    const found = files.flatMap((file) =>
      scanCss(readFileSync(join(SRC, file), "utf-8")).map((f) => key(file, f)),
    );
    const allowed = ALLOWLIST.map(([file, selector]) => `${file} | no-counterpart | ${selector}`);
    expect(found.filter((k) => !allowed.includes(k))).toEqual([]);
    // The allowlist only shrinks: a stale entry fails here.
    expect(allowed.filter((k) => !found.includes(k))).toEqual([]);
    for (const [, , reason] of ALLOWLIST) expect(reason.length).toBeGreaterThan(10);
  });

  it("the OS query never gates entrance motion (G-1): only the data-motion fallback may read it", () => {
    for (const file of files) {
      const rules = scanCss(readFileSync(join(SRC, file), "utf-8")).map((f) => f.rule);
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

  describe("the scanner itself", () => {
    it("flags a literal animation with no counterpart", () => {
      expect(scanCss(".a { animation: spin 1s linear; }")).toEqual([
        { rule: "no-counterpart", selector: ".a" },
      ]);
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
