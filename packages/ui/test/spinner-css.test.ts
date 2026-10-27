// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(
  resolve(import.meta.dirname, "../src/components/spinner.css"),
  "utf-8",
).replace(/\/\*[\s\S]*?\*\//g, "");
const [motion = "", forced = ""] = CSS.split("@media (forced-colors: active)");

const body = (css: string, selector: string): string =>
  [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => (m[1] ?? "").split(",").some((s) => s.replace(/\s+/g, " ").trim() === selector))
    .map((m) => m[2] ?? "")
    .join(";");

describe("spinner.css contract (CMP-014)", () => {
  it("reduced motion stops the rotation: the in-app override and the OS preference", () => {
    expect(body(CSS, ':root[data-motion="reduce"] .cv-spinner__arc')).toContain("animation: none");
    const os = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?\}\s*)\}/.exec(motion)?.[1];
    expect(body(os ?? "", ":root:not([data-motion]) .cv-spinner__arc")).toContain(
      "animation: none",
    );
    // Rotation is the only animation: nothing else in the file animates or transitions.
    expect(CSS.match(/animation:/g)).toHaveLength(3);
    expect(CSS).not.toContain("transition");
  });

  it('OS reduce with an explicit data-motion="safe" still rotates: the in-app override wins', () => {
    // Treat the OS query as matching (unwrap its blocks), then see which animation rules match the arc.
    const osReduce = motion.replace(
      /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?\})\s*\}/g,
      "$1",
    );
    const rules = [...osReduce.matchAll(/([^{}]+)\{([^{}]*animation[^{}]*)\}/g)].flatMap((m) =>
      (m[1] ?? "")
        .split(",")
        .map((sel) => [sel.trim().replace(/::(before|after)$/, ""), m[2] ?? ""]),
    );
    const arc = document.body.appendChild(document.createElement("span"));
    arc.className = "cv-spinner__arc";
    const root = document.documentElement;
    const applied = (motionAttr: string | null): string => {
      if (motionAttr === null) root.removeAttribute("data-motion");
      else root.setAttribute("data-motion", motionAttr);
      return rules
        .filter(([sel]) => arc.matches(sel ?? ""))
        .map(([, body]) => body)
        .join(";");
    };
    expect(applied("safe")).toContain("animation: cv-spin");
    expect(applied("safe")).not.toMatch(/animation: none|animation-duration/);
    expect(applied(null)).toContain("animation: none");
    expect(applied("reduce")).toContain("animation: none");
    root.removeAttribute("data-motion");
    arc.remove();
  });

  it("sizes: md is the control height, sm the icon size; a fixed square", () => {
    const md = body(CSS, ".cv-spinner");
    expect(md).toContain("width: var(--size-control-height)");
    expect(md).toContain("height: var(--size-control-height)");
    const sm = body(CSS, '.cv-spinner[data-size="sm"]');
    expect(sm).toContain("width: var(--size-icon)");
    expect(sm).toContain("height: var(--size-icon)");
  });

  it("the arc is a 2px currentColor stroke; standalone takes the primary action colour", () => {
    const arc = body(CSS, ".cv-spinner__arc circle");
    expect(arc).toContain("stroke: currentcolor");
    expect(arc).toContain("stroke-width: calc(var(--border-thick) * 1px)");
    expect(arc).toContain("stroke-linecap: round");
    expect(body(CSS, ".cv-spinner[data-standalone]")).toContain(
      "color: var(--color-action-primary-default)",
    );
    expect(CSS).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });

  it("forced colours: the standalone arc is CanvasText, system colours only", () => {
    expect(forced).not.toMatch(/var\(--/);
    expect(body(forced, ".cv-spinner[data-standalone]")).toContain("color: CanvasText");
  });
});
