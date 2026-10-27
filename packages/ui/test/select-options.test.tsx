// @vitest-environment jsdom
import { useState, type JSX } from "react";
import { act } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { Select, type SelectProps } from "../src/components/index.js";
import { extendTyped, matchIndex, TYPE_AHEAD_MS } from "../src/components/internal/listNav.js";
import { mount } from "./theme/mount.js";

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo", disabled: true },
  { value: "c", label: "Charlie", unavailableReason: "Not on Bybit linear." },
  { value: "d", label: "Delta", disabledReason: "Owner only." },
  { value: "e", label: "Charlie two" },
  { value: "f", label: "Sub-account 1" },
  { value: "g", label: "Sub-account 2" },
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
const options = (host: HTMLElement): HTMLElement[] => within(host).queryAllByRole("option");
const activeLabel = (host: HTMLElement): string | undefined => {
  const id = box(host).getAttribute("aria-activedescendant");
  return id === null
    ? undefined
    : document.getElementById(id)?.querySelector(".cv-select__label")?.textContent;
};
const key = (host: HTMLElement, k: string, init: object = {}): boolean => {
  let result = true;
  act(() => {
    result = box(host).dispatchEvent(
      new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }),
    );
  });
  return result;
};
const type = (host: HTMLElement, text: string): void => {
  for (const c of text) key(host, c);
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Select unavailable and T2 options", () => {
  it("are reachable by the arrows, aria-disabled, and described by their reason line", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    key(host, "ArrowDown"); // Bravo is plain disabled: skipped
    expect(activeLabel(host)).toBe("Charlie");
    key(host, "ArrowDown");
    expect(activeLabel(host)).toBe("Delta");
    const [, bravo, charlie, delta] = options(host) as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ];
    expect(bravo).toHaveAttribute("aria-disabled", "true");
    expect(bravo).not.toHaveAttribute("aria-describedby");
    for (const [option, reason] of [
      [charlie, "Not on Bybit linear."],
      [delta, "Owner only."],
    ] as const) {
      expect(option).toHaveAttribute("aria-disabled", "true");
      expect(option).toHaveAccessibleDescription(reason);
    }
    // The name is the option's content, so the reason line (visible text) is part of it (axe label-in-name).
    expect(charlie).toHaveAccessibleName("Charlie Not on Bybit linear.");
    expect(delta).toHaveAccessibleName("Delta Owner only.");
    expect(charlie).toHaveAttribute("data-kind", "unavailable");
    expect(delta).toHaveAttribute("data-kind", "locked");
    // The lock shows on the T2 option only.
    expect(delta.querySelector(".cv-select__optlock")).not.toBeNull();
    expect(charlie.querySelector(".cv-select__optlock")).toBeNull();
    expect(bravo.querySelector(".cv-select__reason")).toBeNull();
  });

  it("are never chosen by Enter, Space or Tab; Enter re-shows the reason and the list stays open", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    key(host, "Enter");
    key(host, "ArrowDown");
    expect(within(host).getByRole("status")).toHaveTextContent("");
    expect(key(host, "Enter")).toBe(false);
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(within(host).getByRole("status")).toHaveTextContent("Not on Bybit linear.");
    // Moving on clears it; Space is refused too.
    key(host, "ArrowDown");
    expect(within(host).getByRole("status")).toHaveTextContent("");
    key(host, " ");
    expect(within(host).getByRole("status")).toHaveTextContent("Owner only.");
    key(host, "Tab");
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveTextContent("Alpha");
  });

  it("are never chosen by a pointer click, which re-shows the reason; a plain disabled click says nothing", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    key(host, "Enter");
    const [, bravo, charlie] = options(host) as [HTMLElement, HTMLElement, HTMLElement];
    await userEvent.click(bravo);
    expect(within(host).getByRole("status")).toHaveTextContent("");
    await userEvent.hover(charlie);
    await userEvent.click(charlie);
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(within(host).getByRole("status")).toHaveTextContent("Not on Bybit linear.");
    // A reopen starts silent.
    key(host, "Escape");
    key(host, "Enter");
    expect(within(host).getByRole("status")).toHaveTextContent("");
  });

  it("a reason wins over disabled, T2 wins over unavailable, a blank reason is no reason", async () => {
    const host = await mount(
      <Host
        value="a"
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B", disabled: true, unavailableReason: "Why B" },
          { value: "c", label: "C", unavailableReason: "x", disabledReason: "Why C" },
          { value: "d", label: "D", disabled: true, disabledReason: "   " },
        ]}
      />,
    );
    key(host, "Enter");
    const [, b, c, d] = options(host) as [HTMLElement, HTMLElement, HTMLElement, HTMLElement];
    expect(b).toHaveAttribute("data-kind", "unavailable");
    expect(c).toHaveAttribute("data-kind", "locked");
    expect(c).toHaveAccessibleDescription("Why C");
    expect(d).toHaveAttribute("data-kind", "disabled");
    expect(d).not.toHaveAttribute("aria-describedby");
  });

  it("without any reason there is no status node", async () => {
    const host = await mount(<Host options={[{ value: "a", label: "A" }]} value="a" />);
    expect(within(host).queryByRole("status")).toBeNull();
  });
});

