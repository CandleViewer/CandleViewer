// @vitest-environment jsdom
import { act, StrictMode, useRef, useState, type JSX, type ReactNode } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import { Button, Dialog, Drawer, Popover, type DrawerProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-motion");
});

const key = async (key: string, shiftKey = false): Promise<boolean> => {
  let kept = true;
  await act(async () => {
    kept = await fireEvent.keyDown(document.activeElement ?? document.body, { key, shiftKey });
  });
  return kept;
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
const drawerNode = (name = "Instrument rules"): HTMLElement =>
  screen().getByRole("dialog", { name }) as HTMLElement;
const button = (name: string): HTMLElement => screen().getByRole("button", { name });

type Extra = Partial<Omit<DrawerProps, "open" | "onOpenChange" | "title">>;

/** A host: the opener, the page after it, and a drawer with a link, a field and a footer. */
function Host({
  onOpenChange,
  children,
  ...props
}: Extra & { onOpenChange?: DrawerProps["onOpenChange"]; children?: ReactNode }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <div data-testid="page">
        <button type="button">Before</button>
        <button type="button" onClick={() => setOpen(true)}>
          Open
        </button>
        <button type="button">After</button>
      </div>
      <Drawer
        open={open}
        title="Instrument rules"
        onOpenChange={(next, reason) => {
          onOpenChange?.(next, reason);
          setOpen(next);
        }}
        footer={<Button onClick={() => setOpen(false)}>Done</Button>}
        {...props}
      >
        {children ?? (
          <label>
            Rule name <input type="text" />
          </label>
        )}
      </Drawer>
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

// CMP-043's contract, run in both modes (the catalogue: "same contract as Dialog").
describe.each([
  ["modal", true],
  ["non-modal", false],
])("Drawer (CMP-046) %s: the Dialog contract", (_mode, modal) => {
  it("closed: renders nothing; open: a dialog named by its title, aria-modal only when modal", async () => {
    const host = await mount(<Host modal={modal} />);
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".cv-drawer-layer")).toBeNull();
    await click(within(host).getByRole("button", { name: "Open" }));
    const node = drawerNode();
    if (modal) expect(node).toHaveAttribute("aria-modal", "true");
    else expect(node).not.toHaveAttribute("aria-modal");
    expect(node).toHaveAttribute("data-cmp", "CMP-046");
    expect(node).toHaveAttribute("data-side", "right");
    expect(within(node).getByRole("heading", { level: 2, name: "Instrument rules" })).toBeVisible();
    expect(within(node).getByRole("button", { name: "Close Instrument rules" })).toBeVisible();
    expect(node.closest("[data-cv-layer]")?.parentElement).toBe(document.body);
    expect(document.querySelector(".cv-drawer__scrim") !== null).toBe(modal);
  });

  it("focus in on the heading (its body is content to read); Esc closes and focus returns", async () => {
    const onOpenChange = vi.fn();
    await openHost(<Host modal={modal} onOpenChange={onOpenChange} />);
    expect(screen().getByRole("heading", { name: "Instrument rules" })).toHaveFocus();
    await focus(screen().getByRole("textbox", { name: "Rule name" }));
    await key("Escape");
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "escape");
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(button("Open")).toHaveFocus();
  });

  it.each([
    ["on a tab stop", false],
    ["on a wrapper (its first tab stop)", true],
  ])("initialFocusRef wins: %s", async (_where, wrap) => {
    function Initial({ wrap }: { wrap: boolean }): JSX.Element {
      const wrapper = useRef<HTMLDivElement>(null);
      const direct = useRef<HTMLButtonElement>(null);
      return (
        <Host modal={modal} initialFocusRef={wrap ? wrapper : direct}>
          {wrap ? (
            <div ref={wrapper}>
              <button type="button">Edit rule</button>
            </div>
          ) : (
            <button ref={direct} type="button">
              Edit rule
            </button>
          )}
        </Host>
      );
    }
    await openHost(<Initial wrap={wrap} />);
    expect(button("Edit rule")).toHaveFocus();
  });

  it("the close button closes with its reason, focus back to the opener", async () => {
    const onOpenChange = vi.fn();
    await openHost(<Host modal={modal} onOpenChange={onOpenChange} />);
    await click(button("Close Instrument rules"));
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "close");
    expect(button("Open")).toHaveFocus();
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
          <Drawer
            open={open}
            modal={modal}
            title="Alert detail"
            fallbackFocusRef={bell}
            onOpenChange={setOpen}
            footer={<Button onClick={() => setOpener(false)}>Remove opener</Button>}
          />
        </>
      );
    }
    await openHost(<Gone />);
    await click(button("Remove opener"));
    await focus(button("Remove opener"));
    await key("Escape");
    expect(button("Alerts")).toHaveFocus();
  });

  it("aria-label overrides the title; busy, side, width, id and className reach the panel", async () => {
    await openHost(
      <Host
        modal={modal}
        aria-label="Order rejected - BTCUSDT - LIVE - Main"
        busy
        side="left"
        width={420}
        id="rejection"
        className="host-class"
      />,
    );
    const node = drawerNode("Order rejected - BTCUSDT - LIVE - Main");
    expect(node).not.toHaveAttribute("aria-labelledby");
    expect(node).toHaveAttribute("data-side", "left");
    expect(node).toHaveAttribute("id", "rejection");
    expect(node).toHaveClass("cv-drawer", "host-class");
    expect(node.style.getPropertyValue("--cv-drawer-width")).toBe("420px");
    expect(node.querySelector(".cv-drawer__body")).toHaveAttribute("aria-busy", "true");
  });

  it("a width that is no positive number is ignored (the CSS default stands)", async () => {
    await openHost(<Host modal={modal} width={Number.NaN} />);
    expect(drawerNode().style.getPropertyValue("--cv-drawer-width")).toBe("");
  });

  it("Esc closes the topmost layer only: a popover inside first, then the drawer", async () => {
    const onOpenChange = vi.fn();
    await openHost(
      <Host modal={modal} onOpenChange={onOpenChange}>
        <Popover heading="Line style" anchor={<Button>Line style</Button>}>
          <button type="button">Width</button>
        </Popover>
      </Host>,
    );
    await click(button("Line style"));
    const panel = screen().getByRole("dialog", { name: "Line style" });
    expect(panel.closest(".cv-drawer-layer")).not.toBeNull();
    await focus(within(panel).getByRole("button", { name: "Width" }));
    await key("Escape");
    expect(panel.hidden).toBe(true);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(button("Line style")).toHaveFocus();
    await key("Escape");
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "escape");
    expect(button("Open")).toHaveFocus();
  });

  it("StrictMode: focus in, Esc closes, focus back to the opener", async () => {
    await openHost(
      <StrictMode>
        <Host modal={modal} />
      </StrictMode>,
    );
    expect(screen().getByRole("heading", { name: "Instrument rules" })).toHaveFocus();
    await key("Escape");
    expect(button("Open")).toHaveFocus();
    expect(document.querySelector(".cv-drawer-layer")).toBeNull();
  });
});

