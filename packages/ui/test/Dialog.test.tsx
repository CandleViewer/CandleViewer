// @vitest-environment jsdom
import { act, StrictMode, useRef, useState, type JSX, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import { Button, Dialog, Popover, Tooltip, type DialogProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

afterEach(() => vi.restoreAllMocks());

const key = async (key: string, shiftKey = false): Promise<void> => {
  await act(async () => {
    fireEvent.keyDown(document.activeElement ?? document.body, { key, shiftKey });
  });
};
const click = async (element: Element): Promise<void> => {
  await act(async () => {
    fireEvent.click(element);
  });
};
const focus = async (element: HTMLElement): Promise<void> => {
  await act(async () => element.focus());
};
const screen = (): ReturnType<typeof within> => within(document.body);
const dialogNode = (name: string): HTMLElement =>
  screen().getByRole("dialog", { name }) as HTMLElement;

type Extra = Partial<Omit<DialogProps, "open" | "onOpenChange" | "title">>;

/** A host: the opener, the page around it, and a form dialog with two fields and a footer. */
function Host({
  onOpenChange,
  title = "Rename layout",
  children,
  ...props
}: Extra & { onOpenChange?: DialogProps["onOpenChange"]; title?: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div data-testid="page">
        <Button onClick={() => setOpen(true)}>Open</Button>
        <button type="button">Page control</button>
      </div>
      <Dialog
        open={open}
        title={title}
        description="Names are unique per workspace."
        onOpenChange={(next, reason) => {
          onOpenChange?.(next, reason);
          setOpen(next);
        }}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary">Save</Button>
          </>
        }
        {...props}
      >
        {children ?? (
          <>
            <label>
              Name <input type="text" defaultValue="Scalping" />
            </label>
            <label>
              Note <input type="text" />
            </label>
          </>
        )}
      </Dialog>
    </>
  );
}

const openHost = async (ui: ReactNode = <Host />): Promise<HTMLElement> => {
  const host = await mount(ui);
  const opener = within(host).getByRole("button", { name: "Open" });
  await focus(opener);
  await click(opener);
  return host;
};

describe("Dialog (CMP-043)", () => {
  it("closed: renders nothing; open: a modal dialog named by its title and described", async () => {
    const host = await mount(<Host />);
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".cv-dialog-layer")).toBeNull();
    await click(within(host).getByRole("button", { name: "Open" }));
    const node = dialogNode("Rename layout");
    expect(node).toHaveAttribute("aria-modal", "true");
    expect(node).toHaveAccessibleDescription("Names are unique per workspace.");
    expect(node).toHaveAttribute("data-cmp", "CMP-043");
    expect(node).toHaveAttribute("data-size", "md");
    expect(within(node).getByRole("heading", { level: 2, name: "Rename layout" })).toBeVisible();
    expect(within(node).getByRole("button", { name: "Close Rename layout" })).toBeVisible();
    expect(node.closest("[data-cv-layer]")?.parentElement).toBe(document.body);
  });

  it("Gherkin 'Dialog focus contract': focus in, Tab trapped, Escape closes, focus returns, page inert", async () => {
    const onOpenChange = vi.fn();
    const host = await openHost(<Host onOpenChange={onOpenChange} />);
    const node = dialogNode("Rename layout");
    const name = within(node).getByRole("textbox", { name: "Name" });
    expect(name).toHaveFocus();
    // The background is out of the accessibility tree (jsdom has no native inert: the fallback).
    expect(within(host).getByTestId("page").closest("[aria-hidden='true']")).not.toBeNull();
    expect(screen().queryByRole("button", { name: "Page control" })).toBeNull();

    const close = within(node).getByRole("button", { name: "Close Rename layout" });
    const save = within(node).getByRole("button", { name: "Save" });
    await focus(save);
    await key("Tab");
    expect(close).toHaveFocus();
    await key("Tab", true);
    expect(save).toHaveFocus();

    await focus(name);
    await key("Escape");
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "escape");
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(within(host).getByRole("button", { name: "Open" })).toHaveFocus();
    expect(host.closest("[aria-hidden]")).toBeNull();
  });

  it("native inert where the engine has it; data-cv-inert-exempt regions are spared", async () => {
    Object.defineProperty(HTMLElement.prototype, "inert", { configurable: true, value: false });
    try {
      const shell = document.body.appendChild(document.createElement("div"));
      const bar = shell.appendChild(document.createElement("header"));
      bar.setAttribute("data-cv-inert-exempt", "");
      const workspace = shell.appendChild(document.createElement("main"));
      const host = await openHost();
      expect(bar).not.toHaveAttribute("inert");
      expect(shell).not.toHaveAttribute("inert");
      expect(workspace).toHaveAttribute("inert");
      expect(host).toHaveAttribute("inert");
      expect(host).not.toHaveAttribute("aria-hidden");
      await key("Escape");
      expect(workspace).not.toHaveAttribute("inert");
      expect(host).not.toHaveAttribute("inert");
    } finally {
      delete (HTMLElement.prototype as { inert?: boolean }).inert;
    }
  });

  it("leaves a node that was already hidden as it was, and hides a subtree added while open", async () => {
    const before = document.body.appendChild(document.createElement("aside"));
    before.setAttribute("aria-hidden", "true");
    await openHost();
    const late = document.body.appendChild(document.createElement("section"));
    await act(async () => Promise.resolve());
    expect(late).toHaveAttribute("aria-hidden", "true");
    await key("Escape");
    expect(before).toHaveAttribute("aria-hidden", "true");
    expect(late).not.toHaveAttribute("aria-hidden");
  });

  it("initial focus: initialFocusRef, else the first field, else the heading (H32)", async () => {
    function WithRef(): JSX.Element {
      const save = useRef<HTMLButtonElement>(null);
      return (
        <Host
          initialFocusRef={save}
          footer={
            <button ref={save} type="button">
              Save
            </button>
          }
        />
      );
    }
    await openHost(<WithRef />);
    expect(screen().getByRole("button", { name: "Save" })).toHaveFocus();
    await key("Escape");
    await openHost(<Host>{<p>No fields here.</p>}</Host>);
    expect(screen().getByRole("heading", { name: "Rename layout" })).toHaveFocus();
  });

  it("alertdialog: no close button, a scrim press does nothing, focus on the host's choice", async () => {
    const onOpenChange = vi.fn();
    function Alert(): JSX.Element {
      // CMP-001 takes no ref: the ref is on a wrapper, and its first tab stop takes focus.
      const cancel = useRef<HTMLSpanElement>(null);
      return (
        <Host
          role="alertdialog"
          title="Delete 497 drawings?"
          initialFocusRef={cancel}
          onOpenChange={onOpenChange}
          footer={
            <>
              <span ref={cancel}>
                <Button>Cancel</Button>
              </span>
              <Button variant="danger">Delete 497</Button>
            </>
          }
        >
          <p>3 locked drawings stay.</p>
        </Host>
      );
    }
    await openHost(<Alert />);
    const node = screen().getByRole("alertdialog", { name: "Delete 497 drawings?" });
    expect(node).toHaveAttribute("aria-modal", "true");
    expect(within(node).queryByRole("button", { name: /^Close/ })).toBeNull();
    expect(within(node).getByRole("button", { name: "Cancel" })).toHaveFocus();
    const scrim = document.querySelector(".cv-dialog__scrim");
    if (scrim === null) throw new Error("no scrim");
    expect(scrim).toHaveAttribute("aria-hidden", "true");
    await act(async () => {
      fireEvent.pointerDown(scrim);
      fireEvent.click(scrim);
    });
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(node).toBeVisible();
  });

  it("an alertdialog without initialFocusRef warns and opens on its heading", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await openHost(<Host role="alertdialog" title="Version changed" />);
    expect(screen().getByRole("heading", { name: "Version changed" })).toHaveFocus();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("initialFocusRef"));
  });

  it("a scrim press is Cancel for a dialog; the close button closes with its reason", async () => {
    const onOpenChange = vi.fn();
    const host = await openHost(<Host onOpenChange={onOpenChange} />);
    const scrim = document.querySelector(".cv-dialog__scrim");
    if (scrim === null) throw new Error("no scrim");
    await act(async () => {
      fireEvent.pointerDown(scrim);
      fireEvent.click(scrim);
    });
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "scrim");
    expect(within(host).getByRole("button", { name: "Open" })).toHaveFocus();
    await click(within(host).getByRole("button", { name: "Open" }));
    await click(screen().getByRole("button", { name: "Close Rename layout" }));
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "close");
    expect(screen().queryByRole("dialog")).toBeNull();
  });

  it("aria-label overrides the title as the name; size, busy and className reach the card", async () => {
    await openHost(
      <Host aria-label="Confirm order - BTCUSDT - LIVE - Main" size="lg" busy className="extra" />,
    );
    const node = dialogNode("Confirm order - BTCUSDT - LIVE - Main");
    expect(node).not.toHaveAttribute("aria-labelledby");
    expect(node).toHaveAttribute("data-size", "lg");
    expect(node).toHaveAttribute("aria-busy", "true");
    expect(node).toHaveClass("cv-dialog", "extra");
  });

  it("busy: Esc still closes the view (H22)", async () => {
    const onOpenChange = vi.fn();
    await openHost(<Host busy onOpenChange={onOpenChange} />);
    await key("Escape");
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "escape");
  });

  it("a host may keep it open (a lock ignores Esc)", async () => {
    await mount(<Dialog open title="Session locked" onOpenChange={() => undefined} />);
    await key("Escape");
    expect(dialogNode("Session locked")).toBeVisible();
  });

  it("focus that escapes without a Tab is taken back to the last focused element inside", async () => {
    const host = await openHost();
    const note = screen().getByRole("textbox", { name: "Note" });
    await focus(note);
    const outside = within(host).getByRole("button", { name: "Page control", hidden: true });
    await focus(outside);
    expect(note).toHaveFocus();
  });

  it("returns focus to the host's fallback when the opener is gone, never to body", async () => {
    function Gone(): JSX.Element {
      const [open, setOpen] = useState(false);
      const [opener, setOpener] = useState(true);
      const bell = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={bell} type="button">
            Alerts
          </button>
          {opener ? (
            <button type="button" onClick={() => setOpen(true)}>
              Open
            </button>
          ) : null}
          <Dialog
            open={open}
            title="Alert detail"
            fallbackFocusRef={bell}
            onOpenChange={setOpen}
            footer={<Button onClick={() => setOpener(false)}>Remove opener</Button>}
          />
        </>
      );
    }
    await openHost(<Gone />);
    await click(screen().getByRole("button", { name: "Remove opener" }));
    await key("Escape");
    expect(screen().getByRole("button", { name: "Alerts" })).toHaveFocus();
  });

  it("locks page scroll with the scrollbar's width given back as padding, and restores it", async () => {
    vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(
      window.innerWidth - 15,
    );
    const root = document.documentElement;
    root.style.paddingRight = "";
    await openHost();
    expect(root.style.overflow).toBe("hidden");
    expect(root.style.paddingRight).toBe("15px");
    expect(root.style.getPropertyValue("--cv-scroll-lock-gutter")).toBe("15px");
    await key("Escape");
    expect(root.style.overflow).toBe("");
    expect(root.style.paddingRight).toBe("");
    expect(root.style.getPropertyValue("--cv-scroll-lock-gutter")).toBe("");
  });

  it("unmounting while open restores the page and removes its layer and listeners", async () => {
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const container = document.body.appendChild(document.createElement("div"));
    const page = document.body.appendChild(document.createElement("main"));
    const root = createRoot(container);
    await act(async () =>
      root.render(<Dialog open title="Go to date" onOpenChange={() => undefined} />),
    );
    expect(page).toHaveAttribute("aria-hidden", "true");
    expect(document.documentElement.style.overflow).toBe("hidden");
    await act(async () => root.unmount());
    expect(page).not.toHaveAttribute("aria-hidden");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.querySelector(".cv-dialog-layer")).toBeNull();
    const added = docAdd.mock.calls.filter(([type]) => type === "keydown" || type === "focusin");
    for (const [type, listener] of added)
      expect(docRemove.mock.calls.some(([t, l]) => t === type && l === listener)).toBe(true);
  });

  it("StrictMode: focus in, Esc closes, focus back to the opener, the page restored", async () => {
    const host = await openHost(
      <StrictMode>
        <Host />
      </StrictMode>,
    );
    expect(screen().getByRole("textbox", { name: "Name" })).toHaveFocus();
    await key("Escape");
    expect(within(host).getByRole("button", { name: "Open" })).toHaveFocus();
    expect(host.closest("[aria-hidden]")).toBeNull();
  });
});

