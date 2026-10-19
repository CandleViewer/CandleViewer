import type { Meta, StoryObj } from "@storybook/react-vite";
import { Placeholder } from "./Placeholder.js";

// Placeholder story (E02-T03): proves the Storybook + a11y addon harness
// runs before real components exist. Only variant needed is "default" since
// this component has no interactive/disabled/error states.
const meta: Meta<typeof Placeholder> = {
  title: "Foundations/Placeholder",
  component: Placeholder,
};

export default meta;
type Story = StoryObj<typeof Placeholder>;

export const Default: Story = {
  args: { label: "CandleViewer" },
};
