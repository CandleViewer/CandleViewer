// @vitest-environment jsdom
import { act, StrictMode, useRef, useState, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import { Button, Popover, Tooltip, type PopoverProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

afterEach(() => vi.restoreAllMocks());

/**
 * This component's listener calls: React's own delegated listeners (bound `dispatch*` functions, added
 * once per document or root, whichever test runs first) and its development `error` listener are not.
 */
/** A removal that matches an addition: same type, same listener, same capture flag. */
const removedLike = (
  calls: unknown[][],
  type: unknown,
  listener: unknown,
  options: unknown,
): boolean =>
  calls.some(([t, l, o]) => t === type && l === listener && Boolean(o) === Boolean(options));

const mine = <T extends readonly unknown[]>(calls: T[]): T[] =>
  calls.filter(
    ([type, listener]) =>
      type !== "error" &&
      !(typeof listener === "function" && /^bound dispatch/.test(listener.name)),
  );

const panel = (): HTMLElement => {
  const node = document.querySelector<HTMLElement>(".cv-popover");
  if (node === null) throw new Error("no popover node");
  return node;
};
const isOpen = (): boolean => !panel().hidden;
const trigger = (host: HTMLElement, name = "Line style"): HTMLButtonElement =>
  within(host).getByRole("button", { name }) as HTMLButtonElement;
const click = async (el: Element): Promise<void> => {
  await act(async () => {
    fireEvent.click(el);
  });
};
const key = async (key: string, shiftKey = false): Promise<void> => {
  await act(async () => {
    fireEvent.keyDown(document.activeElement ?? document.body, { key, shiftKey });
  });
};
const focus = async (el: HTMLElement): Promise<void> => {
  await act(async () => el.focus());
};
const pointer = async (down: Element, up: Element = down): Promise<void> => {
  await act(async () => {
    fireEvent.pointerDown(down);
  });
  await act(async () => {
    fireEvent.pointerUp(up);
  });
};
const dialog = (): HTMLElement =>
  within(document.body).getByRole("dialog", { hidden: false }) as HTMLElement;

/** SCR-037's property popover: a field, two swatches, then Save as default · Delete. */
function Form(props: Partial<PopoverProps>): JSX.Element {
  return (
    <>
      <Popover aria-label="Line style" anchor={<Button>Line style</Button>} {...(props as object)}>
        <label>
          Width <input type="text" defaultValue="2" />
        </label>
        <button type="button">Red</button>
        <button type="button">Blue</button>
      </Popover>
      <button type="button">After</button>
      <div data-testid="page">page</div>
    </>
  );
}

const open = async (props: Partial<PopoverProps> = {}): Promise<HTMLElement> => {
  const host = await mount(<Form {...props} />);
  await click(trigger(host));
  return host;
};

describe("Popover (CMP-017)", () => {
  it("closed: hidden, out of the accessibility tree; the anchor carries haspopup, expanded and controls", async () => {
    const host = await mount(<Form />);
    const button = trigger(host);
    expect(panel().hidden).toBe(true);
    expect(within(document.body).queryByRole("dialog")).toBeNull();
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", panel().id);
    expect(panel()).toHaveAttribute("data-cmp", "CMP-017");
    expect(panel()).toHaveAttribute("data-placement", "below");
  });

  it("Gherkin 'Popover focus management': opening moves focus into it (its first control)", async () => {
    const host = await open();
    expect(isOpen()).toBe(true);
    expect(trigger(host)).toHaveAttribute("aria-expanded", "true");
    const node = dialog();
    expect(node).toHaveAccessibleName("Line style");
    expect(node).not.toHaveAttribute("aria-modal");
    expect(within(node).getByRole("textbox", { name: "Width" })).toHaveFocus();
  });

  it("Gherkin: Escape closes it and returns focus to the trigger, and stops there", async () => {
    const onOpenChange = vi.fn();
    const outer = vi.fn();
    document.addEventListener("keydown", outer);
    const host = await open({ onOpenChange });
    await key("Escape");
    document.removeEventListener("keydown", outer);
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();
    expect(trigger(host)).toHaveAttribute("aria-expanded", "false");
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(outer).not.toHaveBeenCalled();
  });

  it("Gherkin, modal: Tab is contained; it cycles inside both ways; Esc returns to the trigger", async () => {
    const host = await open({ modal: true });
    const node = dialog();
    expect(node).toHaveAttribute("aria-modal", "true");
    const [, red, blue] = [
      within(node).getByRole("textbox"),
      ...within(node).getAllByRole("button"),
    ] as HTMLElement[];
    const field = within(node).getByRole("textbox");
    await focus(blue as HTMLElement);
    await key("Tab");
    expect(field).toHaveFocus();
    await key("Tab", true);
    expect(blue).toHaveFocus();
    await focus(red as HTMLElement);
    await key("Tab");
    expect(red).toHaveFocus(); // a middle stop: the browser moves on, the trap does not interfere
    expect(isOpen()).toBe(true);
    await key("Escape");
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();
  });

  it("modal: an outside press closes it too, focus going to the pressed control", async () => {
    const host = await open({ modal: true });
    const after = within(host).getByRole("button", { name: "After" });
    await act(async () => {
      fireEvent.pointerDown(after);
      after.focus();
    });
    await act(async () => {
      fireEvent.pointerUp(after);
    });
    expect(isOpen()).toBe(false);
    expect(after).toHaveFocus();
  });

  it("modal: from the heading (no control focused) Tab goes to the first and Shift+Tab to the last", async () => {
    await open({ modal: true, heading: "Line style" } as Partial<PopoverProps>);
    const node = dialog();
    await focus(within(node).getByRole("heading", { name: "Line style" }));
    await key("Tab");
    expect(within(node).getByRole("textbox")).toHaveFocus();
    await focus(within(node).getByRole("heading"));
    await key("Tab", true);
    expect(within(node).getByRole("button", { name: "Blue" })).toHaveFocus();
  });

  it("modal: a panel with no control keeps Tab on itself; focus that escapes is taken back", async () => {
    const host = await mount(
      <>
        <Popover modal aria-label="Note" anchor={<Button>Note</Button>}>
          Read-only text
        </Popover>
        <button type="button">Elsewhere</button>
      </>,
    );
    await click(trigger(host, "Note"));
    expect(panel()).toHaveFocus();
    await key("Tab");
    expect(panel()).toHaveFocus();
    await focus(within(host).getByRole("button", { name: "Elsewhere" }));
    expect(panel()).toHaveFocus();
    expect(isOpen()).toBe(true);
  });

  it("non-modal: Tab past the last control closes it and moves on from the trigger (H11)", async () => {
    const onOpenChange = vi.fn();
    const host = await open({ onOpenChange });
    await focus(within(dialog()).getByRole("button", { name: "Blue" }));
    await key("Tab");
    expect(isOpen()).toBe(false);
    expect(within(host).getByRole("button", { name: "After" })).toHaveFocus();
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
  });

  it("non-modal: Tab past the last with nothing after the trigger lands on the trigger", async () => {
    const host = await mount(
      <Popover aria-label="Only" anchor={<Button>Only</Button>}>
        <button type="button">One</button>
      </Popover>,
    );
    await click(trigger(host, "Only"));
    await key("Tab");
    expect(isOpen()).toBe(false);
    expect(trigger(host, "Only")).toHaveFocus();
  });

  it("non-modal: Shift+Tab before the first control returns to the trigger and closes it (H11)", async () => {
    const host = await open();
    await key("Tab", true);
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();
  });

  it("non-modal: a middle Tab is left to the browser", async () => {
    await open();
    await key("Tab");
    expect(isOpen()).toBe(true);
  });

  it("non-modal: focus leaving it by other means closes it, focus staying where it went", async () => {
    const host = await open();
    const after = within(host).getByRole("button", { name: "After" });
    await focus(after);
    expect(isOpen()).toBe(false);
    expect(after).toHaveFocus();
  });

  it("focus fallbacks: initialFocusRef, else the first control, else the heading, else the panel", async () => {
    function WithRef(): JSX.Element {
      const blue = useRef<HTMLButtonElement>(null);
      return (
        <Popover aria-label="Ref" initialFocusRef={blue} anchor={<Button>Ref</Button>}>
          <button type="button">Red</button>
          <button type="button" ref={blue}>
            Blue
          </button>
        </Popover>
      );
    }
    const a = await mount(<WithRef />);
    await click(trigger(a, "Ref"));
    expect(within(dialog()).getByRole("button", { name: "Blue" })).toHaveFocus();
    await key("Escape");

    const b = await mount(
      <Popover heading="Session details" anchor={<Button>Details</Button>}>
        <p>Connected 12 minutes ago.</p>
      </Popover>,
    );
    await click(trigger(b, "Details"));
    const heading = within(dialog()).getByRole("heading", { name: "Session details" });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(dialog()).toHaveAccessibleName("Session details");
  });

  it("names: aria-labelledby wins over the heading; the type admits no unnamed popover", async () => {
    const host = await mount(
      <>
        <span id="ext">External name</span>
        <Popover aria-labelledby="ext" heading="Shown heading" anchor={<Button>Named</Button>}>
          <button type="button">x</button>
        </Popover>
      </>,
    );
    await click(trigger(host, "Named"));
    expect(dialog()).toHaveAccessibleName("External name");
    const anchor = <Button>a</Button>;
    // @ts-expect-error H11: a name is required (aria-label, aria-labelledby or the heading)
    const unnamed: PopoverProps = { anchor };
    // @ts-expect-error one name only: aria-label and aria-labelledby together are refused
    const both: PopoverProps = { anchor, "aria-label": "a", "aria-labelledby": "b" };
    expect([unnamed, both]).toHaveLength(2);
  });

  it("an outside press that starts and ends outside closes it; focus returns to the trigger", async () => {
    const host = await open();
    await pointer(within(host).getByTestId("page"));
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();
  });

  it("an outside press on a control closes it and leaves focus on the pressed control", async () => {
    const host = await open();
    const after = within(host).getByRole("button", { name: "After" });
    await act(async () => {
      fireEvent.pointerDown(after);
      after.focus(); // what the browser does on the press
    });
    expect(isOpen()).toBe(true); // the press is not over yet: blur alone does not close it
    await act(async () => {
      fireEvent.pointerUp(after);
    });
    expect(isOpen()).toBe(false);
    expect(after).toHaveFocus();
  });

  it("a drag that starts inside and ends outside does not close it", async () => {
    const host = await open();
    await pointer(within(dialog()).getByRole("textbox"), within(host).getByTestId("page"));
    expect(isOpen()).toBe(true);
  });

  it("a press that starts outside and ends inside keeps it open with focus back inside", async () => {
    const host = await open();
    const field = within(dialog()).getByRole("textbox");
    const after = within(host).getByRole("button", { name: "After" });
    await act(async () => {
      fireEvent.pointerDown(after);
      after.focus();
    });
    await act(async () => {
      fireEvent.pointerUp(field);
    });
    expect(isOpen()).toBe(true);
    expect(field).toHaveFocus();
  });

  it("a cancelled press does nothing", async () => {
    const host = await open();
    await act(async () => {
      fireEvent.pointerDown(within(host).getByTestId("page"));
      fireEvent.pointerCancel(within(host).getByTestId("page"));
      fireEvent.pointerUp(within(host).getByTestId("page"));
    });
    expect(isOpen()).toBe(true);
  });

  it("a press on the trigger while open closes it once (no close-then-reopen)", async () => {
    const onOpenChange = vi.fn();
    const host = await open({ onOpenChange });
    const button = trigger(host);
    await act(async () => {
      fireEvent.pointerDown(button);
      button.focus();
    });
    await act(async () => {
      fireEvent.pointerUp(button);
      fireEvent.click(button);
    });
    expect(isOpen()).toBe(false);
    expect(onOpenChange.mock.calls).toEqual([[true], [false]]);
    expect(button).toHaveFocus();
  });

  it("composes the anchor's own onClick first; preventDefault keeps it closed", async () => {
    const order: string[] = [];
    const host = await mount(
      <Popover
        aria-label="P"
        anchor={
          <Button
            onClick={(event) => {
              order.push("own");
              event.preventDefault();
            }}
          >
            P
          </Button>
        }
      >
        <button type="button">x</button>
      </Popover>,
    );
    await click(trigger(host, "P"));
    expect(order).toEqual(["own"]);
    expect(isOpen()).toBe(false);
  });

  it("controlled: renders open, reports changes, and stays open while the host keeps it open", async () => {
    const onOpenChange = vi.fn();
    const host = await mount(
      <Popover
        open
        onOpenChange={onOpenChange}
        aria-label="Controlled"
        anchor={<Button>Controlled</Button>}
        placement="above"
      >
        <button type="button">Inside</button>
      </Popover>,
    );
    expect(isOpen()).toBe(true);
    expect(within(dialog()).getByRole("button", { name: "Inside" })).toHaveFocus();
    expect(panel()).toHaveAttribute("data-placement", "above");
    await key("Escape");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(isOpen()).toBe(true);
    expect(trigger(host, "Controlled")).toHaveAttribute("aria-expanded", "true");
  });

  it("a host that closes it from inside (Save) returns focus to the trigger", async () => {
    function Host(): JSX.Element {
      const [shown, setShown] = useState(false);
      return (
        <Popover
          open={shown}
          onOpenChange={setShown}
          aria-label="Save"
          anchor={<Button>Edit</Button>}
          footer={<Button onClick={() => setShown(false)}>Save as default</Button>}
        >
          <input aria-label="Width" />
        </Popover>
      );
    }
    const host = await mount(<Host />);
    await click(trigger(host, "Edit"));
    const save = within(dialog()).getByRole("button", { name: "Save as default" });
    await focus(save);
    await click(save);
    expect(isOpen()).toBe(false);
    expect(trigger(host, "Edit")).toHaveFocus();
  });

  it("Esc on a tooltip inside closes the tooltip only (the topmost layer)", async () => {
    const host = await mount(
      <Popover aria-label="Layer" anchor={<Button>Layer</Button>}>
        <Tooltip content="Removes the drawing.">
          <Button>Delete</Button>
        </Tooltip>
      </Popover>,
    );
    await click(trigger(host, "Layer"));
    const tip = document.querySelector<HTMLElement>(".cv-tooltip");
    expect(within(dialog()).getByRole("button", { name: "Delete" })).toHaveFocus();
    expect(tip?.hidden).toBe(false);
    await key("Escape");
    expect(tip?.hidden).toBe(true);
    expect(isOpen()).toBe(true);
    await key("Escape");
    expect(isOpen()).toBe(false);
  });

  it("heading, body and footer parts; className joins", async () => {
    await mount(
      <Popover
        defaultOpen
        heading="Parts"
        className="extra"
        anchor={<Button>Parts</Button>}
        footer={<Button>Done</Button>}
      >
        <p>Body</p>
      </Popover>,
    );
    expect(panel()).toHaveClass("cv-popover", "extra");
    expect(panel().querySelector(".cv-popover__heading")).toHaveTextContent("Parts");
    expect(panel().querySelector(".cv-popover__body")).toHaveTextContent("Body");
    expect(panel().querySelector(".cv-popover__footer")).toHaveTextContent("Done");
  });

  it("adds no document or window listener while closed, and removes every one it adds", async () => {
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const winAdd = vi.spyOn(window, "addEventListener");
    const winRemove = vi.spyOn(window, "removeEventListener");
    const host = await mount(<Form />);
    expect(mine(docAdd.mock.calls)).toEqual([]);
    expect(mine(winAdd.mock.calls)).toEqual([]);

    await click(trigger(host));
    expect(docAdd).toHaveBeenCalledWith("pointerdown", expect.any(Function), true);
    expect(winAdd).toHaveBeenCalledWith("scroll", expect.any(Function));
    await key("Escape");
    for (const [type, listener, options] of mine(docAdd.mock.calls))
      expect(removedLike(docRemove.mock.calls, type, listener, options)).toBe(true);
    for (const [type, listener] of mine(winAdd.mock.calls))
      expect(winRemove.mock.calls.some(([t, l]) => t === type && l === listener)).toBe(true);
  });

  it("unmounting while open removes its listeners", async () => {
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () => root.render(<Form defaultOpen />));
    expect(docAdd).toHaveBeenCalled();
    await act(async () => root.unmount());
    for (const [type, listener, options] of mine(docAdd.mock.calls))
      expect(removedLike(docRemove.mock.calls, type, listener, options)).toBe(true);
  });

  it("StrictMode: opens with focus inside, closes on Esc to the trigger, listeners balanced", async () => {
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const host = await mount(
      <StrictMode>
        <Form />
      </StrictMode>,
    );
    await click(trigger(host));
    expect(isOpen()).toBe(true);
    expect(within(dialog()).getByRole("textbox")).toHaveFocus();
    await key("Escape");
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();
    expect(mine(docRemove.mock.calls)).toHaveLength(mine(docAdd.mock.calls).length);
  });

  it("closed: the content clears and an empty hidden shell stays, so aria-controls stays valid", async () => {
    const host = await open();
    expect(within(panel()).getByRole("textbox")).toBeInTheDocument();
    await key("Escape");
    expect(panel().hidden).toBe(true);
    expect(panel()).toBeEmptyDOMElement();
    expect(document.getElementById(trigger(host).getAttribute("aria-controls") ?? "")).toBe(
      panel(),
    );
  });

  it("the content stays through the exit fade and clears on transitionend", async () => {
    const host = await open();
    panel().style.transitionDuration = "0.15s";
    await key("Escape");
    expect(panel().hidden).toBe(true);
    expect(trigger(host)).toHaveFocus();
    expect(panel().querySelector(".cv-popover__body")).not.toBeNull();
    await act(async () => {
      panel().dispatchEvent(new Event("transitionend"));
    });
    expect(panel()).toBeEmptyDOMElement();
  });

  it("a fade that never reports its end still clears after its duration", async () => {
    vi.useFakeTimers();
    try {
      await open();
      panel().style.transitionDuration = "150ms";
      await key("Escape");
      expect(panel()).not.toBeEmptyDOMElement();
      await act(async () => {
        vi.advanceTimersByTime(260);
      });
      expect(panel()).toBeEmptyDOMElement();
    } finally {
      vi.useRealTimers();
    }
  });

  it("reduced motion: the content clears at once, with no wait for a fade", async () => {
    document.documentElement.setAttribute("data-motion", "reduce");
    try {
      await open();
      panel().style.transitionDuration = "0.15s";
      await key("Escape");
      expect(panel()).toBeEmptyDOMElement();
    } finally {
      document.documentElement.removeAttribute("data-motion");
    }
  });

  it("reopening during the exit fade keeps the content and focuses into it again", async () => {
    const host = await open();
    panel().style.transitionDuration = "0.15s";
    await key("Escape");
    await click(trigger(host));
    expect(isOpen()).toBe(true);
    expect(within(dialog()).getByRole("textbox")).toHaveFocus();
    await act(async () => {
      panel().dispatchEvent(new Event("transitionend"));
    });
    expect(within(dialog()).getByRole("textbox")).toBeInTheDocument();
  });

  it("a fresh initialFocusRef object per render neither steals focus nor closes it", async () => {
    let rerender: () => void = () => undefined;
    function Fresh(): JSX.Element {
      const [, setTick] = useState(0);
      rerender = () => setTick((t) => t + 1);
      const blue = useRef<HTMLButtonElement>(null);
      return (
        <Popover
          aria-label="Fresh"
          initialFocusRef={{ current: blue.current }}
          anchor={<Button>Fresh</Button>}
        >
          <button type="button">Red</button>
          <button type="button" ref={blue}>
            Blue
          </button>
        </Popover>
      );
    }
    const host = await mount(<Fresh />);
    await click(trigger(host, "Fresh"));
    const red = within(dialog()).getByRole("button", { name: "Red" });
    await focus(red);
    await act(async () => rerender());
    await act(async () => rerender());
    expect(isOpen()).toBe(true);
    expect(red).toHaveFocus();
  });

  it("Esc closes it while focus is outside it: on the anchor, or lost to the body", async () => {
    const host = await open();
    await act(async () => {
      fireEvent.keyDown(trigger(host), { key: "Escape" });
    });
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();

    await click(trigger(host));
    await act(async () => (document.activeElement as HTMLElement | null)?.blur());
    expect(isOpen()).toBe(true);
    await key("Escape");
    expect(isOpen()).toBe(false);
    expect(trigger(host)).toHaveFocus();
  });

  it("an Esc another layer already handled is left alone", async () => {
    await open();
    await act(async () => {
      const event = new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
      });
      event.preventDefault();
      document.body.dispatchEvent(event);
    });
    expect(isOpen()).toBe(true);
  });
});
