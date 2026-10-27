import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Popover, type PopoverBaseProps } from "./Popover.js";
import { TextInput } from "./TextInput.js";

const column = { display: "flex", flexDirection: "column", gap: "var(--space-stack-sm)" } as const;
const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;
/** Room below and above the trigger, so the preferred placement is the one drawn. */
const stage = {
  display: "grid",
  placeItems: "center",
  minHeight: "28rem",
  gap: "var(--space-stack-sm)",
} as const;

type Extra = Pick<PopoverBaseProps, "placement" | "modal">;

/** SCR-037's property popover, "a standard form": a field, two swatches, Save as default · Delete. */
function PropertyPopover(props: Extra): JSX.Element {
  return (
    <div style={stage}>
      <div style={row}>
        <Popover
          heading="Line style"
          anchor={<Button>Line style</Button>}
          footer={
            <>
              <Button variant="danger">Delete</Button>
              <Button variant="primary">Save as default</Button>
            </>
          }
          {...props}
        >
          <div style={column}>
            <label htmlFor="popover-width">Width</label>
            <TextInput id="popover-width" defaultValue="2" />
          </div>
          <div style={row} role="group" aria-label="Colour">
            <Button variant="ghost" aria-pressed="true">
              Amber
            </Button>
            <Button variant="ghost" aria-pressed="false">
              Blue
            </Button>
          </div>
        </Popover>
        <Button variant="ghost">Next tool</Button>
      </div>
    </div>
  );
}

/** CMP-047's calendar dialog (slice 3), reduced to a week: its heading, the trapped grid. */
function CalendarPopover(): JSX.Element {
  const days = ["Mon 4", "Tue 5", "Wed 6", "Thu 7", "Fri 8"];
  return (
    <div style={stage}>
      <Popover
        modal
        heading="Pick a date"
        anchor={<Button>Choose date</Button>}
        footer={<Button variant="ghost">Today</Button>}
      >
        <div style={row} role="group" aria-label="Week of 4 March">
          {days.map((day) => (
            <Button key={day} variant="ghost">
              {day}
            </Button>
          ))}
        </div>
      </Popover>
    </div>
  );
}

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta = {
  title: "Atoms/Popover",
  component: Popover,
  render: () => <PropertyPopover />,
};
export default meta;
type Story = StoryObj;

/** The popover lives in a portal on `document.body`, outside the story canvas. */
const popover = (): HTMLElement => {
  const node = document.body.querySelector<HTMLElement>(".cv-popover");
  if (node === null) throw new Error("no popover in the document");
  return node;
};
const dialog = (): HTMLElement => within(document.body).getByRole("dialog");
const isOpen = async (): Promise<void> =>
  waitFor(() => {
    expect(popover().hidden).toBe(false);
    expect(popover()).toHaveAttribute("data-positioned");
  });
const isClosed = async (): Promise<void> => waitFor(() => expect(popover().hidden).toBe(true));
const openIt = async (canvas: HTMLElement, name = "Line style"): Promise<HTMLElement> => {
  const trigger = within(canvas).getByRole("button", { name });
  await userEvent.click(trigger);
  await isOpen();
  return trigger;
};

/** Modal=false · below · fits: focus moves to its first control (the Width field), the ring on it. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement);
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
    await expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    await expect(dialog()).toHaveAccessibleName("Line style");
    await expect(dialog()).not.toHaveAttribute("aria-modal");
    await expect(within(dialog()).getByRole("textbox", { name: "Width" })).toHaveFocus();
    await expect(popover()).toHaveAttribute("data-side", "bottom");
    const box = popover().getBoundingClientRect();
    await expect(box.top).toBeGreaterThanOrEqual(trigger.getBoundingClientRect().bottom);
    await expect(box.width).toBeGreaterThanOrEqual(trigger.getBoundingClientRect().width);
  },
};

/** H11: Tab past the last control closes it and moves on from the trigger; Shift+Tab before the first returns. */
export const NonModal: Story = {
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement);
    const save = within(dialog()).getByRole("button", { name: "Save as default" });
    save.focus();
    await userEvent.tab();
    await isClosed();
    await expect(within(canvasElement).getByRole("button", { name: "Next tool" })).toHaveFocus();
    await userEvent.click(trigger);
    await isOpen();
    await userEvent.tab({ shift: true });
    await isClosed();
    await expect(trigger).toHaveFocus();
  },
};

