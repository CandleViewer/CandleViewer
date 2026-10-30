import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState, type JSX, type ReactNode } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Drawer, type DrawerProps } from "./Drawer.js";
import { FormField } from "./FormField.js";
import { Skeleton } from "./Skeleton.js";
import { TextInput } from "./TextInput.js";

const column = { display: "flex", flexDirection: "column", gap: "var(--space-stack-sm)" } as const;
const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;

type DemoProps = Omit<DrawerProps, "open" | "onOpenChange" | "title" | "children"> & {
  title?: string;
  children?: ReactNode;
};

/** The opener, the page after it, and the drawer (focus returns to the opener). */
function Demo({ title = "Instrument rules", children, ...props }: DemoProps): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div style={column}>
      <div style={row}>
        <Button onClick={() => setOpen(true)} aria-expanded={open}>
          Open
        </Button>
        <Button variant="ghost">Page control</Button>
      </div>
      <p style={{ margin: 0 }}>The workspace beside the drawer.</p>
      <Drawer
        open={open}
        title={title}
        onOpenChange={(next) => setOpen(next)}
        footer={<Button onClick={() => setOpen(false)}>Done</Button>}
        {...props}
      >
        {children ?? (
          <>
            <p style={{ margin: 0 }}>Rules that fire on BTCUSDT.</p>
            <FormField label="Rule name">
              <TextInput defaultValue="Breakout long" />
            </FormField>
          </>
        )}
      </Drawer>
    </div>
  );
}

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta = {
  title: "Molecules/Drawer",
  component: Drawer,
  render: () => <Demo />,
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const opened = async (canvas: HTMLElement): Promise<HTMLElement> => {
  const opener = within(canvas).getByRole("button", { name: "Open" });
  await userEvent.click(opener);
  await waitFor(() => expect(document.querySelector(".cv-drawer")).not.toBeNull());
  return opener;
};
const panel = (): HTMLElement => {
  const node = document.querySelector<HTMLElement>(".cv-drawer");
  if (node === null) throw new Error("no drawer in the document");
  return node;
};
const closed = async (): Promise<void> =>
  waitFor(() => expect(document.querySelector(".cv-drawer-layer")).toBeNull());

/** Modal (default, Side=right): over the scrim, focus on the heading, Tab trapped, Esc back to the opener. */
export const Modal: Story = {
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    const drawer = page.getByRole("dialog", { name: "Instrument rules" });
    await expect(drawer).toHaveAttribute("aria-modal", "true");
    await expect(within(drawer).getByRole("heading", { name: "Instrument rules" })).toHaveFocus();
    await expect(canvasElement.closest("[inert]")).not.toBeNull();
    const done = within(drawer).getByRole("button", { name: "Done" });
    done.focus();
    await userEvent.tab();
    await expect(
      within(drawer).getByRole("button", { name: "Close Instrument rules" }),
    ).toHaveFocus();
    // From the field (the close button's tooltip would take the first Esc: the topmost layer).
    within(drawer).getByRole("textbox", { name: "Rule name" }).focus();
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(opener).toHaveFocus();
    await expect(canvasElement.closest("[inert]")).toBeNull();
  },
};