describe("Select type-ahead", () => {
  it("opens a closed list on the next match and never chooses, even an unavailable option", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    expect(key(host, "c")).toBe(false);
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(activeLabel(host)).toBe("Charlie");
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveTextContent("Alpha");
  });

  it("moves the active option while open, case-insensitively (Shift allowed)", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    key(host, "S", { shiftKey: true });
    expect(activeLabel(host)).toBe("Sub-account 1");
    expect(box(host)).toHaveAttribute("aria-activedescendant", options(host)[5]?.id);
  });

  it("accumulates within the window, restarts after it, and an injected clock drives it", async () => {
    vi.useFakeTimers();
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    type(host, "sub-account 2".slice(0, 4)); // "sub-"
    expect(activeLabel(host)).toBe("Sub-account 1");
    vi.advanceTimersByTime(TYPE_AHEAD_MS - 1);
    type(host, "a");
    key(host, "c");
    expect(activeLabel(host)).toBe("Sub-account 1");
    // Past the window the string restarts: "a" alone goes to Alpha again.
    vi.advanceTimersByTime(TYPE_AHEAD_MS + 1);
    key(host, "d");
    expect(activeLabel(host)).toBe("Delta");
  });

  it("a repeated letter cycles through the matches and wraps; no match keeps the active option", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    key(host, "c");
    expect(activeLabel(host)).toBe("Charlie");
    key(host, "c");
    expect(activeLabel(host)).toBe("Charlie two");
    key(host, "c");
    expect(activeLabel(host)).toBe("Charlie");
    vi.useFakeTimers();
    vi.advanceTimersByTime(TYPE_AHEAD_MS * 2);
    key(host, "z");
    expect(activeLabel(host)).toBe("Charlie");
  });

  it("a closed list stays closed when nothing matches; plain disabled never matches", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "b"); // Bravo is disabled
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(key(host, "z")).toBe(true); // not consumed
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
  });

  it("scrolls the matched option into view", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    key(host, "s");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("a Space continues a typed string; on its own it is not type-ahead", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "s");
    type(host, "ub-account ");
    key(host, "2");
    expect(activeLabel(host)).toBe("Sub-account 2");
  });

  it("ignores Ctrl, Alt and Meta chords and Shift+Space", async () => {
    const host = await mount(<Host value="a" />);
    for (const init of [{ ctrlKey: true }, { altKey: true }, { metaKey: true }]) {
      expect(key(host, "c", init)).toBe(true);
    }
    expect(key(host, " ", { shiftKey: true })).toBe(true);
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
  });

  it("an open list leaves a non-printable key it does not own to the host", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    expect(key(host, "F2")).toBe(true);
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
  });

  it("a gated or disabled select refuses typing and never opens", async () => {
    const gated = await mount(<Host value="a" disabledReason="Owner only" />);
    expect(key(gated, "c")).toBe(false);
    expect(box(gated)).toHaveAttribute("aria-expanded", "false");
    const off = await mount(<Host value="a" disabled />);
    expect(key(off, "c")).toBe(true);
    expect(box(off)).toHaveAttribute("aria-expanded", "false");
  });
});

describe("listNav type-ahead", () => {
  const items = ["Alpha", "Bravo", "alpine", "Delta"];
  const label = (s: string): string => s;
  const none = (): boolean => false;

  it("extendTyped appends inside the window and restarts outside it", () => {
    const first = extendTyped({ text: "", at: 0 }, "a", 1000);
    expect(first).toEqual({ text: "a", at: 1000 });
    expect(extendTyped(first, "l", 1000 + TYPE_AHEAD_MS)).toEqual({ text: "al", at: 1500 });
    expect(extendTyped(first, "b", 1000 + TYPE_AHEAD_MS + 1).text).toBe("b");
  });

  it("matchIndex: prefix, case-insensitive, one letter cycles with wrap, a string stays on a match", () => {
    expect(matchIndex(items, -1, "AL", label, none)).toBe(0);
    expect(matchIndex(items, 0, "al", label, none)).toBe(0);
    expect(matchIndex(items, 0, "a", label, none)).toBe(2);
    expect(matchIndex(items, 2, "a", label, none)).toBe(0);
    expect(matchIndex(items, 0, "aa", label, none)).toBe(2);
    expect(matchIndex(items, 0, "x", label, none)).toBe(-1);
    expect(matchIndex(items, 0, "b", label, (s) => s === "Bravo")).toBe(-1);
    expect(matchIndex([], 0, "a", label, none)).toBe(-1);
  });
});