describe("Drawer (CMP-046) modal", () => {
  it("the page is inert and does not scroll; Tab cycles inside", async () => {
    const host = await openHost();
    expect(within(host).getByTestId("page").closest("[aria-hidden='true']")).not.toBeNull();
    expect(document.documentElement.style.overflow).toBe("hidden");
    const close = button("Close Instrument rules");
    const done = button("Done");
    await focus(done);
    await key("Tab");
    expect(close).toHaveFocus();
    await key("Tab", true);
    expect(done).toHaveFocus();
    await key("Escape");
    expect(host.closest("[aria-hidden]")).toBeNull();
    expect(document.documentElement.style.overflow).toBe("");
  });

  it("a scrim press is Cancel; a click with no press that began on it does nothing", async () => {
    const onOpenChange = vi.fn();
    await openHost(<Host onOpenChange={onOpenChange} />);
    const scrim = document.querySelector(".cv-drawer__scrim");
    if (scrim === null) throw new Error("no scrim");
    await click(scrim);
    expect(onOpenChange).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.pointerDown(scrim);
      fireEvent.click(scrim);
    });
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "scrim");
    expect(button("Open")).toHaveFocus();
  });

  it("focus that escapes without a Tab is taken back inside", async () => {
    await openHost();
    const field = screen().getByRole("textbox", { name: "Rule name" });
    await focus(field);
    const outside = document.body.appendChild(document.createElement("button"));
    outside.setAttribute("data-cv-inert-exempt", "");
    await focus(outside);
    expect(field).toHaveFocus();
  });
});

