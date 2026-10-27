import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Select, type SelectProps } from "./Select.js";

const REASON = "Owner only: your role can't change this account.";
const ERROR = "Choose an account.";
/** The T2 option sample (D02F §7 CMP-009; the registered `rbac.account_read_only` copy). */
const T2_OPTION = {
  value: "sub_002",
  label: "sub_002",
  disabledReason: "You can view this account, not trade it.",
};
const OPTIONS = [
  { value: "main", label: "Main account" },
  { value: "sub1", label: "Sub-account 1" },
  { value: "sub2", label: "Sub-account 2 (frozen)", disabled: true },
  { value: "sub3", label: "Sub-account 3" },
];

/** A stateful host: the atom is controlled, so every story wires `value` back. */
function Host(props: Partial<SelectProps>): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <Select
      options={OPTIONS}
      aria-label="Account"
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange?.(next);
      }}
    />
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Select> = {
  title: "Atoms/Select",
  component: Select,
  render: (args) => <Host {...args} />,
  args: { value: "main", onChange: fn(), options: OPTIONS, "aria-label": "Account" },
};
export default meta;
type Story = StoryObj<typeof Select>;

const col = { display: "grid", gap: "var(--space-inset-md)", width: "16rem" } as const;
const trigger = (canvasElement: HTMLElement): HTMLElement =>
  within(canvasElement).getByRole("combobox");

export const Default: Story = {};

export const Placeholder: Story = {
  args: { value: undefined, placeholder: "Choose an account" },
};

export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(trigger(canvasElement)),
};

export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(trigger(canvasElement)).toHaveFocus();
  },
};

/** Open: the listbox under the trigger, the chosen option checked, the active one on the hover surface with CMP-039's inset ring. */
export const Open: Story = {
  args: { options: [...OPTIONS, T2_OPTION] },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    const box = trigger(canvasElement);
    await expect(box).toHaveAttribute("aria-expanded", "true");
    // The list fades in over the fast token: wait for it to be painted.
    await waitFor(() =>
      expect(within(canvasElement).getByRole("listbox", { name: "Account" })).toBeVisible(),
    );
    const id = box.getAttribute("aria-activedescendant");
    await expect(id).not.toBeNull();
    // The ring (2px focus ring, drawn 2px inside) marks the active option's row; its 3:1 is held in test/contrast.
    const ring = getComputedStyle(
      canvasElement.ownerDocument
        .getElementById(id as string)
        ?.closest(".cv-select__row") as Element,
    );
    await expect(ring.outlineStyle).toBe("solid");
    await expect(parseFloat(ring.outlineWidth)).toBe(2);
    // Drawn 2px inside: the outer edge sits 2px in from the row edge, so the offset is -(gap + width)
    // (#264 ruling, 27 Oct 14:55Z).
    await expect(parseFloat(ring.outlineOffset)).toBe(-2 * parseFloat(ring.outlineWidth));
  },
};

/** Arrows skip the plain-disabled option; Enter chooses and the trigger keeps focus. */
export const KeyboardChoose: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowDown}{Enter}");
    await expect(args.onChange).toHaveBeenCalledWith("sub3");
    await expect(trigger(canvasElement)).toHaveFocus();
    await expect(trigger(canvasElement)).toHaveAttribute("aria-expanded", "false");
    await expect(trigger(canvasElement)).toHaveTextContent("Sub-account 3");
  },
};

export const Invalid: Story = {
  args: { invalid: true, errorMessage: ERROR, value: undefined, placeholder: "Choose an account" },
  play: async ({ canvasElement }) => {
    await expect(trigger(canvasElement)).toHaveAttribute("aria-invalid", "true");
    await expect(trigger(canvasElement)).toHaveAccessibleDescription(ERROR);
  },
};

export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(trigger(canvasElement)).not.toHaveFocus();
  },
};

/** T2: focusable, never opens, the lock leads the value and the first refused key announces the reason. */
export const DisabledWithReason: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{ArrowDown} ");
    const box = trigger(canvasElement);
    await expect(box).toHaveFocus();
    await expect(box).toHaveAttribute("aria-expanded", "false");
    await expect(box).toHaveAccessibleDescription(REASON);
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(REASON);
  },
};

