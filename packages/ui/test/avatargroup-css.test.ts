import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("avatargroup.css");
const { normal, forced } = css;
/** Both targets of the cut-out ring: every avatar in the group and the +N chip. */
const RING = [".cv-avatar-group .cv-avatar", ".cv-avatar-group__more"] as const;

describe("avatargroup.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("overlaps through fixed size.icon slots, never a negative gap, in one unwrapped row", () => {
    expect(find(normal, ".cv-avatar-group__slot", "width")).toContain("width: var(--size-icon)");
    expect(find(normal, ".cv-avatar-group", "flex-wrap")).toContain("flex-wrap: nowrap");
    expect(css.all).not.toMatch(/margin[^:]*:\s*-|gap:\s*-/);
  });

  it("the cut-out ring is a border.thick outline in a host-settable custom property, canvas by default", () => {
    for (const target of RING) {
      const ring = find(normal, target, "outline");
      expect(ring).toContain("calc(var(--border-thick) * 1px)");
      expect(ring).toContain("var(--cv-avatar-group-ring, var(--color-surface-canvas))");
    }
    expect(css.all).not.toMatch(/box-shadow/);
  });

  it("the +N chip: size.control.height minimum, neutral fill, text.secondary num.sm numeral", () => {
    const chip = find(normal, ".cv-avatar-group__more", "min-width");
    expect(chip).toContain("min-width: var(--size-control-height)");
    expect(chip).toContain("background: var(--color-neutral-subtle)");
    expect(chip).toContain("color: var(--color-text-secondary)");
    expect(chip).toContain("--type-num-sm-font-size");
  });

  it("forced colours: a CanvasText ring, and a CanvasText border and numeral on the chip", () => {
    for (const target of RING) {
      expect(find(forced, target, "outline-color")).toContain("outline-color: CanvasText");
    }
    const chip = find(forced, ".cv-avatar-group__more", "border-color");
    expect(chip).toContain("border-color: CanvasText");
    expect(chip).toContain("color: CanvasText");
  });
});
