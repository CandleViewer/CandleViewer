import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { NumericStepperInput, type NumericStepperInputProps } from "./NumericStepperInput.js";

const REASON = "Owner only: your role can't edit this field.";

/** A controlled host, so every story steps for real; theme and density come from the toolbars. */
const Controlled = (args: NumericStepperInputProps): JSX.Element => {
  const [value, setValue] = useState(args.value);
  return (
    <NumericStepperInput
      {...args}
      value={value}
      onChange={(next) => {
        setValue(next);
        args.onChange(next);
      }}
    />
  );
};

const meta: Meta<typeof NumericStepperInput> = {
  title: "Atoms/NumericStepperInput",
  component: NumericStepperInput,
  args: { label: "Qty", value: 1, step: 0.1, precision: 1, onChange: fn(), onStep: fn() },
  render: (args) => <Controlled {...args} />,
};
export default meta;
type Story = StoryObj<typeof NumericStepperInput>;

const col = { display: "grid", gap: "var(--space-inset-md)", width: "16rem" } as const;
const input = (canvasElement: HTMLElement): HTMLInputElement =>
  within(canvasElement).getByRole("spinbutton") as HTMLInputElement;

export const Default: Story = {};

export const WithUnit: Story = {
  args: {
    label: "Auto-scale margin",
    value: 5,
    step: 1,
    precision: 0,
    min: 0,
    max: 50,
    suffix: "%",
  },
  play: async ({ canvasElement }) => {
    await expect(input(canvasElement)).toHaveAttribute("aria-valuetext", "5 %");
  },
};

export const Hover: Story = {
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("button", { name: "Increase Qty" })),
};

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
  },
};

/** Tabular figures, mono, end-aligned: the computed values, so a broken cascade fails here (AC "tabular"). */
export const Tabular: Story = {
  play: async ({ canvasElement }) => {
    const style = getComputedStyle(input(canvasElement));
    await expect(style.fontVariantNumeric).toContain("tabular-nums");
    await expect(style.textAlign).toBe("end");
    const mono = getComputedStyle(document.documentElement)
      .getPropertyValue("--type-num-base-font-family")
      .replaceAll('"', "")
      .trim();
    await expect(mono).not.toBe("");
    await expect(style.fontFamily.replaceAll('"', "")).toContain(mono);
  },
};

export const MinMaxClamped: Story = {
  args: { value: 1.8, min: 0, max: 2 },
  play: async ({ canvasElement }) => {
    const field = input(canvasElement);
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Increase Qty" }));
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Increase Qty" }));
    await expect(field).toHaveValue("2.0");
    await expect(
      within(canvasElement).getByRole("button", { name: "Increase Qty" }),
    ).toBeDisabled();
  },
};

/** Up and Down, Shift x10, Page keys by `largeStep`, Home and End; 0.1 steps stay exact. */
export const KeyboardStepDemo: Story = {
  args: { value: 0, min: 0, max: 100, largeStep: 5 },
  play: async ({ canvasElement, args }) => {
    const field = input(canvasElement);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowUp}{ArrowUp}{ArrowUp}");
    await expect(field).toHaveValue("0.3");
    await userEvent.keyboard("{Shift>}{ArrowUp}{/Shift}");
    await expect(field).toHaveValue("1.3");
    await userEvent.keyboard("{PageUp}");
    await expect(field).toHaveValue("6.3");
    await userEvent.keyboard("{End}");
    await expect(field).toHaveValue("100.0");
    await userEvent.keyboard("{Home}");
    await expect(field).toHaveValue("0.0");
    await expect(args.onStep).toHaveBeenCalledWith("up");
  },
};

/** AC "Invalid numeric entry": min 0, type -5, blur: the error shows, the value is unchanged. */
export const OutOfRangeEntry: Story = {
  args: { value: 0.5, min: 0 },
  play: async ({ canvasElement, args }) => {
    const field = input(canvasElement);
    await userEvent.clear(field);
    await userEvent.type(field, "-5");
    await userEvent.tab();
    await expect(field).toHaveAttribute("aria-invalid", "true");
    await expect(field).toHaveAttribute("aria-valuenow", "0.5");
    await expect(field).toHaveAccessibleDescription(/Minimum 0\.0/);
    await expect(args.onChange).not.toHaveBeenCalled();
  },
};

