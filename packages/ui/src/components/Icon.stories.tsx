import type { Meta, StoryObj } from "@storybook/react-vite";
import { Icon } from "./Icon.js";

/** The #271 contract's stub: E05-T06's slices add FullSet and SizeScale with the real set. */
const meta: Meta<typeof Icon> = { title: "Atoms/Icon", component: Icon, args: { name: "lock" } };
export default meta;
type Story = StoryObj<typeof Icon>;

export const Default: Story = {};
export const Labelled: Story = { args: { name: "check", decorative: false, label: "Done" } };
export const SizeLarge: Story = { args: { size: "lg" } };
