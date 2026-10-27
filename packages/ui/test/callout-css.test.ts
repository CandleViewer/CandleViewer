import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("callout.css");

describe("callout.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("box: radius.card, inset.sm block and inset.md inline padding, inset.sm glyph gap", () => {
    const base = find(css.normal, ".cv-callout", "border-radius");
    expect(base).toContain("border-radius: var(--radius-card)");
    expect(base).toContain("padding-block: var(--space-inset-sm)");
    expect(base).toContain("padding-inline: var(--space-inset-md)");
    expect(base).toContain("gap: var(--space-inset-sm)");
  });

  it("a 2px border.thick start edge in the tone's .strong, on the tone's subtle fill", () => {
    const base = find(css.normal, ".cv-callout", "border-inline-start");
    expect(base).toContain(
      "border-inline-start: calc(var(--border-thick) * 1px) solid var(--cv-callout-strong)",
    );
    expect(base).toContain("background: var(--cv-callout-fill)");
    expect(find(css.normal, ".cv-callout__glyph", "color")).toContain("var(--cv-callout-strong)");
  });

  it.each(["info", "success", "warning"])("%s binds its own status pair", (tone) => {
    const body =
      tone === "info"
        ? find(css.normal, ".cv-callout", "--cv-callout-fill")
        : find(css.normal, `.cv-callout[data-tone="${tone}"]`, "--cv-callout-fill");
    expect(body).toContain(`--cv-callout-fill: var(--color-status-${tone}-subtle)`);
    expect(body).toContain(`--cv-callout-strong: var(--color-status-${tone}-strong)`);
  });

  it.each(["danger", "connection-reconnecting", "connection-disconnected"])(
    "%s draws on the danger pair (the data-confidence accents stay off the fill)",
    (tone) => {
      const body = find(css.normal, `.cv-callout[data-tone="${tone}"]`, "--cv-callout-fill");
      expect(body).toContain("--cv-callout-fill: var(--color-status-danger-subtle)");
      expect(body).toContain("--cv-callout-strong: var(--color-status-danger-strong)");
      expect(css.all).not.toMatch(/data-confidence/);
    },
  );

  it("type: title body-strong in text.primary, body and details body in text.secondary", () => {
    const title = find(css.normal, ".cv-callout__title", "font");
    expect(title).toContain("--type-ui-body-strong-font-size");
    expect(title).toContain("color: var(--color-text-primary)");
    const body = find(css.normal, ".cv-callout__body", "font");
    expect(body).toContain("--type-ui-body-font-size");
    expect(body).toContain("color: var(--color-text-secondary)");
    expect(find(css.normal, ".cv-callout__details", "font")).toBe(body);
  });

  it("band: full width and square", () => {
    const band = find(css.normal, '.cv-callout[data-placement="band"]', "border-radius");
    expect(band).toContain("border-radius: 0");
    expect(band).toContain("width: 100%");
  });

  it("actions wrap under the body, inset.sm apart", () => {
    const actions = find(css.normal, ".cv-callout__actions", "flex-wrap");
    expect(actions).toContain("flex-wrap: wrap");
    expect(actions).toContain("gap: var(--space-inset-sm)");
  });

  it("no motion: no transition and no animation (the dismissal fade waits for E05-D03)", () => {
    expect(css.all).not.toMatch(/transition/);
    expect(css.all).not.toMatch(/animation|@keyframes/);
  });

  it("no ring or dimming of its own: its buttons draw theirs", () => {
    expect(css.all).not.toMatch(/focus|outline|opacity/);
  });

  it("no hatched edge yet: the PROPOSED pattern token is deferred", () => {
    expect(css.all).not.toMatch(/hatch|repeating-linear-gradient/);
  });

  it("forced colours: the fill drops, a CanvasText border and edge, glyph and words CanvasText", () => {
    const box = find(css.forced, ".cv-callout[data-tone]", "border");
    expect(box).toContain("border: 1px solid CanvasText");
    expect(box).toContain("border-inline-start: 2px solid CanvasText");
    expect(box).toContain("background: Canvas");
    expect(find(css.forced, ".cv-callout__glyph", "color")).toContain("CanvasText");
    expect(find(css.forced, ".cv-callout__title", "color")).toContain("CanvasText");
  });
});
