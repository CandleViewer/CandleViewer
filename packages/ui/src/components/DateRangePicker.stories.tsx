import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import {
  DateRangePicker,
  type DateRangePickerProps,
  type DateRangeValue,
} from "./DateRangePicker.js";
import { FormField } from "./FormField.js";

/** A fixed clock (2026-10-28, UTC) so today is the same in every run and in the visual matrix. */
const NOW = (): number => Date.UTC(2026, 9, 28, 12);
const CAPTION = "Recorded history: 2026-09-01 – today";
const REASON = "Your role can't control replay.";
const WEEK: DateRangeValue = { start: "2026-10-01", end: "2026-10-07" };
const noop = (): void => undefined;

type HostProps = Omit<DateRangePickerProps, "value" | "onChange"> & {
  readonly initial?: DateRangeValue;
  readonly label?: string;
  readonly error?: string;
};

/** A host that owns the range inside a CMP-040 field, as SCR-098's replay range does. */
function Host({ initial = WEEK, label = "Replay range", error, ...props }: HostProps): JSX.Element {
  const [value, setValue] = useState<DateRangeValue>(initial);
  return (
    <FormField label={label} {...(error === undefined ? {} : { error })}>
      <DateRangePicker value={value} onChange={setValue} now={NOW} {...props} />
    </FormField>
  );
}

const meta: Meta<typeof DateRangePicker> = {
  title: "Molecules/DateRangePicker",
  component: DateRangePicker,
  args: { value: WEEK, onChange: noop, now: NOW },
  decorators: [
    (Story) => (
      <div style={{ width: "28rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof DateRangePicker>;

const page = within(document.body);
const calendar = (): HTMLElement => page.getByRole("dialog");
const openWith = async (canvas: HTMLElement): Promise<HTMLElement> => {
  await userEvent.click(within(canvas).getByRole("button", { name: "Choose dates" }));
  await waitFor(() => expect(calendar()).toBeVisible());
  return calendar();
};

/** Mode=range: Start and End fields, one calendar button on the End field. */
export const Range: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("group", { name: "Replay range" })).toBeVisible();
    await expect(canvas.getByRole("textbox", { name: "Start" })).toHaveValue("2026-10-01");
    await expect(canvas.getByRole("textbox", { name: "End" })).toHaveValue("2026-10-07");
  },
};

/** Empty: both placeholders are the format hint. */
export const Empty: Story = {
  render: () => <Host initial={{ start: null, end: null }} />,
};

/** Open: every day of the range selected, the ends marked, the band between. */
export const Open: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const dialog = await openWith(canvasElement);
    await expect(dialog).toHaveAccessibleName("October 2026");
    await expect(within(dialog).getByRole("button", { name: "1 October 2026" })).toHaveFocus();
  },
};

/** Mode=range, open: the start picked, the end pending, the band to the focused day; then the end closes it. */
export const RangeOpen: Story = {
  render: () => <Host initial={{ start: null, end: null }} />,
  play: async ({ canvasElement }) => {
    const dialog = await openWith(canvasElement);
    await userEvent.keyboard("{PageUp}{Home}");
    await userEvent.keyboard("{Enter}");
    await expect(within(dialog).getByText("Start 2026-09-28. Choose the end date.")).toBeDefined();
    await userEvent.keyboard("{ArrowDown}{ArrowRight}{ArrowRight}");
    await expect(dialog.querySelectorAll("[data-in-range]").length).toBeGreaterThan(0);
  },
};

