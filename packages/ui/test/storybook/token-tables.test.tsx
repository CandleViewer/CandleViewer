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