/** Modal=true: `aria-modal`, Tab cycles inside both ways (APG Dialog (Modal)); Esc returns to the trigger. */
export const Modal: Story = {
  render: () => <CalendarPopover />,
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement, "Choose date");
    await expect(dialog()).toHaveAttribute("aria-modal", "true");
    await expect(dialog()).toHaveAccessibleName("Pick a date");
    const first = within(dialog()).getByRole("button", { name: "Mon 4" });
    const last = within(dialog()).getByRole("button", { name: "Today" });
    await expect(first).toHaveFocus();
    last.focus();
    await userEvent.tab();
    await expect(first).toHaveFocus();
    await userEvent.tab({ shift: true });
    await expect(last).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await isClosed();
    await expect(trigger).toHaveFocus();
  },
};

/** Esc closes the topmost layer and focus returns to the trigger (Gherkin "Popover focus management"). */
export const EscDismiss: Story = {
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement);
    await userEvent.keyboard("{Escape}");
    await isClosed();
    await expect(trigger).toHaveFocus();
    await expect(trigger).toHaveAttribute("aria-expanded", "false");
    // After the exit fade the content clears; the empty hidden shell keeps aria-controls valid.
    await waitFor(() => expect(popover()).toBeEmptyDOMElement());
    await expect(document.getElementById(trigger.getAttribute("aria-controls") ?? "")).toBe(
      popover(),
    );
  },
};

/** A press that starts and ends outside closes it; on no control, focus returns to the trigger. */
export const OutsideClick: Story = {
  render: () => (
    <>
      <p>Chart area</p>
      <PropertyPopover />
    </>
  ),
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement);
    await userEvent.click(within(canvasElement).getByText("Chart area"));
    await isClosed();
    await expect(trigger).toHaveFocus();
  },
};

/** Placement=above, with room above. */
export const Above: Story = {
  render: () => <PropertyPopover placement="above" />,
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement);
    await expect(popover()).toHaveAttribute("data-side", "top");
    await expect(popover().getBoundingClientRect().bottom).toBeLessThanOrEqual(
      trigger.getBoundingClientRect().top,
    );
  },
};

/** No room below: a below popover on a trigger at the viewport's bottom edge flips above, never clipped. */
export const Flipped: Story = {
  render: () => (
    <div style={{ position: "fixed", insetBlockEnd: 0, insetInlineStart: "40%" }}>
      <Popover heading="Line style" anchor={<Button>Line style</Button>}>
        <TextInput aria-label="Width" defaultValue="2" />
      </Popover>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const trigger = await openIt(canvasElement);
    await expect(popover()).toHaveAttribute("data-side", "top");
    const box = popover().getBoundingClientRect();
    await expect(box.bottom).toBeLessThanOrEqual(trigger.getBoundingClientRect().top);
    await expect(box.top).toBeGreaterThanOrEqual(0);
  },
};

/** Overflow=scrolls: capped at the room to the viewport edge; the body scrolls under the heading and footer. */
export const Scrolling: Story = {
  render: () => (
    <div style={{ position: "fixed", insetBlockStart: 0, insetInlineStart: "40%" }}>
      <Popover
        heading="Indicators"
        anchor={<Button>Indicators</Button>}
        footer={<Button variant="primary">Apply</Button>}
      >
        {Array.from({ length: 40 }, (_, i) => (
          <Button key={i} variant="ghost">
            {`EMA ${String(5 * (i + 1))}`}
          </Button>
        ))}
      </Popover>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await openIt(canvasElement, "Indicators");
    const box = popover().getBoundingClientRect();
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
    const body = popover().querySelector<HTMLElement>(".cv-popover__body");
    await expect(body?.scrollHeight ?? 0).toBeGreaterThan(body?.clientHeight ?? 0);
    await expect(within(dialog()).getByRole("button", { name: "Apply" })).toBeVisible();
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await openIt(canvasElement);
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
