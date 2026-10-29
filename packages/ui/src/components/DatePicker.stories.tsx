import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { DatePicker, type DatePickerProps } from "./DatePicker.js";
import { FormField } from "./FormField.js";

/** A fixed clock (2026-10-28, UTC) so today is the same in every run and in the visual matrix. */
const NOW = (): number => Date.UTC(2026, 9, 28, 12);
const CAPTION = "Recorded history: 2026-09-01 – today";
const REASON = "Your role can't control replay.";
const noop = (): void => undefined;

type HostProps = Omit<DatePickerProps, "value" | "onChange"> & {
  readonly initial?: string | null;
  readonly label?: string;
};

/** A host that owns the value inside a CMP-040 field, as every consumer does. */
function Host({ initial = "2026-10-23", label = "Go to date", ...props }: HostProps): JSX.Element {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <FormField label={label}>
      <DatePicker value={value} onChange={setValue} now={NOW} {...props} />
    </FormField>
  );
}

const meta: Meta<typeof DatePicker> = {
  title: "Molecules/DatePicker",
  component: DatePicker,
  args: { value: "2026-10-23", onChange: noop, now: NOW },
  decorators: [
    (Story) => (
      <div style={{ width: "16rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof DatePicker>;

const page = within(document.body);
const calendar = (): HTMLElement => page.getByRole("dialog");
const openWith = async (canvas: HTMLElement): Promise<HTMLElement> => {
  await userEvent.click(within(canvas).getByRole("button", { name: "Choose date" }));
  await waitFor(() => expect(calendar()).toBeVisible());
  return calendar();
};

/** Mode=single, the default field: the value, the "UTC" suffix, the hint and the calendar button. */
export const Single: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Go to date" })).toHaveValue("2026-10-23");
    await expect(canvas.getByRole("button", { name: "Choose date" })).toHaveAttribute(
      "aria-haspopup",
      "dialog",
    );
  },
};

/** Empty: the placeholder is the format hint. */
export const Empty: Story = {
  render: () => <Host initial={null} />,
};

/** Hover: the well's hover boundary (CMP-007). */
export const Hover: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) =>
    userEvent.hover(within(canvasElement).getByRole("textbox", { name: "Go to date" })),
};

/** Focus-visible: the ring around the well. */
export const Focused: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("textbox")).toHaveFocus();
  },
};

/** Open: the modal calendar named by the month, focus on the selected day; Esc returns to the button. */
export const Open: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const dialog = await openWith(canvasElement);
    await expect(dialog).toHaveAccessibleName("October 2026");
    await expect(within(dialog).getByRole("button", { name: "23 October 2026" })).toHaveFocus();
  },
};

/** Keyboard: arrows by day and week, PageDown by month (clamped), Enter picks, focus back on the button. */
export const KeyboardPick: Story = {
  render: () => <Host initial="2026-01-31" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const dialog = await openWith(canvasElement);
    await userEvent.keyboard("{PageDown}");
    await expect(within(dialog).getByRole("button", { name: "28 February 2026" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{Home}");
    await expect(within(dialog).getByRole("button", { name: "2 March 2026" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(page.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByRole("textbox")).toHaveValue("2026-03-02");
    await expect(canvas.getByRole("button", { name: "Choose date" })).toHaveFocus();
  },
};

/** WithMinMax: days outside the range are aria-disabled at opacity.disabled; the caption names the range. */
export const WithMinMax: Story = {
  render: () => <Host initial={null} min="2026-09-01" max="2026-10-28" rangeCaption={CAPTION} />,
  play: async ({ canvasElement }) => {
    const dialog = await openWith(canvasElement);
    await expect(
      within(dialog).getByRole("button", { name: "28 October 2026, today" }),
    ).toHaveFocus();
    await expect(within(dialog).getByRole("button", { name: "29 October 2026" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(within(dialog).getByText(CAPTION)).toBeVisible();
  },
};

function TimeHost(): JSX.Element {
  const [value, setValue] = useState<string | null>("2026-10-23");
  const [time, setTime] = useState<string | null>("14:05");
  return (
    <FormField label="Go to">
      <DatePicker
        value={value}
        onChange={setValue}
        withTime
        time={time}
        onTimeChange={setTime}
        now={NOW}
      />
    </FormField>
  );
}

/** Time=true: an HH:MM UTC well beside the date ("14:05"); the calendar button ends it (date, time, button). */
export const WithTime: Story = {
  render: () => <TimeHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const time = canvas.getByRole("textbox", { name: "Time" });
    await expect(time).toHaveValue("14:05");
    await userEvent.clear(time);
    await userEvent.type(time, "9:30");
    await userEvent.tab();
    await expect(time).toHaveValue("09:30");
    await expect(canvas.getByRole("button", { name: "Choose date" })).toHaveFocus();
  },
};

/** Invalid: the host's message under the well, the 2px boundary, the glyph and the words. */
export const Invalid: Story = {
  render: () => (
    <FormField label="Go to date" error="Nothing is recorded for that window.">
      <DatePicker value="2026-08-12" onChange={noop} now={NOW} />
    </FormField>
  ),
};

/** Typed text that does not parse: the picker's own message, on blur. */
export const TypedError: Story = {
  render: () => <Host initial={null} />,
  play: async ({ canvasElement }) => {
    const field = within(canvasElement).getByRole("textbox");
    await userEvent.type(field, "2026-02-30");
    await userEvent.tab();
    await expect(field).toHaveAttribute("aria-invalid", "true");
  },
};

/** Plain disabled: native, out of the Tab order; the well dims. */
export const Disabled: Story = {
  render: () => <Host disabled />,
};

/** DisabledWithReason (T2): the lock, the field read-only, the button aria-disabled; the dialog never opens. */
export const DisabledWithReason: Story = {
  render: () => <Host disabledReason={REASON} />,
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Choose date" });
    await expect(button).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(button);
    await expect(page.queryByRole("dialog")).toBeNull();
  },
};

/** Read-only: no fill, a hairline; the value stays selectable and the calendar button is disabled. */
export const ReadOnly: Story = {
  render: () => <Host readOnly />,
};

/** Every field state on one canvas, for the visual matrix (E05-T04). */
export const AllStates: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-stack-lg)" }}>
      <Host label="Default" />
      <Host label="Empty" initial={null} />
      <FormField label="Invalid" error="Nothing is recorded for that window.">
        <DatePicker value="2026-08-12" onChange={noop} now={NOW} />
      </FormField>
      <Host label="Disabled" disabled />
      <Host label="Gated" disabledReason={REASON} />
      <Host label="Read-only" readOnly />
    </div>
  ),
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: () => <Host min="2026-10-05" max="2026-10-28" rangeCaption={CAPTION} />,
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await openWith(canvasElement);
  },
});
/** The open calendar (today, selected, out of range, caption) under axe in the light theme. */
export const ContrastLight: Story = themed("light");
/** The open calendar under axe in the high-contrast theme. */
export const ContrastHighContrast: Story = themed("high-contrast");
