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

  it("a scrim click with no press that began on it does nothing", async () => {
    const onOpenChange = vi.fn();
    await openHost(<Host onOpenChange={onOpenChange} />);
    const scrim = document.querySelector(".cv-dialog__scrim");
    if (scrim === null) throw new Error("no scrim");
    await click(scrim);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(dialogNode("Rename layout")).toBeVisible();
  });

  it("a scrim press that began while a layer was stacked above it does not close it", async () => {
    const onOpenChange = vi.fn();
    function Stacked(): JSX.Element {
      const [open, setOpen] = useState(false);
      const [picking, setPicking] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <Dialog
            open={open}
            title="Edit alert"
            onOpenChange={(next, reason) => {
              onOpenChange(next, reason);
              setOpen(next);
            }}
          >
            <button type="button" onClick={() => setPicking(true)}>
              Pick colour
            </button>
            <Dialog open={picking} title="Colour" onOpenChange={() => setPicking(false)} />
          </Dialog>
        </>
      );
    }
    await openHost(<Stacked />);
    await click(screen().getByRole("button", { name: "Pick colour" }));
    const [outer] = document.querySelectorAll(".cv-dialog__scrim");
    if (outer === undefined) throw new Error("no scrim");
    await act(async () => {
      fireEvent.pointerDown(outer);
    });
    await key("Escape");
    expect(screen().queryByRole("dialog", { name: "Colour" })).toBeNull();
    await click(outer);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(dialogNode("Edit alert")).toBeVisible();
    await act(async () => {
      fireEvent.pointerDown(outer);
      fireEvent.click(outer);
    });
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "scrim");
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

describe("Dialog exit fade", () => {
  const layerNode = (): Element | null => document.querySelector(".cv-dialog-layer");
  const scrimNode = (): Element => {
    const scrim = document.querySelector(".cv-dialog__scrim");
    if (scrim === null) throw new Error("no scrim");
    return scrim;
  };
  /** The scrim fades over 200 ms (the longest of its transitions); nothing else transitions. */
  const stubFade = (): void => {
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) =>
      element.classList.contains("cv-dialog__scrim")
        ? ({ transitionDuration: "0.1s, 200ms" } as unknown as CSSStyleDeclaration)
        : real(element, pseudo),
    );
  };
  const advance = async (ms: number): Promise<void> => {
    await act(async () => {
      vi.advanceTimersByTime(ms);
    });
  };

  afterEach(() => {
    vi.useRealTimers();
    document.documentElement.removeAttribute("data-motion");
  });

  it("keeps the layer inert through the fade, then removes it at the fallback timer", async () => {
    stubFade();
    await openHost();
    vi.useFakeTimers();
    await key("Escape");
    const layer = layerNode();
    expect(layer).toHaveAttribute("data-state", "closing");
    expect(layer).toHaveAttribute("inert");
    await advance(299);
    expect(layerNode()).not.toBeNull();
    await advance(1);
    expect(layerNode()).toBeNull();
  });

  it("ends on the scrim's own transitionend or transitioncancel, not a descendant's", async () => {
    stubFade();
    await openHost();
    vi.useFakeTimers();
    await key("Escape");
    // A transition bubbling up from inside the scrim is not the scrim's own fade.
    const inner = scrimNode().appendChild(document.createElement("span"));
    await act(async () => {
      fireEvent.transitionEnd(inner);
    });
    expect(layerNode()).not.toBeNull();
    await act(async () => {
      fireEvent.transitionEnd(scrimNode());
    });
    expect(layerNode()).toBeNull();

    await click(screen().getByRole("button", { name: "Open" }));
    await key("Escape");
    expect(layerNode()).not.toBeNull();
    await act(async () => {
      fireEvent(scrimNode(), new Event("transitioncancel"));
    });
    expect(layerNode()).toBeNull();
  });

  it("reduced motion is a cut: the layer goes at once", async () => {
    stubFade();
    document.documentElement.setAttribute("data-motion", "reduce");
    await openHost();
    await key("Escape");
    expect(layerNode()).toBeNull();
  });

  it("reopened mid-exit: the fade's timer and listeners are cleared and the dialog stays", async () => {
    stubFade();
    const host = await openHost();
    vi.useFakeTimers();
    await key("Escape");
    const scrim = scrimNode();
    await click(within(host).getByRole("button", { name: "Open" }));
    const layer = layerNode();
    expect(layer).toHaveAttribute("data-state", "open");
    expect(layer).not.toHaveAttribute("inert");
    await advance(1000);
    await act(async () => {
      fireEvent.transitionEnd(scrim);
    });
    expect(dialogNode("Rename layout")).toBeVisible();
    expect(screen().getByRole("textbox", { name: "Name" })).toHaveFocus(); // A stale timer or listener would have cleared the exit: the next close would be a cut.
    await key("Escape");
    expect(layerNode()).toHaveAttribute("data-state", "closing");
    await advance(300);
    expect(layerNode()).toBeNull();
  });
});