/** Modal=false (H31): no scrim, the page live; Tab flows on to the page after the opener and it stays open. */
export const NonModal: Story = {
  render: () => <Demo modal={false} title="Alert detail" />,
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    const drawer = page.getByRole("dialog", { name: "Alert detail" });
    await expect(drawer).not.toHaveAttribute("aria-modal");
    await expect(document.querySelector(".cv-drawer__scrim")).toBeNull();
    await expect(canvasElement.closest("[inert]")).toBeNull();
    within(drawer).getByRole("button", { name: "Done" }).focus();
    await userEvent.tab();
    await expect(within(canvasElement).getByRole("button", { name: "Page control" })).toHaveFocus();
    await expect(drawer).toBeVisible();
    // Esc on the page stays the page's.
    await userEvent.keyboard("{Escape}");
    await expect(drawer).toBeVisible();
    // Shift+Tab from the page's next stop comes back in at the drawer's last control.
    await userEvent.tab({ shift: true });
    await expect(within(drawer).getByRole("button", { name: "Done" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(opener).toHaveFocus();
  },
};

const sideStory = (side: "left" | "right"): Story => ({
  render: () => <Demo side={side} />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await waitFor(() => expect(panel().getAnimations().length).toBe(0));
    const box = panel().getBoundingClientRect();
    if (side === "left") await expect(box.left).toBeLessThanOrEqual(0.5);
    else await expect(box.right).toBeGreaterThanOrEqual(window.innerWidth - 0.5);
  },
});
/** Side=left: the same anatomy mirrored, the inner edge on its right. */
export const LeftSide: Story = sideStory("left");
/** Side=right (default). */
export const RightSide: Story = sideStory("right");

/** State=loading: CMP-015 rows on the overlay, `aria-busy` on the body. */
export const Loading: Story = {
  render: () => (
    <Demo busy>
      <Skeleton shape="row" count={4} surface="overlay" />
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await expect(panel().querySelector(".cv-drawer__body")).toHaveAttribute("aria-busy", "true");
  },
};

/**
 * State=narrow (conventions 39): at a viewport of 720 CSS px or less the drawer takes the full width; above it
 * the host's width (480 px here) stands. The body scrolls between the header and the footer.
 */
export const Narrow: Story = {
  render: () => (
    <Demo>
      {Array.from({ length: 12 }, (_, i) => (
        <FormField key={i} label={`Condition ${String(i + 1)}`}>
          <TextInput />
        </FormField>
      ))}
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await waitFor(() => expect(panel().getAnimations().length).toBe(0));
    const box = panel().getBoundingClientRect();
    if (window.matchMedia("(max-width: 45rem)").matches)
      await expect(box.width).toBeGreaterThanOrEqual(window.innerWidth - 0.5);
    else await expect(Math.round(box.width)).toBe(480);
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight + 0.5);
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
    await expect(page.getByRole("button", { name: "Done" })).toBeVisible();
  },
};

/** A host width (SCR-077's 420 px) and name (`aria-label`, E30-D03's `drawer.name`). */
export const HostWidthAndName: Story = {
  render: () => <Demo width={420} aria-label="Order rejected - BTCUSDT - LIVE - Main" />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await waitFor(() => expect(panel().getAnimations().length).toBe(0));
    await expect(page.getByRole("dialog", { name: "Order rejected - BTCUSDT - LIVE - Main" })).toBe(
      panel(),
    );
    if (!window.matchMedia("(max-width: 45rem)").matches)
      await expect(Math.round(panel().getBoundingClientRect().width)).toBe(420);
  },
};

/** Long text and no control in the body: the body is a Tab stop, so the keyboard can scroll it. */
export const LongText: Story = {
  // 80 paragraphs: more than a 1080 px drawer holds even where none wraps (480 px wide at 1920 px).
  render: () => (
    <Demo modal={false} title="Iceberg detector">
      {Array.from({ length: 80 }, (_, i) => (
        <p key={i} style={{ margin: 0 }}>
          A level that refills after each print, paragraph {String(i + 1)} of the methodology.
        </p>
      ))}
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await waitFor(() =>
      expect(page.getByRole("group", { name: "Iceberg detector" })).toHaveAttribute(
        "tabindex",
        "0",
      ),
    );
  },
};

/** The fallback return: with the opener gone, focus goes to the host's fallback (E40-D02's bell). */
export const FallbackReturn: Story = {
  render: function Render() {
    const [open, setOpen] = useState(false);
    const [opener, setOpener] = useState(true);
    const bell = useRef<HTMLButtonElement>(null);
    return (
      <div style={row}>
        <button ref={bell} type="button">
          Alerts
        </button>
        {opener ? <Button onClick={() => setOpen(true)}>Open</Button> : null}
        <Drawer
          open={open}
          modal={false}
          title="Alert detail"
          fallbackFocusRef={bell}
          onOpenChange={setOpen}
        >
          <Button onClick={() => setOpener(false)}>Dismiss the alert</Button>
        </Drawer>
      </div>
    );
  },
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await userEvent.click(page.getByRole("button", { name: "Dismiss the alert" }));
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(within(canvasElement).getByRole("button", { name: "Alerts" })).toHaveFocus();
  },
};

const themed = (theme: string, modal: boolean): Story => ({
  globals: { theme },
  render: () => <Demo modal={modal} />,
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await opened(canvasElement);
  },
});
export const ContrastLight: Story = themed("light", true);
export const ContrastHighContrast: Story = themed("high-contrast", false);
