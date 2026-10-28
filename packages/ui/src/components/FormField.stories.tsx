import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import { FormField } from "./FormField.js";
import { NumericStepperInput } from "./NumericStepperInput.js";
import { Select } from "./Select.js";
import { TextInput } from "./TextInput.js";

const ERROR = "Enter your username.";
const HELP = "(rounded to nearest tick)";
const REASON = "Your role can't change settings.";
const noop = (): void => undefined;
const options = [
  { value: "market", label: "Market" },
  { value: "limit", label: "Limit" },
];

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof FormField> = {
  title: "Molecules/FormField",
  component: FormField,
  args: { label: "Username", children: <TextInput defaultValue="trader_01" /> },
  decorators: [
    (Story) => (
      <div style={{ width: "20rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof FormField>;

const col = { display: "grid", gap: "var(--space-stack-lg)" } as const;
const textbox = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("textbox");

/** The label is persistent and names the field; it is never a placeholder. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(textbox(canvasElement)).toHaveAccessibleName("Username");
  },
};

/** The error line: the danger glyph and the words, polite, once; the control takes aria-invalid. */
export const WithError: Story = {
  args: { error: ERROR, help: "Letters, digits and underscores." },
  play: async ({ canvasElement }) => {
    const field = textbox(canvasElement);
    await expect(field).toHaveAttribute("aria-invalid", "true");
    await expect(field).toHaveAccessibleDescription(`${ERROR} Letters, digits and underscores.`);
    await expect(within(canvasElement).getAllByText(ERROR)).toHaveLength(1);
  },
};

export const WithHelp: Story = {
  args: { label: "Price", help: HELP, children: <TextInput defaultValue="64 250.5" /> },
  play: async ({ canvasElement }) => {
    // The empty error node comes first in the chain; only the help has words.
    await expect(textbox(canvasElement)).toHaveAccessibleDescription(
      /^\s?\(rounded to nearest tick\)$/,
    );
  },
};

/** Required sets aria-required and draws no asterisk. */
export const Required: Story = {
  args: { required: true },
  play: async ({ canvasElement }) => {
    await expect(textbox(canvasElement)).toBeRequired();
    await expect(canvasElement).not.toHaveTextContent("*");
  },
};

export const Optional: Story = {
  args: { label: "Display name", optional: true, children: <TextInput defaultValue="" /> },
  play: async ({ canvasElement }) => {
    await expect(textbox(canvasElement)).toHaveAccessibleName("Display name (optional)");
  },
};

/** The order ticket's label column (E30-D02 §2): the host sizes it; the row stacks below its fit width. */
export const Inline: Story = {
  args: {
    label: "Qty",
    layout: "inline",
    labelWidth: "calc(var(--size-control-height) * 3)",
    children: <TextInput defaultValue="0.010" suffix="BTC" />,
  },
};

/** Inline in a narrow host: the label column and the control no longer fit, so the field stacks. */
export const InlineNarrow: Story = {
  ...Inline,
  decorators: [
    (Story) => (
      <div style={{ width: "8rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const label = within(canvasElement).getByText("Qty");
    const field = textbox(canvasElement);
    await expect(label.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      field.getBoundingClientRect().top,
    );
  },
};

export const ReadOnly: Story = {
  args: { children: <TextInput defaultValue="trader_01" readOnly /> },
  play: async ({ canvasElement }) => {
    await expect(textbox(canvasElement)).toHaveAttribute("readonly");
  },
};

export const Disabled: Story = {
  args: { disabled: true, help: "Set when the account is created." },
  play: async ({ canvasElement }) => {
    await expect(textbox(canvasElement)).toBeDisabled();
  },
};

/** T2 (2a): the label unchanged, the lock in the well, the reason line under it and the description alone. */
export const DisabledWithReason: Story = {
  args: { disabledReason: REASON, error: ERROR, help: "Letters, digits and underscores." },
  play: async ({ canvasElement }) => {
    const field = textbox(canvasElement);
    await userEvent.tab();
    await expect(field).toHaveFocus();
    await expect(field).toHaveAttribute("aria-disabled", "true");
    await expect(field).not.toHaveAttribute("aria-invalid");
    await expect(field).toHaveAccessibleDescription(REASON);
    await expect(within(canvasElement).getAllByText(REASON)).toHaveLength(1);
    await expect(within(canvasElement).getByRole("img", { name: "Not available" })).toBeVisible();
  },
};

/** A div combobox is named through aria-labelledby, and a press on the label focuses it. */
export const WithSelect: Story = {
  args: {
    label: "Order type",
    help: "Market fills at the best price.",
    children: <Select options={options} value="market" onChange={noop} />,
  },
  play: async ({ canvasElement }) => {
    const combo = within(canvasElement).getByRole("combobox", { name: "Order type" });
    await userEvent.click(within(canvasElement).getByText("Order type"));
    await expect(combo).toHaveFocus();
  },
};

/** The stepper's own parse error shows once, in the field's line. */
export const WithStepper: Story = {
  args: {
    label: "Leverage",
    help: "1 to 100.",
    children: (
      <NumericStepperInput
        label="Leverage"
        value={10}
        min={1}
        max={100}
        step={1}
        precision={0}
        onChange={noop}
      />
    ),
  },
  play: async ({ canvasElement }) => {
    const spin = within(canvasElement).getByRole("spinbutton", { name: "Leverage" });
    await userEvent.clear(spin);
    await userEvent.type(spin, "500");
    await userEvent.tab();
    await expect(spin).toHaveAttribute("aria-invalid", "true");
    await expect(within(canvasElement).getAllByText("Maximum 100")).toHaveLength(1);
  },
};

/** Every catalogued variant and state at once, for the theme x density sweep. */
export const AllStates: Story = {
  render: () => (
    <div style={col}>
      <FormField label="Default">
        <TextInput defaultValue="trader_01" />
      </FormField>
      <FormField label="Invalid" error={ERROR}>
        <TextInput defaultValue="" />
      </FormField>
      <FormField label="Help" help={HELP}>
        <TextInput defaultValue="64 250.5" />
      </FormField>
      <FormField label="Display name" optional>
        <TextInput defaultValue="" />
      </FormField>
      <FormField label="Disabled" disabled help="Set when the account is created.">
        <TextInput defaultValue="trader_01" />
      </FormField>
      <FormField label="Gated" disabledReason={REASON}>
        <TextInput defaultValue="trader_01" />
      </FormField>
      <FormField label="Read only">
        <TextInput defaultValue="trader_01" readOnly />
      </FormField>
      <FormField label="Qty" layout="inline" labelWidth="calc(var(--size-control-height) * 3)">
        <TextInput defaultValue="0.010" suffix="BTC" />
      </FormField>
      <FormField
        label="A long label that wraps onto a second line in a narrow column"
        help="A long help line that wraps under the control instead of clipping or overflowing."
      >
        <TextInput defaultValue="" />
      </FormField>
    </div>
  ),
};