export const RoundedEntry: Story = {
  play: async ({ canvasElement }) => {
    const field = input(canvasElement);
    await userEvent.clear(field);
    await userEvent.type(field, "2.26");
    await userEvent.tab();
    await expect(field).toHaveValue("2.3");
    await expect(field).toHaveAccessibleDescription(/rounded to nearest tick/);
  },
};

export const Invalid: Story = {
  args: { invalid: true, errorMessage: "Minimum 0.001" },
  play: async ({ canvasElement }) => {
    await expect(input(canvasElement)).toHaveAttribute("aria-invalid", "true");
    await expect(input(canvasElement)).toHaveAccessibleDescription(/Minimum 0\.001/);
  },
};

export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).not.toHaveFocus();
  },
};

/** T2: the lock leads the value, step keys and buttons change nothing, the reason is announced once. */
export const DisabledWithReason: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    const field = input(canvasElement);
    await userEvent.tab();
    await expect(field).toHaveAttribute("aria-disabled", "true");
    await expect(field).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{ArrowUp}{PageUp}5{Enter}");
    await expect(field).toHaveValue("1.0");
    await expect(args.onChange).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(within(canvasElement).getByRole("status")).toHaveTextContent(REASON),
    );
  },
};

export const ReadOnly: Story = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(input(canvasElement)).toHaveFocus();
    await expect(
      within(canvasElement).getByRole("button", { name: "Increase Qty" }),
    ).toBeDisabled();
  },
};

/** A value wider than the well scrolls inside it; the buttons never grow. */
export const LongValue: Story = {
  args: { value: 123456789.12345, precision: 5, step: 0.00001, suffix: "USDT" },
  decorators: [
    (Story) => (
      <div style={{ width: "10rem" }}>
        <Story />
      </div>
    ),
  ],
};

const cells = (
  <>
    <Controlled label="Default" value={1} step={0.1} precision={1} onChange={fn()} />
    <Controlled label="At max" value={2} max={2} step={0.1} precision={1} onChange={fn()} />
    <Controlled label="Percent" value={5} step={1} precision={0} suffix="%" onChange={fn()} />
    <Controlled
      label="Invalid"
      value={1}
      step={0.1}
      precision={1}
      invalid
      errorMessage="Minimum 0.0"
      onChange={fn()}
    />
    <Controlled label="Disabled" value={1} step={0.1} precision={1} disabled onChange={fn()} />
    <Controlled
      label="Gated"
      value={1}
      step={0.1}
      precision={1}
      disabledReason={REASON}
      onChange={fn()}
    />
    <Controlled label="Read only" value={1} step={0.1} precision={1} readOnly onChange={fn()} />
    <Controlled
      label="Gated and invalid"
      value={1}
      step={0.1}
      precision={1}
      invalid
      errorMessage="Minimum 0.0"
      disabledReason={REASON}
      onChange={fn()}
    />
    <Controlled
      label="Invalid and read only"
      value={1}
      step={0.1}
      precision={1}
      invalid
      errorMessage="Minimum 0.0"
      readOnly
      onChange={fn()}
    />
    <Controlled
      label="Invalid and disabled"
      value={1}
      step={0.1}
      precision={1}
      invalid
      errorMessage="Minimum 0.0"
      disabled
      onChange={fn()}
    />
    <Controlled
      label="Compact"
      value={1}
      step={0.1}
      precision={1}
      density="compact"
      onChange={fn()}
    />
  </>
);

export const AllStates: Story = { render: () => <div style={col}>{cells}</div> };

/**
 * Light and high contrast. axe skips `aria-disabled` nodes, so the gated value's contrast is the audit's (row 88),
 * not asserted here; the invalid cue, the read-only value and the buttons are.
 */
const themed = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => <div style={col}>{cells}</div>,
});
export const GatedContrastLight: Story = themed("light");
export const GatedContrastHighContrast: Story = themed("high-contrast");
