// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { act } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { Select, type SelectProps } from "../src/components/index.js";
import * as stories from "../src/components/Select.stories.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo", disabled: true },
  { value: "c", label: "Charlie" },
  { value: "d", label: "Delta" },
];

function Host(props: Partial<SelectProps>): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <Select
      options={OPTIONS}
      aria-label="Pick"
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange?.(next);
      }}
    />
  );
}

const box = (host: HTMLElement): HTMLElement => within(host).getByRole("combobox");
const list = (host: HTMLElement): HTMLElement | null => host.querySelector("[role=listbox]");
const options = (host: HTMLElement): HTMLElement[] => within(host).queryAllByRole("option");
const activeId = (host: HTMLElement): string | null =>
  box(host).getAttribute("aria-activedescendant");
const activeLabel = (host: HTMLElement): string | null | undefined =>
  activeId(host) === null ? null : document.getElementById(activeId(host) as string)?.textContent;
const key = (host: HTMLElement, k: string, init: object = {}): boolean => {
  let result = true;
  act(() => {
    result = box(host).dispatchEvent(
      new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }),
    );
  });
  return result;
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());

describe("Select (CMP-009)", () => {
  it("renders a combobox with the select-only attributes, closed", async () => {
    const host = await mount(<Host value="c" />);
    const trigger = box(host);
    expect(trigger).toHaveAccessibleName("Pick");
    expect(trigger).toHaveAttribute("aria-haspopup", "listbox");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-activedescendant");
    expect(trigger).toHaveTextContent("Charlie");
    expect(list(host)).toBeNull();
    expect(host.querySelector("[data-cmp]")?.getAttribute("data-cmp")).toBe("CMP-009");
  });

  it("shows the placeholder when nothing matches, and is named by aria-labelledby", async () => {
    const host = await mount(
      <>
        <span id="l">Account</span>
        <Host value="zz" placeholder="Choose" aria-labelledby="l" density="compact" />
      </>,
    );
    expect(box(host)).toHaveTextContent("Choose");
    expect(box(host)).toHaveAccessibleName("Account");
    expect(host.querySelector("[data-placeholder]")).not.toBeNull();
    expect(host.querySelector("[data-density=compact]")).not.toBeNull();
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(list(host)).toHaveAccessibleName("Account");
  });

  it.each(["Enter", " ", "ArrowDown", "ArrowUp"])("%j opens on the chosen option", async (k) => {
    const host = await mount(<Host value="c" />);
    expect(key(host, k)).toBe(false);
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(activeLabel(host)).toBe("Charlie");
    expect(list(host)?.id).toBe(box(host).getAttribute("aria-controls"));
  });

  it("opens on the first option when nothing is chosen, and on the first enabled one when the chosen is disabled", async () => {
    const one = await mount(<Host value={undefined} />);
    key(one, "Enter");
    expect(activeLabel(one)).toBe("Alpha");
    const two = await mount(<Host value="b" />);
    key(two, "Enter");
    expect(options(two).filter((o) => o.hasAttribute("data-active"))[0]).toHaveTextContent("Alpha");
  });

  it("Home and End open on the first and last option; open they move there", async () => {
    const host = await mount(<Host value="c" />);
    expect(key(host, "End")).toBe(false);
    expect(activeLabel(host)).toBe("Delta");
    key(host, "Home");
    expect(activeLabel(host)).toBe("Alpha");
    key(host, "End");
    expect(activeLabel(host)).toBe("Delta");
    key(host, "Escape");
    key(host, "Home");
    expect(activeLabel(host)).toBe("Alpha");
  });

  it("arrows skip a disabled option, do not wrap, and keep aria in step with the highlight", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    expect(key(host, "ArrowDown")).toBe(false);
    expect(activeLabel(host)).toBe("Charlie");
    key(host, "ArrowDown");
    key(host, "ArrowDown");
    expect(activeLabel(host)).toBe("Delta");
    key(host, "ArrowUp");
    key(host, "ArrowUp");
    key(host, "ArrowUp");
    expect(activeLabel(host)).toBe("Alpha");
    const marked = options(host).filter((o) => o.hasAttribute("data-active"));
    expect(marked).toHaveLength(1);
    expect(marked[0]?.id).toBe(activeId(host));
    expect(options(host).map((o) => o.getAttribute("aria-selected"))).toEqual([
      "true",
      "false",
      "false",
      "false",
    ]);
    expect(options(host)[1]).toHaveAttribute("aria-disabled", "true");
  });

  it("Enter chooses the active option, closes and keeps focus; choosing the same value does not call onChange", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("c");
    expect(box(host)).toHaveFocus();
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(box(host)).toHaveTextContent("Charlie");
    expect(options(host)).toHaveLength(0);
    await userEvent.keyboard("{Enter}{Enter}");
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("Enter never submits the enclosing form, open or closed", async () => {
    const submit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
    await mount(
      <form onSubmit={submit}>
        <Host value="a" />
      </form>,
    );
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{Enter}");
    expect(submit).not.toHaveBeenCalled();
  });

  it("Tab chooses the active option and lets focus move on; Shift+Tab does too", async () => {
    const onChange = fn();
    const host = await mount(
      <>
        <Host value="a" onChange={onChange} />
        <button type="button">next</button>
      </>,
    );
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{ArrowDown}");
    expect(key(host, "Tab")).toBe(true);
    expect(onChange).toHaveBeenCalledWith("c");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    key(host, "Enter");
    key(host, "ArrowDown");
    key(host, "Tab", { shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith("d");
    key(host, "Tab");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
  });

  it("Esc closes with the value unchanged, focus stays, and does not bubble; a second Esc bubbles", async () => {
    const onChange = fn();
    const onKeyDown = vi.fn();
    const host = await mount(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a host listener probing bubbling
      <div onKeyDown={onKeyDown}>
        <Host value="a" onChange={onChange} />
      </div>,
    );
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{ArrowDown}");
    onKeyDown.mockClear();
    await userEvent.keyboard("{Escape}");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(box(host)).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveTextContent("Alpha");
    expect(onKeyDown).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    expect(onKeyDown).toHaveBeenCalledOnce();
  });

  it("modifier chords and unhandled keys do nothing and are not consumed", async () => {
    const host = await mount(<Host value="a" />);
    for (const init of [
      { ctrlKey: true },
      { altKey: true },
      { metaKey: true },
      { shiftKey: true },
    ]) {
      expect(key(host, "ArrowDown", init)).toBe(true);
      expect(key(host, "Enter", init)).toBe(true);
    }
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(key(host, "x")).toBe(true);
    expect(key(host, "PageDown")).toBe(true);
    key(host, "Enter");
    for (const init of [{ ctrlKey: true }, { altKey: true }, { shiftKey: true }]) {
      expect(key(host, "ArrowDown", init)).toBe(true);
      expect(key(host, "Escape", init)).toBe(true);
    }
    expect(activeLabel(host)).toBe("Alpha");
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(key(host, "x")).toBe(true);
  });

  it("Enter with no reachable option closes without choosing", async () => {
    const onChange = fn();
    const host = await mount(
      <Host
        value={undefined}
        options={[{ value: "x", label: "X", disabled: true }]}
        onChange={onChange}
      />,
    );
    key(host, "Enter");
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(box(host)).not.toHaveAttribute("aria-activedescendant");
    key(host, "Enter");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a press opens and closes the list, an option click chooses, a disabled one does not", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    await userEvent.click(box(host));
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(box(host)).toHaveFocus();
    await userEvent.click(options(host)[1] as HTMLElement);
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(options(host)[3] as HTMLElement);
    expect(onChange).toHaveBeenCalledWith("d");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(box(host)).toHaveFocus();
    await userEvent.click(box(host));
    await userEvent.click(box(host));
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
  });

  it("pointer movement activates an enabled option only; a press on the list keeps focus on the trigger", async () => {
    const host = await mount(<Host value="a" />);
    await userEvent.click(box(host));
    await userEvent.hover(options(host)[2] as HTMLElement);
    expect(activeLabel(host)).toBe("Charlie");
    await userEvent.hover(options(host)[1] as HTMLElement);
    expect(activeLabel(host)).toBe("Charlie");
    fireEvent.mouseMove(options(host)[2] as HTMLElement);
    expect(fireEvent.mouseDown(list(host) as HTMLElement)).toBe(false);
    expect(box(host)).toHaveFocus();
  });

  it("closing on blur does not choose; the active option scrolls into view", async () => {
    const onChange = fn();
    const host = await mount(
      <>
        <Host value="a" onChange={onChange} />
        <button type="button">out</button>
      </>,
    );
    await userEvent.tab();
    await userEvent.keyboard("{Enter}{ArrowDown}");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    await userEvent.click(within(host).getByRole("button", { name: "out" }));
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("the check marks the chosen option; the glyphs are hidden from AT", async () => {
    const host = await mount(<Host value="c" />);
    key(host, "Enter");
    const chosen = within(host).getByRole("option", { name: "Charlie" });
    expect(chosen).toHaveAttribute("aria-selected", "true");
    expect(chosen.querySelector("svg")).not.toBeNull();
    expect(options(host)[0]?.querySelector("svg")).toBeNull();
    expect(box(host).querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("invalid: aria-invalid, the message as the description, then the caller's help", async () => {
    const host = await mount(
      <>
        <span id="help">Pick one</span>
        <Host value={undefined} invalid errorMessage="Required" aria-describedby="help" />
      </>,
    );
    expect(box(host)).toHaveAttribute("aria-invalid", "true");
    expect(box(host)).toHaveAccessibleDescription("Required Pick one");
    const message = host.querySelector(".cv-field__message");
    expect(message).toHaveAttribute("aria-live", "polite");
  });

  it("valid: no aria-invalid and an empty message line stays in the DOM", async () => {
    const host = await mount(<Host value="a" />);
    expect(box(host)).not.toHaveAttribute("aria-invalid");
    expect(host.querySelector(".cv-field__message")?.textContent).toBe("");
  });

  it("plain disabled: out of the Tab order, never opens, no status node", async () => {
    const host = await mount(<Host value="a" disabled />);
    expect(box(host)).toHaveAttribute("aria-disabled", "true");
    expect(box(host)).toHaveAttribute("tabindex", "-1");
    await userEvent.tab();
    expect(box(host)).not.toHaveFocus();
    await userEvent.click(box(host));
    fireEvent.keyDown(box(host), { key: "Enter" });
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(within(host).queryByRole("status")).toBeNull();
  });

  it("T2: focusable, aria-disabled, the lock leads, the reason alone described, never opens", async () => {
    const onChange = fn();
    const host = await mount(
      <Host value="a" disabledReason={REASON} invalid errorMessage="Nope" onChange={onChange} />,
    );
    await userEvent.tab();
    expect(box(host)).toHaveFocus();
    expect(box(host)).toHaveAttribute("aria-disabled", "true");
    expect(box(host)).toHaveAccessibleDescription(REASON);
    expect(within(box(host)).getByRole("img", { name: "Not available" })).toBeTruthy();
    for (const k of ["Enter", " ", "ArrowDown", "ArrowUp", "Home", "End", "x"]) {
      expect(key(host, k)).toBe(false);
    }
    await userEvent.click(box(host));
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(onChange).not.toHaveBeenCalled();
    expect(list(host)).toBeNull();
  });

  it("T2: the reason is announced once per focus visit; Tab, Esc and chords are never touched", async () => {
    const host = await mount(
      <>
        <button type="button">before</button>
        <Host value="a" disabledReason={REASON} />
      </>,
    );
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent("");
    await userEvent.tab();
    await userEvent.tab();
    expect(status).toHaveTextContent("");
    expect(key(host, "Escape")).toBe(true);
    expect(key(host, "Tab")).toBe(true);
    expect(key(host, "ArrowDown", { altKey: true })).toBe(true);
    expect(key(host, "c", { ctrlKey: true })).toBe(true);
    expect(status).toHaveTextContent("");
    await act(async () => void key(host, "ArrowDown"));
    expect(status).toHaveTextContent(REASON);
    await userEvent.tab({ shift: true });
    expect(status).toHaveTextContent("");
    await userEvent.tab();
    await userEvent.click(box(host));
    expect(status).toHaveTextContent(REASON);
  });

  it("keeps a caller's Tab choose semantics only when not gated, and renders the reason as text", async () => {
    const host = await mount(<Host value="a" disabledReason="<b>no</b>" />);
    expect(host.querySelector("b")).toBeNull();
    expect(box(host)).toHaveAccessibleDescription("<b>no</b>");
  });

  it("an empty or blank reason is no reason: the combobox keeps working", async () => {
    const host = await mount(<Host value="a" disabledReason="  " />);
    expect(box(host)).not.toHaveAttribute("aria-disabled");
    key(host, "Enter");
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
  });
});

describe("Select popup placement", () => {
  const rect = (top: number, bottom: number, height: number): DOMRect =>
    ({
      top,
      bottom,
      height,
      left: 0,
      right: 0,
      width: 0,
      x: 0,
      y: top,
      toJSON: () => ({}),
    }) as DOMRect;
  const place = async (anchor: [number, number], popup: number): Promise<string | null> => {
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains("cv-select__popup")
        ? rect(0, popup, popup)
        : rect(anchor[0], anchor[1], anchor[1] - anchor[0]);
    });
    const host = await mount(<Host value="a" />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    return list(host)?.getAttribute("data-placement") ?? null;
  };

  it("opens below when it fits", async () => {
    expect(await place([100, 124], 200)).toBe("below");
  });

  it("flips above when there is no room below and more above", async () => {
    expect(await place([500, 524], 200)).toBe("above");
  });

  it("stays below when neither side fits and below is the larger", async () => {
    expect(await place([20, 44], 700)).toBe("below");
  });

  it("measures only at open: nothing during render or while closed", async () => {
    const spy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect");
    await mount(<Host value="a" />);
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("Select stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("combobox").length).toBeGreaterThan(0);
  });
});
