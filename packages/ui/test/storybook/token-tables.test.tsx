// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { within } from "storybook/test";
import { describe, expect, it } from "vitest";
import { TokenTables, tokenRows } from "../../src/docs/TokenTables.js";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TOKENS = {
  border: { focus: "2" },
  color: { buy: { default: "#2EBD59", subtle: "#0E3D1F" } },
  elevation: { "1": { offsetX: "0", offsetY: "1", blur: "2", spread: "0", color: "#00000066" } },
  font: { family: { ui: ["Inter"] } },
  space: { button: { paddingX: "12", paddingY: "6" } },
} as const;

describe("Foundations token tables", () => {
  it("lists every token with the custom property the theme bundles define for it", () => {
    expect(tokenRows(TOKENS)).toEqual([
      { path: "border.focus", property: "--border-focus", value: "2" },
      { path: "color.buy.default", property: "--color-buy-default", value: "#2EBD59" },
      { path: "color.buy.subtle", property: "--color-buy-subtle", value: "#0E3D1F" },
      {
        path: "elevation.1", // a composite (shadow) value is one token, not a group
        property: "--elevation-1",
        value: '{"offsetX":"0","offsetY":"1","blur":"2","spread":"0","color":"#00000066"}',
      },
      { path: "font.family.ui", property: "--font-family-ui", value: '["Inter"]' },
      { path: "space.button.paddingX", property: "--space-button-paddingX", value: "12" },
      { path: "space.button.paddingY", property: "--space-button-paddingY", value: "6" },
    ]);
  });

  it("lists a typography token as one row per field, each with the custom property the bundles define", () => {
    // The bundles write `--type-ui-label-font-size` and its siblings, never one `--type-ui-label`.
    const type = {
      ui: {
        label: {
          fontFamily: ["Inter"],
          fontSize: "12",
          fontWeight: "500",
          letterSpacing: "0.2",
          lineHeight: "1.2",
        },
      },
    };
    expect(tokenRows({ type })).toEqual([
      {
        path: "type.ui.label.fontFamily",
        property: "--type-ui-label-font-family",
        value: '["Inter"]',
      },
      { path: "type.ui.label.fontSize", property: "--type-ui-label-font-size", value: "12" },
      { path: "type.ui.label.fontWeight", property: "--type-ui-label-font-weight", value: "500" },
      {
        path: "type.ui.label.letterSpacing",
        property: "--type-ui-label-letter-spacing",
        value: "0.2",
      },
      { path: "type.ui.label.lineHeight", property: "--type-ui-label-line-height", value: "1.2" },
    ]);
  });

  it("renders one captioned table per group, colour rows with a swatch of the live property", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () => root.render(<TokenTables tokens={TOKENS} />));
    const tables = within(host).getAllByRole("table");
    expect(tables.map((table) => table.querySelector("caption")?.textContent)).toEqual([
      "border",
      "color",
      "elevation",
      "font",
      "space",
    ]);
    const buy = within(host).getByRole("rowheader", { name: "color.buy.default" }).closest("tr");
    const swatch = buy?.querySelector<HTMLElement>("[aria-hidden='true']");
    expect(swatch?.style.getPropertyValue("background-color")).toBe(
      "var(--color-buy-default, #2EBD59)",
    );
    expect(buy?.textContent).toContain("#2EBD59"); // the value is text too, never colour alone
    const focus = within(host).getByRole("rowheader", { name: "border.focus" }).closest("tr");
    expect(focus?.querySelector("[aria-hidden='true']")).toBeNull();
    await act(async () => root.unmount());
  });
});
