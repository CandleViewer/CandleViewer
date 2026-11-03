import { describe, expect, it } from "vitest";
import { find, itIsTokenOnlyAndStatic, loadCss } from "./css-contract.js";

const css = loadCss("keyvaluerow.css");
const { normal, forced } = css;

describe("keyvaluerow.css contract", () => {
  itIsTokenOnlyAndStatic(css);

  it("row: size.row.height minimum, space.inset.sm gap, space.stack.xs between rows", () => {
    const row = find(normal, ".cv-kv", "min-height");
    expect(row).toContain("min-height: var(--size-row-height)");
    expect(row).toContain("gap: var(--space-inset-sm)");
    expect(find(normal, ".cv-kv + .cv-kv", "margin-block-start")).toContain("--space-stack-xs");
  });

  it("label type.ui.label secondary; value type.ui.body primary, end-aligned; missing secondary", () => {
    const label = find(normal, ".cv-kv__label", "color");
    expect(label).toContain("color: var(--color-text-secondary)");
    expect(label).toContain("--type-ui-label-font-size");
    const value = find(normal, ".cv-kv__value", "color");
    expect(value).toContain("color: var(--color-text-primary)");
    expect(value).toContain("--type-ui-body-font-size");
    expect(value).toContain("justify-content: flex-end");
    expect(find(normal, ".cv-kv__value[data-missing]", "color")).toContain(
      "--color-text-secondary",
    );
  });

  it("label: breaks between words, never inside one, in a host that breaks anywhere (CMP-178's)", () => {
    // A-5330-04: "Maintenance" broke as "Maintenanc / e" in a 307 px tile; the value wraps instead.
    expect(find(normal, ".cv-kv__label", "overflow-wrap")).toContain("overflow-wrap: break-word");
  });

  it("stacked and emphasis: start-aligned column; a base number steps up to type.num.md", () => {
    expect(find(normal, '.cv-kv[data-layout="stacked"]', "flex-direction")).toContain("column");
    expect(
      find(
        normal,
        '.cv-kv[data-emphasis] .cv-kv__value .cv-num[data-size="base"]',
        "--cv-num-size",
      ),
    ).toContain("var(--type-num-md-font-size)");
  });

  it("forced colours: label, value and the dash are CanvasText", () => {
    expect(find(forced, ".cv-kv__value[data-missing]", "color")).toContain("CanvasText");
    expect(find(forced, ".cv-kv__label", "color")).toContain("CanvasText");
  });
});
