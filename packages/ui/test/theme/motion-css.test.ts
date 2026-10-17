// @vitest-environment jsdom
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { createThemeStore } from "../../src/theme/index.js";
import { mediaStub, memoryStorage } from "./helpers.js";

const SRC = resolve(import.meta.dirname, "../../src");
const THEME_CSS = readFileSync(join(SRC, "theme/theme.css"), "utf-8");

interface Rule {
  selector: string;
  decls: Map<string, { value: string; important: boolean }>;
}

function parseRules(css: string): Rule[] {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...bare.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selector = "", body = ""]) => ({
    selector: selector.trim(),
    decls: new Map(
      [...body.matchAll(/([\w-]+)\s*:\s*([^;]*?)\s*(!important)?\s*(?:;|$)/g)].map(
        ([, prop = "", value = "", important]) => [
          prop,
          { value, important: important !== undefined },
        ],
      ),
    ),
  }));
}

const FAMILIES: Record<string, string[]> = {
  transition: ["transition-duration", "transition-delay"],
  animation: ["animation-duration", "animation-delay", "animation-iteration-count"],
  "scroll-behavior": ["scroll-behavior"],
};
const REDUCE_FORMS = ['[data-motion="reduce"] *', ":not([data-motion]) *"];

/** The contract: every animated property outside the reduce scope has an `!important` universal counterpart. */
function violations(css: string): string[] {
  const rules = parseRules(css);
  const scoped = (r: Rule): boolean =>
    REDUCE_FORMS.some((f) => r.selector.includes(f.slice(0, -2)));
  const universal = (form: string): Rule | undefined =>
    rules.find((r) => scoped(r) && r.selector.split(",").some((s) => s.trim().endsWith(form)));
  const out: string[] = [];
  for (const rule of rules.filter((r) => !scoped(r))) {
    for (const [prop, { important }] of rule.decls) {
      const family = Object.keys(FAMILIES).find((f) => prop === f || prop.startsWith(`${f}-`));
      if (family === undefined) continue;
      if (important) out.push(`${rule.selector}: ${prop} is !important`);
      for (const form of REDUCE_FORMS) {
        for (const needed of FAMILIES[family] ?? []) {
          if (universal(form)?.decls.get(needed)?.important !== true) {
            out.push(`${rule.selector}: ${prop} has no ${needed} counterpart under ${form}`);
          }
        }
      }
    }
  }
  return out;
}

describe("reduced-motion CSS contract", () => {
  it("every animated property declared in packages/ui has a reduce counterpart", () => {
    const files = readdirSync(SRC, { recursive: true, encoding: "utf-8" }).filter((f) =>
      f.endsWith(".css"),
    );
    expect(files).toContain(join("theme", "theme.css"));
    for (const file of files)
      expect(violations(readFileSync(join(SRC, file), "utf-8")), file).toEqual([]);
    expect(THEME_CSS).toContain("@media (prefers-reduced-motion: reduce)");
    const withAnimated = `${THEME_CSS}.a{transition:opacity 1s;animation:spin 1s;scroll-behavior:smooth}`;
    expect(violations(withAnimated)).toEqual([]);
  });

  it("the gate itself fails on a missing counterpart or an !important animation", () => {
    expect(violations(".a{transition:opacity 1s}")).toHaveLength(4);
    expect(violations(`${THEME_CSS}.a{animation-name:spin !important}`)).toEqual([
      ".a: animation-name is !important",
    ]);
    const partial = THEME_CSS.replaceAll("transition-delay: 0s !important;", "");
    expect(violations(`${partial}.a{transition-duration:1s}`)).toHaveLength(2);
  });
});

describe("theme.css behaviour (jsdom cascade)", () => {
  function setup(extra = ""): ReturnType<typeof createThemeStore> {
    const style = document.head.appendChild(document.createElement("style"));
    style.textContent = `${extra}${THEME_CSS}`;
    const store = createThemeStore({
      storage: memoryStorage(),
      matchMedia: mediaStub().matchMedia,
    });
    store.connect();
    return store;
  }
  const rootStyle = (name: string): string =>
    getComputedStyle(document.documentElement).getPropertyValue(name);

  it("no transition runs under reduced motion; the authored duration returns when motion is allowed", () => {
    const store = setup(".t{transition-duration:200ms}");
    const el = document.body.appendChild(document.createElement("div"));
    el.className = "t";
    const duration = (): string => getComputedStyle(el).transitionDuration;
    expect(duration()).toBe("200ms");
    store.setMotionOverride("on");
    expect(duration()).toBe("0.01ms");
    expect(rootStyle("--cv-motion-scale")).toBe("0");
    store.setMotionOverride("off");
    expect(duration()).toBe("200ms");
    document.head.querySelector("style")?.remove();
  });

  it("density re-points the row and control aliases at the matching scale step", () => {
    const store = setup();
    expect(rootStyle("--size-row-height")).toBe("var(--size-row-compact)");
    store.setDensity("comfortable");
    expect(rootStyle("--size-row-height")).toBe("var(--size-row-comfortable)");
    expect(rootStyle("--size-control-height")).toBe("var(--size-control-comfortable)");
    document.head.querySelector("style")?.remove();
  });
});
