import type { Meta, StoryObj } from "@storybook/react-vite";
import { CloseIcon } from "../../src/icons/index.js";

/**
 * The icon rule's a11y gate fixture (E05-T06), built only with CV_STORYBOOK_A11Y_FIXTURES=1
 * (main.ts), never published: an icon-only button without an aria-label has no accessible name, as
 * its icon is aria-hidden, so the gate must fail it naming `button-name` and
 * `#icon-only-gate-fixture`. The `candleviewer/icon-only-control-label` lint rule fails the same
 * markup (test/eslint-rules/icon-a11y.test.ts).
 */
const meta: Meta = {
  title: "Foundations/Icon a11y gate fixture",
  parameters: { layout: "centered" },
};
export default meta;

export const IconOnlyButtonWithoutLabel: StoryObj = {
  render: () => (
    <button id="icon-only-gate-fixture" type="button">
      <CloseIcon />
    </button>
  ),
};