describe("Dialog readable body", () => {
  let overflowing = false;
  const observed: Element[] = [];
  let resized: (() => void) | undefined;

  const stubLayout = (): void => {
    overflowing = false;
    observed.length = 0;
    resized = undefined;
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains("cv-dialog__body") && overflowing ? 900 : 100;
    });
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe(target: Element): void {
          observed.push(target);
        }
        disconnect(): void {
          resized = undefined;
        }
      },
    );
  };
  const bodyNode = (): HTMLElement => {
    const node = document.querySelector<HTMLElement>(".cv-dialog__body");
    if (node === null) throw new Error("no body");
    return node;
  };

  afterEach(() => vi.unstubAllGlobals());

  it("a body that scrolls with no control in it is a Tab stop named by the title", async () => {
    stubLayout();
    overflowing = true;
    await openHost(<Host>{<p>Long terms of use.</p>}</Host>);
    const group = screen().getByRole("group", { name: "Rename layout" });
    expect(group).toBe(bodyNode());
    expect(group).toHaveAttribute("tabindex", "0");
  });

  it("with aria-label, the body is named by it", async () => {
    stubLayout();
    overflowing = true;
    await openHost(<Host aria-label="Terms of use">{<p>Long terms of use.</p>}</Host>);
    expect(screen().getByRole("group", { name: "Terms of use" })).toBe(bodyNode());
    expect(bodyNode()).not.toHaveAttribute("aria-labelledby");
  });

  it("a body that scrolls with a control in it, or that fits, is no Tab stop", async () => {
    stubLayout();
    overflowing = true;
    await openHost();
    expect(bodyNode()).not.toHaveAttribute("tabindex");
    expect(bodyNode()).not.toHaveAttribute("role");
    await key("Escape");
    overflowing = false;
    await openHost(<Host>{<p>Short.</p>}</Host>);
    expect(bodyNode()).not.toHaveAttribute("tabindex");
  });

  it("re-measures on a resize, and observes and measures content added while open", async () => {
    stubLayout();
    function Growing(): JSX.Element {
      const [more, setMore] = useState(false);
      return (
        <Host footer={<Button onClick={() => setMore(true)}>More</Button>}>
          <p>Short.</p>
          {more ? <p>Much longer text.</p> : null}
        </Host>
      );
    }
    await openHost(<Growing />);
    expect(bodyNode()).not.toHaveAttribute("tabindex");
    expect(observed).toContain(bodyNode());

    overflowing = true;
    await click(screen().getByRole("button", { name: "More" }));
    await act(async () => Promise.resolve());
    const added = screen().getByText("Much longer text.");
    expect(observed).toContain(added);
    expect(bodyNode()).toHaveAttribute("tabindex", "0");

    overflowing = false;
    await act(async () => resized?.());
    expect(bodyNode()).not.toHaveAttribute("tabindex");
  });
});

