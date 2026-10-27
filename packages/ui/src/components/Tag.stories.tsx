import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Tag } from "./Tag.js";

const REASON = "Owner only: your role can't use this action.";
const STATUS = [
  { variant: "info", label: "Syncing" },
  { variant: "warning", label: "Degraded" },
  { variant: "danger", label: "Blocked" },
] as const;

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Tag> = {
  title: "Atoms/Tag",
  component: Tag,
  args: { label: "Breakout" },
};
export default meta;
type Story = StoryObj<typeof Tag>;

const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
const col = { display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" } as const;
const removeButton = (canvas: HTMLElement, label = "Breakout"): HTMLElement =>
  within(canvas).getByRole("button", { name: `Remove ${label}` });

export const Default: Story = {};

export const WithIcon: Story = { args: { icon: "lock" } };

/** Every built variant: neutral (plain, icon, removable) and the three status tones, glyph plus word. */
export const AllVariants: Story = {
  render: () => (
    <div style={col}>
      <div style={row}>
        <Tag label="Breakout" />
        <Tag label="Breakout" icon="lock" />
        <Tag label="Breakout" removable onRemove={fn()} />
      </div>
      <div style={row}>
        {STATUS.map((s) => (
          <Tag key={s.variant} variant={s.variant} label={s.label} />
        ))}
      </div>
    </div>
  ),
};

export const Info: Story = { args: { variant: "info", label: "Syncing" } };
export const Warning: Story = { args: { variant: "warning", label: "Degraded" } };
export const Danger: Story = { args: { variant: "danger", label: "Blocked" } };

export const Removable: Story = {
  render: () => <Tag label="Breakout" removable onRemove={fn()} />,
};

/** The remove target is the control-height square and the chip stays that tall around it (E7). */
export const RemovableGeometry: Story = {
  ...Removable,
  play: async ({ canvasElement }) => {
    const button = removeButton(canvasElement).getBoundingClientRect();
    const tag = canvasElement.querySelector(".cv-tag")?.getBoundingClientRect();
    await expect(button.width).toBeGreaterThanOrEqual(24);
    await expect(button.width).toBe(button.height);
    await expect(tag?.height).toBe(button.height);
  },
};

export const RemovableHover: Story = {
  ...Removable,
  play: async ({ canvasElement }) => userEvent.hover(removeButton(canvasElement)),
};

/** The nested CMP-002 draws the only ring, on clear fill past the 8px gap (E7, conv. 20). */
export const RemovableFocusVisible: Story = {
  ...Removable,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(removeButton(canvasElement)).toHaveFocus();
  },
};

export const RemovableDisabled: Story = {
  render: () => <Tag label="Breakout" removable onRemove={fn()} disabled />,
};

/** Gated removal (T2) through the nested CMP-002: focusable, the reason is its description, no removal. */
export const RemovableDisabledWithReason: Story = {
  args: { onRemove: fn() },
  render: (args) => (
    <Tag label="Breakout" removable onRemove={args.onRemove ?? fn()} disabledReason={REASON} />
  ),
  play: async ({ canvasElement, args }) => {
    const button = removeButton(canvasElement);
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(button).toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{Enter} ");
    await expect(args.onRemove).not.toHaveBeenCalled();
  },
};

/** A user-authored neutral tag truncates at the consumer's width; its name keeps the full text. */
export const LongText: Story = {
  render: () => (
    <div style={{ ...col, width: "10rem" }}>
      <Tag label="Opening range breakout, London session" removable onRemove={fn()} />
      <Tag variant="warning" label="Degraded" />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(
      removeButton(canvasElement, "Opening range breakout, London session"),
    ).toBeVisible();
  },
};

const NAMES = ["Breakout", "Reversal", "Scalp"];

/** The owning-group contract, as CMP-169 / CMP-055 will do it: focus moves to the next remove button. */
function RemovableGroup(): JSX.Element {
  const [tags, setTags] = useState(NAMES);
  const group = useRef<HTMLDivElement>(null);
  const remove = (index: number): void => {
    setTags((current) => current.filter((_, i) => i !== index));
    requestAnimationFrame(() => {
      const buttons = group.current?.querySelectorAll("button") ?? [];
      const next = buttons[Math.min(index, buttons.length - 1)];
      (next ?? group.current)?.focus();
    });
  };
  return (
    <div ref={group} role="group" aria-label="Active filters" tabIndex={-1} style={row}>
      {tags.map((t, i) => (
        <Tag key={t} label={t} removable onRemove={() => remove(i)} />
      ))}
    </div>
  );
}

export const KeyboardRemove: Story = {
  render: () => <RemovableGroup />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(removeButton(canvasElement)).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(removeButton(canvasElement, "Reversal")).toHaveFocus());
    await userEvent.keyboard(" ");
    await waitFor(() => expect(removeButton(canvasElement, "Scalp")).toHaveFocus());
  },
};

/** Every variant and state under the light and high-contrast themes; axe checks each theme. */
const themeMatrix = (theme: string): Story => ({
  globals: { theme },
  play: async () => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
  },
  render: () => (
    <div style={row}>
      <Tag label="Breakout" icon="lock" />
      <Tag label="Breakout" removable onRemove={fn()} />
      <Tag label="Breakout" removable onRemove={fn()} disabledReason={REASON} />
      {STATUS.map((s) => (
        <Tag key={s.variant} variant={s.variant} label={s.label} />
      ))}
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