describe("the overlay layer stack", () => {
  it("Esc closes the topmost layer only: Tooltip, then Popover, then Dialog", async () => {
    const onOpenChange = vi.fn();
    const host = await openHost(
      <Host onOpenChange={onOpenChange}>
        <Popover heading="Line style" anchor={<Button>Line style</Button>}>
          <Tooltip content="Applies to new drawings">
            <button type="button">Width</button>
          </Tooltip>
        </Popover>
      </Host>,
    );
    await click(screen().getByRole("button", { name: "Line style" }));
    const panel = screen().getByRole("dialog", { name: "Line style" });
    // The popover portals into the dialog's layer, so the inert page does not take it.
    expect(panel.closest("[data-cv-layer]")).not.toBeNull();
    expect(panel.closest("[aria-hidden='true']")).toBeNull();
    const width = within(panel).getByRole("button", { name: "Width" });
    await act(async () => {
      fireEvent.focus(width);
      width.focus();
    });
    expect(width).toHaveFocus();
    const tip = screen().getByText("Applies to new drawings");
    expect(tip.closest("[data-cv-layer]")).not.toBeNull();
    expect(tip.hidden).toBe(false);

    await key("Escape");
    expect(tip.hidden).toBe(true);
    expect(panel.hidden).toBe(false);
    await key("Escape");
    expect(panel.hidden).toBe(true);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen().getByRole("button", { name: "Line style" })).toHaveFocus();
    await key("Escape");
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "escape");
    expect(within(host).getByRole("button", { name: "Open" })).toHaveFocus();
  });

  it("a stacked alertdialog (H36's discard prompt): Esc returns to the form; Discard closes both", async () => {
    function Dirty(): JSX.Element {
      const [open, setOpen] = useState(false);
      const [asking, setAsking] = useState(false);
      const keep = useRef<HTMLSpanElement>(null);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <Dialog open={open} title="Edit alert" onOpenChange={() => setAsking(true)}>
            <label>
              Price <input type="text" defaultValue="64000" />
            </label>
            <Dialog
              open={asking}
              role="alertdialog"
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
        </>
      );
    }
    const host = await openHost(<Dirty />);
    const price = screen().getByRole("textbox", { name: "Price" });
    expect(price).toHaveFocus();
    await key("Escape");
    const prompt = screen().getByRole("alertdialog", { name: "Discard unsaved changes?" });
    expect(within(prompt).getByRole("button", { name: "Keep editing" })).toHaveFocus();
    // The form dialog under the prompt is out of the tree now.
    expect(screen().queryByRole("dialog", { name: "Edit alert" })).toBeNull();
    await key("Escape");
    expect(screen().queryByRole("alertdialog")).toBeNull();
    expect(dialogNode("Edit alert")).toBeVisible();
    expect(price).toHaveFocus();

    await key("Escape");
    await click(screen().getByRole("button", { name: "Discard changes" }));
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(within(host).getByRole("button", { name: "Open" })).toHaveFocus();
  });

  it("a press in a popover opened from another popover keeps the outer one open (nested layers)", async () => {
    await mount(
      <Popover heading="Outer" anchor={<Button>Outer</Button>}>
        <Popover heading="Inner" anchor={<Button>More</Button>}>
          <button type="button">Inner action</button>
        </Popover>
      </Popover>,
    );
    await click(screen().getByRole("button", { name: "Outer" }));
    await click(screen().getByRole("button", { name: "More" }));
    const inner = screen().getByRole("dialog", { name: "Inner" });
    const action = within(inner).getByRole("button", { name: "Inner action" });
    await act(async () => {
      fireEvent.pointerDown(action);
      fireEvent.pointerUp(action);
    });
    expect(screen().getByRole("dialog", { name: "Outer" })).toBeVisible();
    expect(inner).toBeVisible();
  });
});