/** A keyboard range: the start, the end, then the fields and the polite range sentence. */
export const KeyboardRange: Story = {
  render: () => <Host initial={{ start: null, end: null }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openWith(canvasElement);
    await userEvent.keyboard("{Home}{Enter}{End}{Enter}");
    await waitFor(() => expect(page.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByRole("textbox", { name: "Start" })).toHaveValue("2026-10-26");
    await expect(canvas.getByRole("textbox", { name: "End" })).toHaveValue("2026-11-01");
    await waitFor(() =>
      expect(canvasElement.querySelector(".cv-daterange > [role='status']")).toHaveTextContent(
        "2026-10-26 to 2026-11-01, 7 days.",
      ),
    );
  },
};

/** WithMinMax: days outside the range are aria-disabled; the caption names the range. */
export const WithMinMax: Story = {
  render: () => (
    <Host
      initial={{ start: null, end: null }}
      min="2026-09-01"
      max="2026-10-28"
      rangeCaption={CAPTION}
    />
  ),
  play: async ({ canvasElement }) => {
    const dialog = await openWith(canvasElement);
    await expect(within(dialog).getByRole("button", { name: "29 October 2026" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(within(dialog).getByText(CAPTION)).toBeVisible();
  },
};

/** Time=true: an HH:MM UTC well after each date; the calendar button ends the End time well. */
export const WithTime: Story = {
  render: () => <Host withTime initial={{ ...WEEK, startTime: "14:05", endTime: "18:30" }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Start time" })).toHaveValue("14:05");
    await expect(canvas.getByRole("textbox", { name: "End time" })).toHaveValue("18:30");
  },
};

/** Narrow: the host is narrower than both fields, so End stacks under Start. */
export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div style={{ width: "12rem" }}>
        <Story />
      </div>
    ),
  ],
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const start = canvas.getByRole("textbox", { name: "Start" }).getBoundingClientRect();
    const end = canvas.getByRole("textbox", { name: "End" }).getBoundingClientRect();
    await expect(end.top).toBeGreaterThan(start.bottom);
  },
};

/** Invalid: the host's message (its own check) under the group. */
export const Invalid: Story = {
  render: () => <Host error="Nothing is recorded for that window." />,
};

/** Typed text that does not parse: the picker's own message, on blur; only that well is invalid. */
export const TypedError: Story = {
  render: () => <Host initial={{ start: null, end: null }} />,
  play: async ({ canvasElement }) => {
    const end = within(canvasElement).getByRole("textbox", { name: "End" });
    await userEvent.type(end, "2026-02-30");
    await userEvent.tab();
    await expect(end).toHaveAttribute("aria-invalid", "true");
  },
};

/** Plain disabled: native, out of the Tab order; the wells and labels dim. */
export const Disabled: Story = {
  render: () => <Host disabled />,
};

/** DisabledWithReason (T2): a lock in each well, the fields read-only, the button aria-disabled. */
export const DisabledWithReason: Story = {
  render: () => <Host disabledReason={REASON} />,
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Choose dates" });
    await expect(button).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(button);
    await expect(page.queryByRole("dialog")).toBeNull();
  },
};

/** Read-only: the values stay selectable and the calendar button is disabled. */
export const ReadOnly: Story = {
  render: () => <Host readOnly />,
};

/** Every range state on one canvas, for the visual matrix (E05-T04). */
export const AllStates: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-stack-lg)" }}>
      <Host label="Default" />
      <Host label="Empty" initial={{ start: null, end: null }} />
      <Host label="With time" withTime initial={{ ...WEEK, startTime: "14:05", endTime: null }} />
      <Host label="Invalid" error="Nothing is recorded for that window." />
      <Host label="Disabled" disabled />
      <Host label="Gated" disabledReason={REASON} />
      <Host label="Read-only" readOnly />
    </div>
  ),
};

const themed = (theme: string): Story => ({
  globals: { theme },
  render: () => <Host min="2026-09-05" max="2026-10-28" rangeCaption={CAPTION} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await openWith(canvasElement);
  },
});
/** The open range (ends, band, today, out of range) under axe in the light theme. */
export const ContrastLight: Story = themed("light");
/** The open range under axe in the high-contrast theme. */
export const ContrastHighContrast: Story = themed("high-contrast");
