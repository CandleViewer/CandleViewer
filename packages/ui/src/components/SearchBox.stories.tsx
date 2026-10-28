import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { SearchBox } from "./SearchBox.js";

const LABEL = "Search users";
const noop = (): void => undefined;

/** A host that owns the query, as every consumer does. */
const Host = ({
  initial = "",
  disabled = false,
}: {
  readonly initial?: string;
  readonly disabled?: boolean;
}): JSX.Element => {
  const [value, setValue] = useState(initial);
  return (
    <SearchBox
      label={LABEL}
      placeholder="Search by name or email"
      value={value}
      onChange={setValue}
      onClear={() => setValue("")}
      disabled={disabled}
    />
  );
};

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof SearchBox> = {
  title: "Molecules/SearchBox",
  component: SearchBox,
  args: { label: LABEL, value: "", onChange: noop, onClear: noop },
  decorators: [
    (Story) => (
      <div style={{ width: "20rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SearchBox>;

/** Value=empty: the leading glyph and the host's placeholder; no clear button. */
export const Default: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("searchbox", { name: LABEL })).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "Clear search" })).toBeNull();
  },
};

/** Value=filled: the clear button shows; Esc clears and keeps focus. */
export const WithValue: Story = {
  render: () => <Host initial="alex" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByRole("searchbox", { name: LABEL });
    await expect(field).toHaveValue("alex");
    await expect(canvas.getByRole("button", { name: "Clear search" })).toBeVisible();
    field.focus();
    await userEvent.keyboard("{Escape}");
    await expect(field).toHaveValue("");
    await expect(field).toHaveFocus();
  },
};

/** Clear by keyboard: Enter on the button clears and returns focus to the field. */
export const ClearReturnsFocus: Story = {
  render: () => <Host initial="alex" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    canvas.getByRole("button", { name: "Clear search" }).focus();
    await userEvent.keyboard("{Enter}");
    const field = canvas.getByRole("searchbox", { name: LABEL });
    await expect(field).toHaveValue("");
    await expect(field).toHaveFocus();
  },
};

/** Focus-visible: the ring around the well. */
export const Focused: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("searchbox")).toHaveFocus();
  },
};

/** Plain disabled: native, out of the Tab order, the whole well dims. */
export const Disabled: Story = {
  render: () => <Host disabled />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("searchbox", { name: LABEL })).toBeDisabled();
  },
};

/** A long query scrolls inside the well; the clear button keeps its place. */
export const LongText: Story = {
  render: () => <Host initial="alex.morgan.account-manager-for-the-eu-desk@example.invalid" />,
};

const col = { display: "grid", gap: "var(--space-stack-lg)" } as const;

/** Every catalogued state on one canvas, for the visual matrix (E05-T04). */
export const AllStates: Story = {
  render: () => (
    <div style={col}>
      <SearchBox label="Empty" value="" onChange={noop} onClear={noop} placeholder="Search" />
      <SearchBox label="Filled" value="alex" onChange={noop} onClear={noop} />
      <SearchBox label="Disabled" value="" onChange={noop} onClear={noop} disabled />
    </div>
  ),
};
