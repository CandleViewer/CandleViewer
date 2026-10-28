import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState, type JSX, type ReactNode } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Dialog, type DialogProps } from "./Dialog.js";
import { FormField } from "./FormField.js";
import { Popover } from "./Popover.js";
import { TextInput } from "./TextInput.js";
import { Tooltip } from "./Tooltip.js";

const column = { display: "flex", flexDirection: "column", gap: "var(--space-stack-sm)" } as const;
const row = { display: "flex", gap: "var(--space-inset-sm)", alignItems: "center" } as const;

type DemoProps = Omit<DialogProps, "open" | "onOpenChange" | "footer" | "children"> & {
  opener?: string;
  footer?: (close: () => void) => ReactNode;
  children?: ReactNode;
};

/** The opener and the page around it; the dialog opens from the button (focus returns there). */
function Demo({ opener = "Open", footer, children, ...props }: DemoProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const close = (): void => setOpen(false);
  return (
    <div style={column}>
      <div style={row}>
        <Button onClick={() => setOpen(true)}>{opener}</Button>
        <Button variant="ghost">Page control</Button>
      </div>
      <p style={{ margin: 0 }}>The workspace under the dialog.</p>
      <Dialog
        open={open}
        onOpenChange={(next) => setOpen(next)}
        footer={footer?.(close)}
        {...props}
      >
        {children}
      </Dialog>
    </div>
  );
}

const cancelSave = (primary: string) =>
  function Footer(close: () => void): JSX.Element {
    return (
      <>
        <Button onClick={close}>Cancel</Button>
        <Button variant="primary" onClick={close}>
          {primary}
        </Button>
      </>
    );
  };

/** Default: a title, a description, two CMP-040 fields, Cancel and the primary action. */
function RenameLayout(props: Partial<DemoProps>): JSX.Element {
  return (
    <Demo
      title="Rename layout"
      description="Layout names are unique within a workspace."
      footer={cancelSave("Save")}
      {...props}
    >
      <FormField label="Name">
        <TextInput defaultValue="Scalping" />
      </FormField>
      <FormField label="Note" optional>
        <TextInput />
      </FormField>
    </Demo>
  );
}

/** Theme and density come from the toolbars; the light and high-contrast stories pin the theme for axe. */
const meta: Meta = {
  title: "Molecules/Dialog",
  component: Dialog,
  render: () => <RenameLayout />,
};
export default meta;
type Story = StoryObj;

const page = within(document.body);
const opened = async (canvas: HTMLElement, name = "Open"): Promise<HTMLElement> => {
  const opener = within(canvas).getByRole("button", { name });
  await userEvent.click(opener);
  await waitFor(() => expect(document.querySelector(".cv-dialog")).not.toBeNull());
  return opener;
};
const card = (): HTMLElement => {
  const node = document.querySelector<HTMLElement>(".cv-dialog");
  if (node === null) throw new Error("no dialog in the document");
  return node;
};
const closed = async (): Promise<void> =>
  waitFor(() => expect(document.querySelector(".cv-dialog-layer")).toBeNull());

/** Gherkin "Dialog focus contract": focus in, Tab trapped, Escape closes, focus returns, the page inert. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    const dialog = page.getByRole("dialog", { name: "Rename layout" });
    await expect(dialog).toHaveAttribute("aria-modal", "true");
    await expect(dialog).toHaveAccessibleDescription("Layout names are unique within a workspace.");
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    await expect(name).toHaveFocus();
    // The page is inert (pointer, focus and the accessibility tree): it cannot even take focus.
    await expect(canvasElement.closest("[inert]")).not.toBeNull();
    within(canvasElement).getByRole("button", { name: "Page control" }).focus();
    await expect(name).toHaveFocus();
    const save = within(dialog).getByRole("button", { name: "Save" });
    save.focus();
    await userEvent.tab();
    await expect(within(dialog).getByRole("button", { name: "Close Rename layout" })).toHaveFocus();
    await userEvent.tab({ shift: true });
    await expect(save).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(opener).toHaveFocus();
    await expect(canvasElement.closest("[inert]")).toBeNull();
  },
};

/** Size=sm (420 px): E11-D03's "Go to date". */
export const Small: Story = {
  render: () => (
    <Demo size="sm" title="Go to date" footer={cancelSave("Go")}>
      <FormField label="Date (UTC)" help="YYYY-MM-DD">
        <TextInput defaultValue="2026-10-23" />
      </FormField>
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await expect(card()).toHaveAttribute("data-size", "sm");
    await expect(card().getBoundingClientRect().width).toBeLessThanOrEqual(420.5);
  },
};

