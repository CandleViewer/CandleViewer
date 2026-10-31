import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { recipeSafe } from "./css-contract.js";

const read = (name: string): string =>
  readFileSync(resolve(import.meta.dirname, `../src/components/${name}`), "utf-8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );

interface Block {
  readonly selectors: readonly string[];
  readonly body: string;
}
const blocks = (css: string): Block[] =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: (m[1] ?? "").split(/,(?![^(]*\))/).map((s) => s.replace(/\s+/g, " ").trim()),
    body: m[2] ?? "",
  }));
const rule = (css: string, sel: string): string =>
  blocks(css)
    .filter((b) => b.selectors.includes(sel))
    .map((b) => b.body)
    .join("\n");
/** The CSS outside any forced-colours or reduced-motion scope. */
const normalOf = (css: string): string =>
  (css.split("@media (forced-colors: active)")[0] ?? "").split(':root[data-motion="reduce"]')[0] ??
  "";
const forcedOf = (css: string): string =>
  (css.split("@media (forced-colors: active)")[1] ?? "").split(':root[data-motion="reduce"]')[0] ??
  "";

const PAINT = /(^|[\s;])(background|color|border-color)\s*:/;
const RAW = /#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|\b\d+(\.\d+)?px\b/i;

describe.each(["skeleton.css", "progress.css"])("%s contract", (file) => {
  const css = read(file);
  const normal = normalOf(css);
  const forced = forcedOf(css);

  it("paints with tokens only: no raw colour, and no raw px outside a unit conversion", () => {
    for (const b of blocks(normal)) {
      const body = b.body.replace(/\*\s*-?[\d.]+px\)/g, ")");
      expect(body, b.selectors.join(", ")).not.toMatch(RAW);
    }
  });

  it("forced colours use system colours only, and repaint every painting selector", () => {
    expect(forced.length).toBeGreaterThan(0);
    expect(forced).not.toContain("var(--");
    const painted = blocks(forced).flatMap((b) => (PAINT.test(b.body) ? b.selectors : []));
    for (const b of blocks(normal)) {
      if (!/(^|[\s;])(background|color)\s*:/.test(b.body)) continue;
      for (const s of b.selectors) expect(painted, `${s} has no forced twin`).toContain(s);
    }
  });
});

describe("skeleton.css motion", () => {
  const css = read("skeleton.css");
  const band = ".cv-skeleton__block::after";

  it("the shimmer is a transform on the band, 1,200 ms a sweep, stopped before 5 s", () => {
    const body = rule(normalOf(css), band);
    expect(body).toContain("animation: var(--cv-recipe-skeleton-sweep)");
    const safe = recipeSafe("skeleton-sweep");
    expect(safe).toMatch(
      /^cv-skeleton-sweep calc\(var\(--motion-duration-slow\) \* 3\) linear (\d+)$/,
    );
    const sweeps = Number(/linear (\d+)/.exec(safe)?.[1]);
    expect(sweeps * 1200).toBeLessThanOrEqual(5000);
    const frames = /@keyframes cv-skeleton-sweep\s*\{([\s\S]*?)\}\s*\}/.exec(css)?.[1] ?? "";
    expect(frames.replace(/[^:]*\{|\}/g, "").trim()).toMatch(/^transform:/);
  });

  it("reduced motion, in-app and OS, removes the band from the first frame (#265 Gherkin)", () => {
    const app = rule(css, `:root[data-motion="reduce"] ${band}`);
    expect(app).toContain("display: none");
    expect(app).toContain("animation: none");
    const media = css.split("@media (prefers-reduced-motion: reduce)")[1] ?? "";
    const os = rule(media, `:root:not([data-motion]) ${band}`);
    expect(os).toContain("display: none");
    expect(os).toContain("animation: none");
  });

  it("an overlay host moves the blocks to selected and the sweep to hover", () => {
    const overlay = rule(css, '.cv-skeleton[data-surface="overlay"]');
    expect(overlay).toContain("--cv-skeleton-fill: var(--color-surface-selected)");
    expect(overlay).toContain("--cv-skeleton-sweep: var(--color-surface-hover)");
  });

  it("forced colours drop the fills and hide the band", () => {
    const forced = forcedOf(css);
    expect(rule(forced, ".cv-skeleton__block")).toContain("background: Canvas");
    expect(rule(forced, band)).toContain("display: none");
  });
});

describe("progress.css", () => {
  const css = read("progress.css");

  it("the track is 8 px (twice space.inset.xs) and the fill moves by transform only", () => {
    expect(rule(css, ".cv-progress__track")).toContain("height: calc(var(--space-inset-xs) * 2)");
    const fill = rule(normalOf(css), ".cv-progress__fill");
    expect(fill).toContain("transform: scaleX(var(--cv-progress))");
    expect(fill).toMatch(/transition: transform var\(--motion-duration-normal\)/);
    expect(css).not.toMatch(/animation/);
    expect(rule(css, '[dir="rtl"] .cv-progress__fill')).toContain("transform-origin: right");
  });

  it("tones bind the D02 H4 fills; warning uses .strong", () => {
    const tone = (t: string): string => rule(css, `.cv-progress[data-tone="${t}"]`);
    expect(tone("success")).toContain("var(--color-status-success-default)");
    expect(tone("warning")).toContain("var(--color-status-warning-strong)");
    expect(tone("danger")).toContain("var(--color-status-danger-default)");
  });

  it("forced colours: a Highlight fill kept by forced-color-adjust on a bordered Canvas track", () => {
    const forced = forcedOf(css);
    expect(rule(forced, ".cv-progress__fill")).toMatch(
      /forced-color-adjust: none;[\s\S]*Highlight/,
    );
    expect(rule(forced, ".cv-progress__track")).toContain("border: 1px solid CanvasText");
  });

  it("reduced motion makes a new value a step", () => {
    expect(rule(css, ':root[data-motion="reduce"] *')).toContain(
      "transition-duration: 0.01ms !important",
    );
  });
});
