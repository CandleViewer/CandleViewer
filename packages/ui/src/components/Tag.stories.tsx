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

/** Every built variant: neutral (plain, icon, removable), the three status tones (glyph plus word) and the toggle. */
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
      <div style={row}>
        <Tag variant="toggle" label="Trade" pressed onPressedChange={fn()} />
        <Tag variant="toggle" label="Funding" pressed={false} onPressedChange={fn()} />
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

/** The Fills tab's Type chips (E29-D02:299), all on by default; the host holds their state. */
const TYPES = ["Trade", "ADL", "Liquidation", "Funding", "Settlement"];

function TypeChipSet({ words = TYPES }: { words?: readonly string[] }): JSX.Element {
  const [off, setOff] = useState<ReadonlySet<string>>(new Set());
  const flip = (word: string, pressed: boolean): void =>
    setOff((now) => {
      const next = new Set(now);
      if (pressed) next.delete(word);
      else next.add(word);
      return next;
    });
  return (
    <div style={{ ...row, flexWrap: "wrap" }}>
      {words.map((word) => (
        <Tag
          key={word}
          variant="toggle"
          label={word}
          pressed={!off.has(word)}
          onPressedChange={(pressed) => flip(word, pressed)}
        />
      ))}
    </div>
  );
}

const toggleOf = (canvas: HTMLElement, word: string): HTMLElement =>
  within(canvas).getByRole("button", { name: word });

/**
 * The pressed ring as the browser paints it, present by its width alone: `border.thick` of color.border.selected
 * when pressed, 0 at rest (forced colours repaint a border's colour, never its width).
 */
const ringOf = (chip: HTMLElement): { width: string; coloured: boolean } => {
  const after = getComputedStyle(chip, "::after");
  const thick = getComputedStyle(chip).getPropertyValue("--border-thick").trim();
  const width = after.borderTopWidth;
  return {
    width: width === `${thick}px` ? "thick" : Number.parseFloat(width) === 0 ? "none" : width,
    coloured: after.borderTopColor !== "rgba(0, 0, 0, 0)",
  };
};

/** A pressed toggle chip: `aria-pressed="true"`, the action.selected fill and the 2px ring that marks it. */
export const Toggle: Story = {
  render: () => <Tag variant="toggle" label="Trade" pressed onPressedChange={fn()} />,
  play: async ({ canvasElement }) => {
    const chip = toggleOf(canvasElement, "Trade");
    await expect(chip).toHaveAttribute("aria-pressed", "true");
    await expect(ringOf(chip)).toEqual({ width: "thick", coloured: true });
  },
};

/** A toggle chip at rest: the neutral chip's look, `aria-pressed="false"`, no ring (its width is 0). */
export const ToggleOff: Story = {
  render: () => <Tag variant="toggle" label="Funding" pressed={false} onPressedChange={fn()} />,
  play: async ({ canvasElement }) => {
    const chip = toggleOf(canvasElement, "Funding");
    await expect(chip).toHaveAttribute("aria-pressed", "false");
    await expect(ringOf(chip).width).toBe("none");
  },
};

export const ToggleHover: Story = {
  ...ToggleOff,
  play: async ({ canvasElement }) => userEvent.hover(toggleOf(canvasElement, "Funding")),
};

/** CMP-039's ring outside the chip, clear of the pressed ring inside it. */
export const ToggleFocusVisible: Story = {
  ...Toggle,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(toggleOf(canvasElement, "Trade")).toHaveFocus();
  },
};

/** The five Type chips: Space and Enter flip one, its name unchanged; each chip is its own Tab stop. */
export const TypeChips: Story = {
  render: () => <TypeChipSet />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await userEvent.tab();
    const adl = toggleOf(canvasElement, "ADL");
    await expect(adl).toHaveFocus();
    await userEvent.keyboard(" ");
    await waitFor(() => expect(adl).toHaveAttribute("aria-pressed", "false"));
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(adl).toHaveAttribute("aria-pressed", "true"));
  },
};

/** A narrow toolbar: the chips wrap to a second row and no word is ever cut. */
export const ToggleLongText: Story = {
  render: () => (
    <div style={{ width: "10rem" }}>
      <TypeChipSet />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const chips = TYPES.map((word) => toggleOf(canvasElement, word));
    // Nothing overflows a chip: each shows its whole word, neither squeezed nor clipped.
    for (const chip of chips) await expect(chip.scrollWidth).toBeLessThanOrEqual(chip.clientWidth);
    // The row wraps instead.
    const rows = new Set(chips.map((chip) => chip.getBoundingClientRect().top));
    await expect(rows.size).toBeGreaterThan(1);
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
      <Tag variant="toggle" label="Trade" pressed onPressedChange={fn()} />
      <Tag variant="toggle" label="Funding" pressed={false} onPressedChange={fn()} />
    </div>
  ),
});
export const ContrastLight: Story = themeMatrix("light");
export const ContrastHighContrast: Story = themeMatrix("high-contrast");