/** Size=lg (960 px): E42-D03's "Invite a user". */
export const Large: Story = {
  render: () => (
    <Demo size="lg" title="Invite a user" footer={cancelSave("Send invite")}>
      <FormField label="Email">
        <TextInput type="email" defaultValue="manager@example.com" />
      </FormField>
      <FormField label="Display name">
        <TextInput defaultValue="Desk manager" />
      </FormField>
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    await expect(card()).toHaveAttribute("data-size", "lg");
    await expect(card().getBoundingClientRect().width).toBeLessThanOrEqual(960.5);
  },
};

/** Role=alertdialog: E14-D02's delete, Cancel focused, no close button; a scrim press does nothing. */
function DeleteDrawings(): JSX.Element {
  const cancel = useRef<HTMLSpanElement>(null);
  return (
    <Demo
      role="alertdialog"
      title="Delete 497 drawings on BTCUSDT?"
      initialFocusRef={cancel}
      footer={(close) => (
        <>
          <span ref={cancel}>
            <Button onClick={close}>Cancel</Button>
          </span>
          <Button variant="danger" onClick={close}>
            Delete 497
          </Button>
        </>
      )}
    >
      <p style={{ margin: 0 }}>3 locked drawings stay. One undo.</p>
    </Demo>
  );
}
export const AlertDialog: Story = {
  render: () => <DeleteDrawings />,
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    const dialog = page.getByRole("alertdialog", { name: "Delete 497 drawings on BTCUSDT?" });
    await expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await expect(within(dialog).queryByRole("button", { name: /^Close/ })).toBeNull();
    const scrim = document.querySelector(".cv-dialog__scrim");
    if (scrim === null) throw new Error("no scrim");
    await userEvent.click(scrim);
    await expect(dialog).toBeVisible();
  },
};