/** A long label truncates inside the well and stays the accessible value. */
export const LongValue: Story = {
  args: {
    value: "long",
    options: [{ value: "long", label: "A very long account label that does not fit" }],
  },
  decorators: [
    (Story) => (
      <div style={{ width: "10rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const text = within(canvasElement).getByText(/A very long/);
    await expect(text.scrollWidth).toBeGreaterThan(text.clientWidth);
  },
};

/** More than ten options: the list stops at ten rows and scrolls. */
export const LongList: Story = {
  args: {
    options: Array.from({ length: 14 }, (_, i) => ({
      value: `o${String(i)}`,
      label: `Option ${String(i + 1)}`,
    })),
    value: "o0",
  },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    const list = within(canvasElement).getByRole("listbox");
    await expect(list.scrollHeight).toBeGreaterThan(list.clientHeight);
  },
};

const PAIRS = [
  { value: "gtc", label: "GTC" },
  { value: "ioc", label: "IOC" },
  {
    value: "fok",
    label: "FOK",
    unavailableReason: "Market orders are always IOC on Bybit",
  },
  T2_OPTION,
  { value: "gone", label: "Retired", disabled: true },
];

/** Unavailable and T2 options: arrow-reachable, aria-disabled, described by the reason; Enter never chooses. */
export const UnavailableOption: Story = {
  args: { options: PAIRS, value: "gtc", "aria-label": "Time in force" },
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    const box = trigger(canvasElement);
    const fok = within(canvasElement).getByRole("option", { name: "FOK" });
    await expect(fok).toHaveAccessibleDescription("Market orders are always IOC on Bybit");
    await expect(box).toHaveAttribute("aria-activedescendant", fok.id);
    await userEvent.keyboard("{Enter}");
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(box).toHaveAttribute("aria-expanded", "true");
    await expect(within(canvasElement).getByRole("status")).toHaveTextContent(/always IOC/);
    // The T2 option follows; the plain-disabled one after it is skipped.
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    await expect(box).toHaveAttribute(
      "aria-activedescendant",
      within(canvasElement).getByRole("option", { name: "sub_002" }).id,
    );
  },
};

/** Type-ahead: a printable moves the active option to the next label that starts with the typed string. */
export const TypeAhead: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.tab();
    await userEvent.keyboard("sub-account 3");
    const box = trigger(canvasElement);
    await expect(box).toHaveAttribute("aria-expanded", "true");
    await expect(box).toHaveAttribute(
      "aria-activedescendant",
      within(canvasElement).getByRole("option", { name: "Sub-account 3" }).id,
    );
    await expect(args.onChange).not.toHaveBeenCalled();
  },
};

/** Fourteen options with a reason on the last: ten rows, then it scrolls; End keeps the active row in view. */
export const LongListUnavailable: Story = {
  args: {
    options: Array.from({ length: 14 }, (_, i) => ({
      value: `o${String(i)}`,
      label: `Option ${String(i + 1)}`,
      ...(i === 13 ? { unavailableReason: "Sold out" } : {}),
    })),
    value: "o0",
  },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    const list = within(canvasElement).getByRole("listbox");
    await expect(list.scrollHeight).toBeGreaterThan(list.clientHeight);
    const last = within(canvasElement).getByRole("option", { name: /^Option 14/ });
    const edge = list.getBoundingClientRect();
    await expect(last.getBoundingClientRect().bottom).toBeLessThanOrEqual(edge.bottom + 1);
  },
};

export const AllStates: Story = {
  render: (args) => (
    <div style={col}>
      <Host {...args} aria-label="Default" />
      <Host {...args} aria-label="Placeholder" value={undefined} placeholder="Choose an account" />
      <Host {...args} aria-label="Invalid" invalid errorMessage={ERROR} />
      <Host {...args} aria-label="Disabled" disabled />
      <Host {...args} aria-label="Gated" disabledReason={REASON} />
      <Host
        {...args}
        aria-label="Gated and invalid"
        invalid
        errorMessage={ERROR}
        disabledReason={REASON}
      />
      <Host {...args} aria-label="Invalid and disabled" invalid errorMessage={ERROR} disabled />
    </div>
  ),
};

/**
 * Gated, invalid and open under light and high contrast. axe checks the danger cues, the placeholder and the open
 * list per theme; it skips `aria-disabled` nodes, so the gated value's contrast is not asserted here.
 */
const themed = (theme: string): Story => ({
  globals: { theme },
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await userEvent.click(within(canvasElement).getByRole("combobox", { name: "Open" }));
  },
  render: (args) => (
    <div style={{ ...col, paddingBlockEnd: "10rem" }}>
      <Host {...args} aria-label="Open" options={PAIRS} value="gtc" />
      <Host {...args} aria-label="Gated" disabledReason={REASON} />
      <Host {...args} aria-label="Invalid" invalid errorMessage={ERROR} />
      <Host {...args} aria-label="Placeholder" value={undefined} placeholder="Choose an account" />
    </div>
  ),
});
export const GatedContrastLight: Story = themed("light");
export const GatedContrastHighContrast: Story = themed("high-contrast");