describe("Drawer (CMP-046) non-modal", () => {
  it("the page stays live: not inert, still scrolling, no scrim", async () => {
    const host = await openHost(<Host modal={false} />);
    expect(within(host).getByTestId("page").closest("[aria-hidden], [inert]")).toBeNull();
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.querySelector(".cv-drawer__scrim")).toBeNull();
    expect(drawerNode()).not.toHaveAttribute("data-modal");
  });

  it("the Tab path: Tab past its last control moves on after the opener and it stays open", async () => {
    await openHost(<Host modal={false} />);
    await focus(button("Done"));
    await key("Tab");
    expect(button("After")).toHaveFocus();
    expect(drawerNode()).toBeVisible();
  });

  it("Shift+Tab before its first control (or from the heading) goes back to the opener", async () => {
    await openHost(<Host modal={false} />);
    await key("Tab", true);
    expect(button("Open")).toHaveFocus();
    await focus(button("Close Instrument rules"));
    await key("Tab", true);
    expect(button("Open")).toHaveFocus();
    expect(drawerNode()).toBeVisible();
  });

  it("it follows its opener: Tab on the opener goes in, Shift+Tab on the next stop comes back in", async () => {
    await openHost(<Host modal={false} />);
    await focus(button("Open"));
    await key("Tab");
    expect(button("Close Instrument rules")).toHaveFocus();
    await focus(button("After"));
    await key("Tab", true);
    expect(button("Done")).toHaveFocus();
    // Elsewhere on the page Tab is the browser's.
    await focus(button("Before"));
    expect(await key("Tab")).toBe(true);
    expect(button("Before")).toHaveFocus();
  });

  it("a middle control keeps the browser's Tab; the last stop on the page keeps it too", async () => {
    function Last(): JSX.Element {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <Drawer open={open} modal={false} title="Alert detail" onOpenChange={setOpen}>
            <button type="button">Acknowledge</button>
          </Drawer>
        </>
      );
    }
    await openHost(<Last />);
    await focus(button("Close Alert detail"));
    expect(await key("Tab")).toBe(true);
    await focus(button("Acknowledge"));
    expect(await key("Tab")).toBe(true);
    expect(button("Acknowledge")).toHaveFocus();
  });

  it("with the opener gone, the Tab path anchors on the host's fallback", async () => {
    function Gone(): JSX.Element {
      const [open, setOpen] = useState(false);
      const [opener, setOpener] = useState(true);
      const bell = useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={bell} type="button">
            Alerts
          </button>
          <button type="button">Chart</button>
          {opener ? (
            <button type="button" onClick={() => setOpen(true)}>
              Open
            </button>
          ) : null}
          <Drawer
            open={open}
            modal={false}
            title="Alert detail"
            fallbackFocusRef={bell}
            onOpenChange={setOpen}
          >
            <Button onClick={() => setOpener(false)}>Remove opener</Button>
          </Drawer>
        </>
      );
    }
    await openHost(<Gone />);
    await click(button("Remove opener"));
    await focus(button("Remove opener"));
    await key("Tab");
    expect(button("Chart")).toHaveFocus();
    await focus(button("Close Alert detail"));
    await key("Tab", true);
    expect(button("Alerts")).toHaveFocus();
  });

  it("Esc on the page stays the page's: the drawer stays open and the key is not taken", async () => {
    const onOpenChange = vi.fn();
    await openHost(<Host modal={false} onOpenChange={onOpenChange} />);
    await focus(button("After"));
    expect(await key("Escape")).toBe(true);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(drawerNode()).toBeVisible();
    await focus(drawerNode());
    expect(await key("Escape")).toBe(false);
    expect(onOpenChange).toHaveBeenLastCalledWith(false, "escape");
  });

  it("Esc passes to a layer under it that claims it (a dialog it was opened over)", async () => {
    function Over(): JSX.Element {
      const [dialog, setDialog] = useState(true);
      const [drawer, setDrawer] = useState(false);
      return (
        <Dialog open={dialog} title="Rules" onOpenChange={setDialog}>
          <button type="button" onClick={() => setDrawer(true)}>
            Details
          </button>
          <Drawer open={drawer} modal={false} title="Rule detail" onOpenChange={setDrawer} />
        </Dialog>
      );
    }
    await mount(<Over />);
    await click(button("Details"));
    expect(drawerNode("Rule detail")).toBeVisible();
    await focus(button("Details"));
    await key("Escape");
    expect(screen().queryByRole("dialog", { name: "Rules" })).toBeNull();
  });

  it("a modal dialog opened from the page makes the open drawer inert with the page", async () => {
    function Both(): JSX.Element {
      const [dialog, setDialog] = useState(false);
      return (
        <>
          <Host modal={false} />
          <button type="button" onClick={() => setDialog(true)}>
            Settings
          </button>
          <Dialog open={dialog} title="Settings" onOpenChange={setDialog} />
        </>
      );
    }
    await openHost(<Both />);
    const layer = drawerNode().closest(".cv-drawer-layer");
    await focus(button("Settings"));
    await click(button("Settings"));
    expect(layer).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Drawer slide out", () => {
  /** The panel slides out over 150 ms (the longest of its transitions). */
  const stubSlide = (): void => {
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) =>
      element.classList.contains("cv-drawer")
        ? ({
            transitionDuration: "150ms",
            getPropertyValue: () => "",
          } as unknown as CSSStyleDeclaration)
        : real(element, pseudo),
    );
  };
  const layerNode = (): Element | null => document.querySelector(".cv-drawer-layer");

  it("keeps the layer inert and closing until the panel's own transitionend", async () => {
    stubSlide();
    await openHost();
    const panel = drawerNode();
    await key("Escape");
    const layer = layerNode();
    expect(layer).toHaveAttribute("data-state", "closing");
    expect(layer).toHaveAttribute("inert");
    expect(button("Open")).toHaveFocus();
    await act(async () => {
      fireEvent.transitionEnd(panel.querySelector(".cv-drawer__header") ?? panel);
    });
    expect(layerNode()).not.toBeNull();
    await act(async () => {
      fireEvent.transitionEnd(panel);
    });
    expect(layerNode()).toBeNull();
  });

  it("a slide that never reports its end clears at the fallback timer", async () => {
    vi.useFakeTimers();
    stubSlide();
    await openHost();
    await key("Escape");
    expect(layerNode()).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(260);
    });
    expect(layerNode()).toBeNull();
  });

  it("reduced motion is a cut: the layer goes at once", async () => {
    stubSlide();
    document.documentElement.setAttribute("data-motion", "reduce");
    await openHost();
    await key("Escape");
    expect(layerNode()).toBeNull();
  });
});

describe("Drawer readable body", () => {
  it("a body that scrolls with no control in it is a Tab stop named by the title", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains("cv-drawer__body") ? 900 : 100;
    });
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    await openHost(<Host modal={false}>{<p>Long methodology.</p>}</Host>);
    const group = screen().getByRole("group", { name: "Instrument rules" });
    expect(group).toHaveClass("cv-drawer__body");
    expect(group).toHaveAttribute("tabindex", "0");
  });
});