/** Overflow=scrolls: the card at 80 % of the viewport, the body scrolling between the header and footer. */
export const Scrolling: Story = {
  render: () => (
    <Demo title="Import 40 alerts" footer={cancelSave("Import")}>
      {Array.from({ length: 40 }, (_, i) => (
        <p key={i} style={{ margin: 0 }}>{`Alert ${String(i + 1)}: BTCUSDT crosses a level`}</p>
      ))}
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    const body = card().querySelector<HTMLElement>(".cv-dialog__body");
    await expect(body?.scrollHeight ?? 0).toBeGreaterThan(body?.clientHeight ?? 0);
    // Nothing focusable in the body: it is a Tab stop itself, named by the title, so keys can scroll it.
    await waitFor(() => expect(body).toHaveAttribute("tabindex", "0"));
    await expect(page.getByRole("group", { name: "Import 40 alerts" })).toBe(body);
    await expect(card().getBoundingClientRect().bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(page.getByRole("button", { name: "Import" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Import 40 alerts" })).toBeVisible();
  },
};

/** State=busy: the primary is CMP-001 loading and the fields readOnly; Esc closes the view (H22). */
export const Busy: Story = {
  render: () => (
    <Demo
      title="Rename layout"
      busy
      footer={(close) => (
        <>
          <Button onClick={close}>Cancel</Button>
          <Button variant="primary" loading>
            Save
          </Button>
        </>
      )}
    >
      <FormField label="Name">
        <TextInput defaultValue="Scalping" readOnly />
      </FormField>
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    await expect(page.getByRole("dialog", { name: "Rename layout" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(opener).toHaveFocus();
  },
};

/**
 * State=reflow (conventions 39): at 200 % zoom on the 1280 x 800 frame (a 640 x 400 viewport, as the
 * test runner's narrow frame) the card fills the viewport, the header and footer stay, the body scrolls.
 */
export const Reflow: Story = {
  render: () => (
    <Demo title="Rename layout" footer={cancelSave("Save and switch to the new layout")}>
      {Array.from({ length: 12 }, (_, i) => (
        <FormField key={i} label={`Field ${String(i + 1)}`}>
          <TextInput />
        </FormField>
      ))}
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    const box = card().getBoundingClientRect();
    const reflowed = window.matchMedia("(max-width: 40rem), (max-height: 25rem)").matches;
    if (reflowed) await expect(box.width).toBeGreaterThan(window.innerWidth * 0.9);
    else await expect(box.width).toBeLessThanOrEqual(560.5);
    await expect(box.right).toBeLessThanOrEqual(window.innerWidth);
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(window.innerWidth);
    await expect(
      page.getByRole("button", { name: "Save and switch to the new layout" }),
    ).toBeVisible();
  },
};

/** H23: an exempt region (the shell's StatusBar) stays live while the workspace is inert. */
export const ExemptRegion: Story = {
  render: () => (
    <>
      <RenameLayout />
      <footer data-cv-inert-exempt="" aria-label="Status bar" style={row}>
        <Button variant="ghost">Panic: flatten all</Button>
      </footer>
    </>
  ),
  play: async ({ canvasElement }) => {
    await opened(canvasElement);
    const panic = within(canvasElement).getByRole("button", { name: "Panic: flatten all" });
    await expect(panic.closest("[inert]")).toBeNull();
    await expect(
      within(canvasElement).getByText("The workspace under the dialog.").closest("[inert]"),
    ).not.toBeNull();
  },
};

/** Esc closes the topmost layer only: a tooltip, then a popover, then the dialog (conventions 32). */
export const EscTopmost: Story = {
  render: () => (
    <Demo title="Chart settings" footer={cancelSave("Apply")}>
      <Popover heading="Line style" anchor={<Button>Line style</Button>}>
        <Tooltip content="Applies to new drawings">
          <Button variant="ghost">Width 2</Button>
        </Tooltip>
      </Popover>
    </Demo>
  ),
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement);
    await userEvent.click(page.getByRole("button", { name: "Line style" }));
    const popover = page.getByRole("dialog", { name: "Line style" });
    await waitFor(() => expect(popover).toHaveAttribute("data-positioned"));
    const width = within(popover).getByRole("button", { name: "Width 2" });
    await expect(width).toHaveFocus();
    const tip = page.getByText("Applies to new drawings");
    await waitFor(() => expect(tip).toBeVisible());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(tip).not.toBeVisible());
    await expect(popover).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(popover).not.toBeVisible());
    await expect(page.getByRole("dialog", { name: "Chart settings" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(opener).toHaveFocus();
  },
};

/** H36: the host's discard prompt is a stacked alertdialog; its Esc returns to the form as it was. */
function DirtyForm(): JSX.Element {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const keep = useRef<HTMLSpanElement>(null);
  return (
    <div style={column}>
      <div style={row}>
        <Button onClick={() => setOpen(true)}>Edit alert</Button>
      </div>
      <Dialog
        open={open}
        title="Edit alert"
        onOpenChange={() => setAsking(true)}
        footer={
          <>
            <Button onClick={() => setAsking(true)}>Cancel</Button>
            <Button variant="primary" onClick={() => setOpen(false)}>
              Save
            </Button>
          </>
        }
      >
        <FormField label="Price">
          <TextInput defaultValue="64000" />
        </FormField>
        <Dialog
          open={asking}
          role="alertdialog"
          size="sm"
          title="Discard unsaved changes?"
          initialFocusRef={keep}
          onOpenChange={() => setAsking(false)}
          footer={
            <>
              <span ref={keep}>
                <Button onClick={() => setAsking(false)}>Keep editing</Button>
              </span>
              <Button
                variant="danger"
                onClick={() => {
                  setAsking(false);
                  setOpen(false);
                }}
              >
                Discard changes
              </Button>
            </>
          }
        />
      </Dialog>
    </div>
  );
}
export const StackedDiscard: Story = {
  render: () => <DirtyForm />,
  play: async ({ canvasElement }) => {
    const opener = await opened(canvasElement, "Edit alert");
    const price = page.getByRole("textbox", { name: "Price" });
    await expect(price).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    const prompt = await page.findByRole("alertdialog", { name: "Discard unsaved changes?" });
    await expect(within(prompt).getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await expect(price.closest("[inert]")).not.toBeNull();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(page.queryByRole("alertdialog")).toBeNull());
    await expect(price).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(await page.findByRole("button", { name: "Discard changes" }));
    await closed();
    await expect(opener).toHaveFocus();
  },
};

/** The scroll lock gives the scrollbar's width back: nothing under the scrim moves. */
export const NoLayoutShift: Story = {
  render: () => (
    <div>
      <RenameLayout />
      <div style={{ height: "200vh" }} aria-hidden="true" />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const marker = within(canvasElement).getByText("The workspace under the dialog.");
    const before = marker.getBoundingClientRect();
    await opened(canvasElement);
    await expect(document.documentElement.style.overflow).toBe("hidden");
    const during = marker.getBoundingClientRect();
    await expect(during.left).toBe(before.left);
    await expect(during.width).toBe(before.width);
    await userEvent.keyboard("{Escape}");
    await closed();
    await expect(document.documentElement.style.overflow).toBe("");
  },
};

const themed = (theme: string): Story => ({
  globals: { theme },
  play: async ({ canvasElement }) => {
    // The theme runtime applies the global in an effect: prove axe runs on this theme, not the dark default.
    await waitFor(() => expect(document.documentElement).toHaveAttribute("data-theme", theme));
    await opened(canvasElement);
  },
});
export const ContrastLight: Story = themed("light");
export const ContrastHighContrast: Story = themed("high-contrast");
