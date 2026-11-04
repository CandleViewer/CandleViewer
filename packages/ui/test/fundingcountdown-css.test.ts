import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("fundingcountdown.css");
const { normal, forced } = css;

describe("fundingcountdown.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("the under-5-minutes glyph takes color.status.warning.strong", () => {
    expect(find(normal, ".cv-funding__warn", "color")).toContain("--color-status-warning-strong");
  });

  it("the rate is color.text.primary with its sign as text, never a side hue (E24-D03 §5.1, C4, A-3)", () => {
    expect(find(normal, ".cv-funding .cv-funding__rate", "color")).toContain(
      "--color-text-primary",
    );
    expect(css.all).not.toMatch(/data-sign|--color-buy|--color-sell/);
  });

  it("the < 5 min border is reserved in every state and coloured only when settling (no shift)", () => {
    expect(find(normal, ".cv-funding", "border")).toContain("transparent");
    expect(find(normal, '.cv-funding[data-state="settling"]', "border-color")).toContain(
      "--color-status-warning-default",
    );
  });

  it("never uses the disabled colour or opacity (G-T2.2)", () => {
    expect(css.all).not.toMatch(/text-disabled|opacity/);
  });

  it("sentences wrap rather than clip at 200 % zoom (R1)", () => {
    expect(find(normal, ".cv-funding__note", "overflow-wrap")).toContain("anywhere");
  });

  it("forced colours: every colour carrier is CanvasText (R2)", () => {
    expect(forced).toContain("color: CanvasText");
    expect(forced).toContain(".cv-funding__warn");
    expect(forced).toContain(".cv-funding .cv-funding__rate");
  });
});