describe("inert ownership (stacked modals)", () => {
  /** Two dialogs that are not nested: each portals to `body`; the host drives both. */
  function Pair({ a, b }: { a: boolean; b: boolean }): JSX.Element {
    return (
      <>
        <div data-testid="page">
          <button type="button">Page control</button>
        </div>
        <Dialog open={a} title="Dialog A" onOpenChange={() => undefined}>
          <label>
            Alpha <input type="text" />
          </label>
        </Dialog>
        <Dialog open={b} title="Dialog B" onOpenChange={() => undefined}>
          <label>
            Beta <input type="text" />
          </label>
        </Dialog>
      </>
    );
  }

  const modes = [
    { mode: "aria-hidden fallback", native: false },
    { mode: "native inert", native: true },
  ] as const;

  const withInert = async (native: boolean, run: () => Promise<void>): Promise<void> => {
    if (native)
      Object.defineProperty(HTMLElement.prototype, "inert", { configurable: true, value: false });
    try {
      await run();
    } finally {
      if (native) delete (HTMLElement.prototype as { inert?: boolean }).inert;
    }
  };

  const hiddenBy =
    (native: boolean) =>
    (element: Element | null | undefined): boolean =>
      element !== null &&
      element !== undefined &&
      (native ? element.hasAttribute("inert") : element.getAttribute("aria-hidden") === "true");

  const layerOf = (title: string): Element | null | undefined =>
    [...document.querySelectorAll("[data-cv-layer]")].find(
      (layer) => layer.querySelector(".cv-dialog__title")?.textContent === title,
    );

  it.each(modes)(
    "$mode: open A then B (non-nested); close A → the page stays hidden; close B → restored",
    async ({ native }) =>
      withInert(native, async () => {
        const hidden = hiddenBy(native);
        const container = document.body.appendChild(document.createElement("div"));
        const root = createRoot(container);
        try {
          await act(async () => root.render(<Pair a b={false} />));
          await act(async () => root.render(<Pair a b />));
          expect(hidden(container)).toBe(true);
          expect(hidden(layerOf("Dialog A"))).toBe(true);
          expect(hidden(layerOf("Dialog B"))).toBe(false);

          await act(async () => root.render(<Pair a={false} b />));
          expect(layerOf("Dialog A")).toBeUndefined();
          expect(hidden(container)).toBe(true);

          await act(async () => root.render(<Pair a={false} b={false} />));
          expect(hidden(container)).toBe(false);
          expect(container.hasAttribute("aria-hidden")).toBe(false);
          expect(container.hasAttribute("inert")).toBe(false);
        } finally {
          await act(async () => root.unmount());
        }
      }),
  );

  it.each(modes)(
    "$mode: open A then B; close B first → A's root is restored and the page stays hidden",
    async ({ native }) =>
      withInert(native, async () => {
        const hidden = hiddenBy(native);
        const container = document.body.appendChild(document.createElement("div"));
        const root = createRoot(container);
        try {
          await act(async () => root.render(<Pair a b={false} />));
          await act(async () => root.render(<Pair a b />));
          await act(async () => root.render(<Pair a b={false} />));
          const a = layerOf("Dialog A");
          expect(a).toBeDefined();
          expect(hidden(a)).toBe(false);
          expect(a?.hasAttribute("aria-hidden")).toBe(false);
          expect(hidden(container)).toBe(true);
          expect(dialogNode("Dialog A")).toBeVisible();

          await act(async () => root.render(<Pair a={false} b={false} />));
          expect(hidden(container)).toBe(false);
        } finally {
          await act(async () => root.unmount());
        }
      }),
  );

  it.each(modes)(
    "$mode: a node hidden before any layer is never made visible, in either close order",
    async ({ native }) =>
      withInert(native, async () => {
        const hidden = hiddenBy(native);
        const before = document.body.appendChild(document.createElement("aside"));
        before.setAttribute(native ? "inert" : "aria-hidden", "true");
        const container = document.body.appendChild(document.createElement("div"));
        const root = createRoot(container);
        try {
          for (const [first, second] of [
            [
              { a: false, b: true },
              { a: false, b: false },
            ],
            [
              { a: true, b: false },
              { a: false, b: false },
            ],
          ] as const) {
            await act(async () => root.render(<Pair a b={false} />));
            await act(async () => root.render(<Pair a b />));
            await act(async () => root.render(<Pair {...first} />));
            expect(hidden(before)).toBe(true);
            await act(async () => root.render(<Pair {...second} />));
            expect(hidden(before)).toBe(true);
            expect(hidden(container)).toBe(false);
          }
        } finally {
          await act(async () => root.unmount());
        }
      }),
  );

  it("nested dialogs mounting open in one commit: the child is topmost, Esc reaches it first", async () => {
    const onParent = vi.fn();
    const onChild = vi.fn();
    function Nested(): JSX.Element {
      const [child, setChild] = useState(true);
      return (
        <Dialog open title="Parent" onOpenChange={onParent}>
          <label>
            Outer <input type="text" />
          </label>
          <Dialog
            open={child}
            title="Child"
            onOpenChange={(next, reason) => {
              onChild(next, reason);
              setChild(next);
            }}
          >
            <label>
              Inner <input type="text" />
            </label>
          </Dialog>
        </Dialog>
      );
    }
    await mount(<Nested />);
    await act(async () => Promise.resolve());
    // The parent's card is out of the tree under its child; focus is in the child.
    expect(screen().queryByRole("dialog", { name: "Parent" })).toBeNull();
    const inner = within(dialogNode("Child")).getByRole("textbox", { name: "Inner" });
    expect(inner).toHaveFocus();

    await key("Escape");
    expect(onChild).toHaveBeenCalledWith(false, "escape");
    expect(onParent).not.toHaveBeenCalled();
    expect(screen().queryByRole("dialog", { name: "Child" })).toBeNull();
    expect(dialogNode("Parent")).toBeVisible();

    await key("Escape");
    expect(onParent).toHaveBeenCalledWith(false, "escape");
  });

  it("disconnects its observer on close: a subtree added afterwards is left alone", async () => {
    await openHost();
    await key("Escape");
    expect(screen().queryByRole("dialog")).toBeNull();
    const late = document.body.appendChild(document.createElement("section"));
    await act(async () => Promise.resolve());
    expect(late).not.toHaveAttribute("aria-hidden");
    expect(late).not.toHaveAttribute("inert");
  });

  it("a Popover or Tooltip anchored in an exempt region stays live over an open Dialog", async () => {
    function Shell(): JSX.Element {
      return (
        <>
          <header data-cv-inert-exempt="">
            <Popover heading="Bar menu" anchor={<Button>Menu</Button>}>
              <button type="button">Bar action</button>
            </Popover>
            <Tooltip content="Kill switch" delay={0}>
              <button type="button">Panic</button>
            </Tooltip>
          </header>
          <Host />
        </>
      );
    }
    const host = await openHost(<Shell />);
    expect(dialogNode("Rename layout")).toBeVisible();
    const panel = document.querySelector<HTMLElement>(".cv-popover");
    // Closed, the panel is a page subtree like any other: the dialog's pass hid it.
    expect(panel).toHaveAttribute("aria-hidden", "true");

    await click(within(host).getByRole("button", { name: "Menu" }));
    const menu = screen().getByRole("dialog", { name: "Bar menu" });
    expect(menu).toHaveAttribute("data-cv-inert-exempt");
    expect(menu).not.toHaveAttribute("aria-hidden");
    expect(within(menu).getByRole("button", { name: "Bar action" })).toBeVisible();
    await key("Escape");
    expect(menu.hidden).toBe(true);
    expect(dialogNode("Rename layout")).toBeVisible();

    const panic = within(host).getByRole("button", { name: "Panic" });
    await act(async () => {
      fireEvent.pointerOver(panic);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const tip = screen().getByRole("tooltip", { name: "Kill switch" });
    expect(tip).toHaveAttribute("data-cv-inert-exempt");
    expect(tip).not.toHaveAttribute("aria-hidden");

    await key("Escape");
    await key("Escape");
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(panel).not.toHaveAttribute("aria-hidden");
  });
});
