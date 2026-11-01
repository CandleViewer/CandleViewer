// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { Button, Tooltip, type TooltipProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

const TEXT = "Saves the layout under a new name.";
let clock = Date.UTC(2030, 0, 1);

beforeEach(() => {
  vi.useFakeTimers();
  // A fresh minute per test: the 300 ms skip window never carries over from the previous test.
  clock += 60_000;
  vi.setSystemTime(clock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** React's development build adds and removes a window `error` listener around each event it dispatches. */
const ours = <T extends readonly unknown[]>(calls: T[]): T[] =>
  calls.filter((c) => c[0] !== "error");

const removed = (calls: unknown[][], type: unknown, listener: unknown): boolean =>
  calls.some(([t, l]) => t === type && l === listener);

const tip = (): HTMLElement => {
  const node = document.querySelector<HTMLElement>(".cv-tooltip");
  if (node === null) throw new Error("no tooltip node");
  return node;
};
const shown = (): boolean => !tip().hidden;
const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const hover = async (el: Element): Promise<void> => {
  await act(async () => {
    fireEvent.pointerOver(el);
  });
};
const unhover = async (el: Element): Promise<void> => {
  await act(async () => {
    fireEvent.pointerOut(el);
  });
};
const focus = async (el: HTMLElement): Promise<void> => {
  await act(async () => el.focus());
};
const press = async (el: Element, key: string): Promise<void> => {
  await act(async () => {
    fireEvent.keyDown(el, { key });
  });
};

const saveAs = (props: Partial<Parameters<typeof Tooltip>[0]> = {}): Promise<HTMLElement> =>
  mount(
    <Tooltip content={TEXT} {...props}>
      <Button>Save as</Button>
    </Tooltip>,
  );
const trigger = (host: HTMLElement, name = "Save as"): HTMLButtonElement =>
  within(host).getByRole("button", { name }) as HTMLButtonElement;

describe("Tooltip (CMP-016)", () => {
  it("describes: a role=tooltip node in the DOM at mount, hidden, and the trigger's description", async () => {
    const host = await saveAs();
    const node = tip();
    expect(node).toHaveAttribute("role", "tooltip");
    expect(node).toHaveAttribute("data-cmp", "CMP-016");
    expect(node).toHaveAttribute("data-mode", "describes");
    expect(node).toHaveAttribute("data-side", "top");
    expect(node).not.toHaveAttribute("aria-hidden");
    expect(node.hidden).toBe(true);
    expect(node).toHaveTextContent(TEXT);
    const button = trigger(host);
    expect(button).toHaveAttribute("aria-describedby", node.id);
    expect(button).toHaveAccessibleDescription(TEXT);
    expect(button).not.toHaveAttribute("title");
  });

  it("keeps the trigger's own aria-describedby and adds its id after it", async () => {
    const host = await mount(
      <>
        <span id="hint">Ctrl+S</span>
        <Tooltip content={TEXT}>
          <button type="button" aria-describedby="hint">
            Save as
          </button>
        </Tooltip>
      </>,
    );
    expect(trigger(host)).toHaveAttribute("aria-describedby", `hint ${tip().id}`);
  });

  it("echo: aria-hidden and never in the description; the trigger keeps its own name", async () => {
    const host = await mount(
      <Tooltip content="Settings" mode="echo">
        <button type="button" aria-label="Settings" />
      </Tooltip>,
    );
    const button = trigger(host, "Settings");
    expect(tip()).toHaveAttribute("aria-hidden", "true");
    expect(tip()).toHaveAttribute("data-mode", "echo");
    expect(button).not.toHaveAttribute("aria-describedby");
    expect(button).toHaveAccessibleName("Settings");
  });

  it("echo of a T2 reason: the description stays the always-rendered reason node, read once", async () => {
    const reason = "Only the owner can change account settings.";
    const host = await mount(
      <>
        <Tooltip content={reason} mode="echo">
          <button type="button" aria-label="Account settings" aria-disabled aria-describedby="r" />
        </Tooltip>
        <span id="r">{reason}</span>
      </>,
    );
    const button = trigger(host, "Account settings");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(reason);
    expect(button.getAttribute("aria-describedby")?.split(" ")).not.toContain(tip().id);
    await focus(button);
    expect(shown()).toBe(true);
  });

  it("empty content renders no node, adds no description and never shows", async () => {
    const host = await mount(
      <Tooltip content="  ">
        <Button>Save as</Button>
      </Tooltip>,
    );
    const button = trigger(host);
    expect(document.querySelector(".cv-tooltip")).toBeNull();
    expect(button).not.toHaveAttribute("aria-describedby");
    await hover(button);
    await advance(300);
    await focus(button);
    expect(document.querySelector(".cv-tooltip")).toBeNull();
  });

  it("content emptied while shown: the node goes and Esc reaches the host again", async () => {
    const onKey = vi.fn();
    let setContent: (next: string) => void = () => undefined;
    function Host(): JSX.Element {
      const [content, set] = useState(TEXT);
      setContent = set;
      return (
        <Tooltip content={content} mode="echo">
          <Button>Save as</Button>
        </Tooltip>
      );
    }
    const host = await mount(<Host />);
    const button = trigger(host);
    document.addEventListener("keydown", onKey);
    await focus(button);
    expect(shown()).toBe(true);
    await act(async () => setContent(""));
    expect(document.querySelector(".cv-tooltip")).toBeNull();
    expect(button).toHaveFocus();
    await press(button, "Escape");
    expect(onKey).toHaveBeenCalledTimes(1);
    document.removeEventListener("keydown", onKey);
  });

  it("content that arrives while the trigger holds keyboard focus or the pointer shows at once", async () => {
    let setContent: (next: string) => void = () => undefined;
    function Host(): JSX.Element {
      const [content, set] = useState("");
      setContent = set;
      return (
        <Tooltip content={content} mode="echo">
          <Button>Save as</Button>
        </Tooltip>
      );
    }
    const host = await mount(<Host />);
    const button = trigger(host);
    await focus(button);
    await act(async () => setContent(TEXT));
    expect(shown()).toBe(true);
    await act(async () => button.blur());
    await act(async () => setContent(""));
    await hover(button);
    await act(async () => setContent(TEXT));
    expect(shown()).toBe(true);
    await unhover(button);
    await advance(100);
    expect(shown()).toBe(false);
  });

  it("content that arrives after an Esc dismissal does not show until focus moves", async () => {
    let setContent: (next: string) => void = () => undefined;
    function Host(): JSX.Element {
      const [content, set] = useState(TEXT);
      setContent = set;
      return (
        <Tooltip content={content} mode="echo">
          <Button>Save as</Button>
        </Tooltip>
      );
    }
    const host = await mount(<Host />);
    const button = trigger(host);
    await focus(button);
    expect(shown()).toBe(true);
    await press(button, "Escape");
    expect(shown()).toBe(false);
    await act(async () => setContent(""));
    await act(async () => setContent("Only the owner can save layouts."));
    expect(shown()).toBe(false);
    expect(button).toHaveFocus();
  });

  /** A host whose trigger can go natively disabled and whose content can change. */
  const gated = async (): Promise<{
    button: HTMLButtonElement;
    set: (next: { content?: string; disabled?: boolean }) => Promise<void>;
  }> => {
    let update: (next: { content?: string; disabled?: boolean }) => void = () => undefined;
    function Host(): JSX.Element {
      const [state, setState] = useState({ content: "", disabled: false });
      update = (next) => setState((s) => ({ ...s, ...next }));
      return (
        <Tooltip content={state.content} mode="echo">
          <button type="button" disabled={state.disabled}>
            Save as
          </button>
        </Tooltip>
      );
    }
    const host = await mount(<Host />);
    return {
      button: trigger(host),
      set: async (next) => {
        await act(async () => update(next));
      },
    };
  };

  it("a hovered trigger that goes natively disabled keeps no stale hover for content that arrives", async () => {
    const { button, set } = await gated();
    await hover(button);
    // Disabled controls fire no pointer leave: the remembered hover would otherwise show the new content.
    await set({ disabled: true });
    await set({ content: TEXT });
    expect(shown()).toBe(false);
    await advance(1000);
    expect(shown()).toBe(false);
  });

  it("blur of a trigger that went natively disabled forgets the hover and hides", async () => {
    const { button, set } = await gated();
    await set({ content: TEXT });
    await hover(button);
    await advance(300);
    await focus(button);
    expect(shown()).toBe(true);
    await set({ disabled: true });
    await act(async () => {
      fireEvent.focusOut(button);
    });
    expect(shown()).toBe(false);
    // The stale hover is gone: re-enabling and new content do not reopen it with no pointer there.
    await set({ disabled: false });
    await set({ content: "Only the owner can save layouts." });
    expect(shown()).toBe(false);
  });

  it("a cancelled pointer leaves like a pointer leave, after the 100 ms grace", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await hover(button);
    await advance(300);
    expect(shown()).toBe(true);
    await act(async () => {
      fireEvent.pointerCancel(button);
    });
    await advance(100);
    expect(shown()).toBe(false);
  });

  it("hover shows it after the 300 ms delay, not before", async () => {
    const host = await saveAs();
    await hover(trigger(host));
    await advance(299);
    expect(shown()).toBe(false);
    await advance(1);
    expect(shown()).toBe(true);
  });

  it("delay sets the hover wait", async () => {
    const host = await saveAs({ delay: 600 });
    await hover(trigger(host));
    await advance(500);
    expect(shown()).toBe(false);
    await advance(100);
    expect(shown()).toBe(true);
  });

  it("leaving before the delay cancels the show", async () => {
    const host = await saveAs();
    await hover(trigger(host));
    await advance(200);
    await unhover(trigger(host));
    await advance(1000);
    expect(shown()).toBe(false);
  });

  it("hides on leave after a 100 ms grace; the pointer may cross onto the tooltip and stay", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await hover(button);
    await advance(300);
    await unhover(button);
    await advance(99);
    expect(shown()).toBe(true);
    await hover(tip());
    await advance(5000);
    expect(shown()).toBe(true); // never on a timer (WCAG 1.4.13)
    await unhover(tip());
    await advance(100);
    expect(shown()).toBe(false);
  });

  it("a second trigger within the 300 ms skip window shows at once", async () => {
    const host = await mount(
      <>
        <Tooltip content="First">
          <Button>One</Button>
        </Tooltip>
        <Tooltip content="Second">
          <Button>Two</Button>
        </Tooltip>
      </>,
    );
    const [first, second] = [trigger(host, "One"), trigger(host, "Two")];
    await hover(first);
    await advance(300);
    await unhover(first);
    await advance(100);
    await hover(second);
    await advance(0);
    const nodes = document.querySelectorAll<HTMLElement>(".cv-tooltip");
    expect(nodes[1]?.hidden).toBe(false);
  });

  const pair = (): Promise<HTMLElement> =>
    mount(
      <>
        <Tooltip content="First">
          <Button>One</Button>
        </Tooltip>
        <Tooltip content="Second">
          <Button>Two</Button>
        </Tooltip>
      </>,
    );
  const second = (): HTMLElement | undefined =>
    document.querySelectorAll<HTMLElement>(".cv-tooltip")[1];

  it.each([0, 25, 50])(
    "moving straight from a shown trigger to the next (a %i ms gap) opens the next at once",
    async (gap) => {
      const host = await pair();
      const [one, two] = [trigger(host, "One"), trigger(host, "Two")];
      await hover(one);
      await advance(300);
      expect(shown()).toBe(true);
      await unhover(one);
      await advance(gap);
      await hover(two);
      await advance(0);
      expect(second()?.hidden).toBe(false);
    },
  );

  it("past the skip window the next trigger waits for the full delay again", async () => {
    const host = await pair();
    const [one, two] = [trigger(host, "One"), trigger(host, "Two")];
    await hover(one);
    await advance(300);
    await unhover(one);
    await advance(400);
    await hover(two);
    await advance(299);
    expect(second()?.hidden).toBe(true);
    await advance(1);
    expect(second()?.hidden).toBe(false);
  });

  it("keyboard focus shows it at once and links it by aria-describedby (Gherkin)", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await focus(button);
    expect(shown()).toBe(true);
    expect(within(document.body).getByRole("tooltip")).toBe(tip());
    expect(button.getAttribute("aria-describedby")).toBe(tip().id);
  });

  it("a pointer focus (not :focus-visible) does not show it at once; the hover delay applies", async () => {
    const host = await saveAs();
    const button = trigger(host);
    const matches = button.matches.bind(button);
    vi.spyOn(button, "matches").mockImplementation((s) => s !== ":focus-visible" && matches(s));
    await hover(button);
    await focus(button);
    expect(shown()).toBe(false);
    await advance(300);
    expect(shown()).toBe(true);
    // Opened by the pointer, not pinned by focus: leaving hides it after the grace.
    await unhover(button);
    await advance(100);
    expect(shown()).toBe(false);
  });

  it("an engine without :focus-visible treats every focus as keyboard focus", async () => {
    const host = await saveAs();
    const button = trigger(host);
    const matches = button.matches.bind(button);
    vi.spyOn(button, "matches").mockImplementation((s) => {
      if (s === ":focus-visible") throw new SyntaxError("unsupported selector");
      return matches(s);
    });
    await focus(button);
    expect(shown()).toBe(true);
  });

  it("Esc dismisses it while focus remains on the trigger (Gherkin), and stops there", async () => {
    const onHostKey = vi.fn();
    const host = await saveAs();
    // The host's own Esc handler (a menu, a dialog) listens on an ancestor of the trigger.
    host.addEventListener("keydown", (e) => onHostKey(e.key));
    const button = trigger(host);
    await focus(button);
    await press(button, "Escape");
    expect(shown()).toBe(false);
    expect(document.activeElement).toBe(button);
    expect(onHostKey).not.toHaveBeenCalled();
    // A second Esc reaches the host (conventions 32).
    await press(button, "Escape");
    expect(onHostKey).toHaveBeenCalledWith("Escape");
  });

  it("a press on a gated trigger keeps its reason echo up (G-T2.3: a press re-shows why)", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await focus(button);
    expect(shown()).toBe(true);
    await act(async () => {
      fireEvent.pointerDown(button);
    });
    await advance(1000);
    expect(shown()).toBe(true);
  });

  it("never shows while its trigger's popup is open, however the pointer or focus returns", async () => {
    const host = await saveAs();
    const button = trigger(host);
    button.setAttribute("aria-expanded", "true");
    await hover(button);
    await advance(1000);
    expect(shown()).toBe(false);
    await unhover(button);
    await hover(button);
    await advance(1000);
    expect(shown()).toBe(false);
    await focus(button);
    expect(shown()).toBe(false);
    button.setAttribute("aria-expanded", "false");
    await unhover(button);
    await hover(button);
    await advance(300);
    expect(shown()).toBe(true);
  });

  it("an Esc while its trigger's popup is open hides the echo and passes on to the popup", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await hover(button);
    await advance(300);
    expect(shown()).toBe(true);
    button.setAttribute("aria-expanded", "true");
    const reached = vi.fn((event: KeyboardEvent) => event.defaultPrevented);
    document.addEventListener("keydown", reached);
    try {
      await press(document.body, "Escape");
    } finally {
      document.removeEventListener("keydown", reached);
    }
    expect(shown()).toBe(false);
    expect(reached).toHaveBeenCalledTimes(1);
    expect(reached).toHaveReturnedWith(false);
  });

  it("Esc also hides a hover-opened tooltip; it stays hidden until the pointer leaves and returns", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await hover(button);
    await advance(300);
    await press(document.body, "Escape");
    expect(shown()).toBe(false);
    await advance(1000);
    expect(shown()).toBe(false);
    await unhover(button);
    await hover(button);
    await advance(300);
    expect(shown()).toBe(true);
  });

  it("other keys pass through untouched", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await focus(button);
    await press(button, "Enter");
    expect(shown()).toBe(true);
  });

  it("hides on blur", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await focus(button);
    await act(async () => button.blur());
    expect(shown()).toBe(false);
  });

  it("stays on blur while the pointer is still on the trigger", async () => {
    const host = await saveAs();
    const button = trigger(host);
    await hover(button);
    await advance(300);
    await focus(button);
    await act(async () => button.blur());
    expect(shown()).toBe(true);
  });

  it("composes the trigger's own handlers", async () => {
    const calls: string[] = [];
    const host = await mount(
      <Tooltip content={TEXT}>
        <button
          type="button"
          onFocus={() => calls.push("focus")}
          onBlur={() => calls.push("blur")}
          onPointerEnter={() => calls.push("enter")}
          onPointerLeave={() => calls.push("leave")}
        >
          Save as
        </button>
      </Tooltip>,
    );
    const button = trigger(host);
    await hover(button);
    await unhover(button);
    await focus(button);
    await act(async () => button.blur());
    expect(calls).toEqual(["enter", "leave", "focus", "blur"]);
  });

  it("a trigger that cannot take focus never shows it, and warns in development", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const host = await mount(
      <Tooltip content={TEXT}>
        <span>Static</span>
      </Tooltip>,
    );
    const fixed = within(host).getByText("Static");
    await hover(fixed);
    await unhover(fixed);
    await hover(fixed);
    await advance(1000);
    expect(shown()).toBe(false);
    // Once per instance, not on every hover.
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("cannot take focus"));
    const disabled = await mount(
      <Tooltip content={TEXT}>
        <button type="button" disabled>
          Off
        </button>
      </Tooltip>,
    );
    await hover(trigger(disabled, "Off"));
    await advance(1000);
    expect(document.querySelectorAll(".cv-tooltip")[1]).toHaveProperty("hidden", true);
    const inert = await mount(
      <div {...{ inert: "" }}>
        <Tooltip content={TEXT}>
          <button type="button">Inert</button>
        </Tooltip>
      </div>,
    );
    await hover(inert.querySelector("button") as HTMLButtonElement);
    await advance(1000);
    expect(document.querySelectorAll(".cv-tooltip")[2]).toHaveProperty("hidden", true);
  });

  it("a roving tabindex=-1 item can take focus: it opens on hover, with no warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const host = await mount(
      <div role="toolbar" aria-label="Drawing tools">
        <button type="button" tabIndex={0}>
          Line
        </button>
        <Tooltip content="Draws a horizontal ray.">
          <button type="button" tabIndex={-1}>
            Ray
          </button>
        </Tooltip>
      </div>,
    );
    await hover(trigger(host, "Ray"));
    await advance(300);
    expect(shown()).toBe(true);
    expect(warn).not.toHaveBeenCalled();
  });

  it.each([
    ["a link with href", <a href="#x">Docs</a>],
    ["a span with tabindex", <span tabIndex={-1}>Cell</span>],
    [
      "contenteditable",
      <div contentEditable suppressContentEditableWarning>
        Note
      </div>,
    ],
  ])("%s counts as focusable", async (_label, element) => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const host = await mount(<Tooltip content={TEXT}>{element}</Tooltip>);
    await hover(host.firstElementChild as Element);
    await advance(300);
    expect(shown()).toBe(true);
    expect(warn).not.toHaveBeenCalled();
  });

  it("admits no triggerOnFocus={false} and no rich content at the type level", () => {
    const children = <Button>a</Button>;
    // @ts-expect-error keyboard parity: focus always shows the tooltip
    const noFocus: TooltipProps = { content: "x", triggerOnFocus: false, children };
    // @ts-expect-error text only (H10): a link or a control needs CMP-017 Popover
    const rich: TooltipProps = { content: <a href="#x">x</a>, children };
    expect([noFocus, rich]).toHaveLength(2);
  });

  it("side sets the preferred side; className joins", async () => {
    await saveAs({ side: "right", className: "extra" });
    expect(tip()).toHaveAttribute("data-side", "right");
    expect(tip()).toHaveClass("cv-tooltip", "extra");
  });

  it("adds no document or window listener while closed, and removes every one it adds on close", async () => {
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const winAdd = vi.spyOn(window, "addEventListener");
    const winRemove = vi.spyOn(window, "removeEventListener");
    const host = await saveAs();
    const button = trigger(host);
    await hover(button);
    await unhover(button);
    await advance(1000);
    expect(docAdd).not.toHaveBeenCalled();
    expect(ours(winAdd.mock.calls)).toEqual([]);

    await focus(button);
    expect(shown()).toBe(true);
    expect(docAdd).toHaveBeenCalledWith("keydown", expect.any(Function), true);
    expect(winAdd).toHaveBeenCalledWith("scroll", expect.any(Function));
    await act(async () => button.blur());
    expect(shown()).toBe(false);
    for (const [type, listener, options] of docAdd.mock.calls)
      expect(docRemove).toHaveBeenCalledWith(type, listener, options);
    for (const [type, listener] of ours(winAdd.mock.calls))
      expect(removed(winRemove.mock.calls, type, listener)).toBe(true);
  });

  it("unmounting while open removes its listeners; unmounting during the delay never shows", async () => {
    const docAdd = vi.spyOn(document, "addEventListener");
    const docRemove = vi.spyOn(document, "removeEventListener");
    const winAdd = vi.spyOn(window, "addEventListener");
    const winRemove = vi.spyOn(window, "removeEventListener");
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <Tooltip content={TEXT}>
          <Button>Save as</Button>
        </Tooltip>,
      ),
    );
    await focus(trigger(host));
    expect(docAdd).toHaveBeenCalled();
    await act(async () => root.unmount());
    for (const [type, listener, options] of docAdd.mock.calls)
      expect(docRemove).toHaveBeenCalledWith(type, listener, options);
    for (const [type, listener] of ours(winAdd.mock.calls))
      expect(removed(winRemove.mock.calls, type, listener)).toBe(true);

    const setOpen = vi.spyOn(console, "error");
    const again = createRoot(host);
    await act(async () =>
      again.render(
        <Tooltip content={TEXT}>
          <Button>Save as</Button>
        </Tooltip>,
      ),
    );
    await hover(trigger(host));
    await act(async () => again.unmount());
    await advance(1000);
    expect(setOpen).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
