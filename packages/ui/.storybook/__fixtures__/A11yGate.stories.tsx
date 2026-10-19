import type { Meta, StoryObj } from "@storybook/react-vite";

/**
 * The a11y gate's self-test (E05-T03), built only with CV_STORYBOOK_A11Y_FIXTURES=1 (main.ts), never
 * published: a button whose label has a 2:1 contrast (WCAG 1.4.3 asks 4.5:1) must fail the gate
 * naming `color-contrast` and `#a11y-gate-fixture`. The colours are synthetic, not tokens.
 */
const meta: Meta = { title: "Foundations/A11y gate fixture", parameters: { layout: "centered" } };
export default meta;

export const LowContrastButton: StoryObj = {
  render: () => (
    <button
      id="a11y-gate-fixture"
      type="button"
      style={{ color: "#6D6D6D", backgroundColor: "#404040", border: "none" }}
    >
      Submit order
    </button>
  ),
};
