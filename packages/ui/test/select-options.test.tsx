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
/** The presentational row that carries the look (data-kind, data-active) and the pointer handlers. */
const rowOf = (option: HTMLElement): HTMLElement =>
  option.closest<HTMLElement>(".cv-select__row") as HTMLElement;
const options = (host: HTMLElement): HTMLElement[] => within(host).queryAllByRole("option");
const activeLabel = (host: HTMLElement): string | undefined => {
  const id = box(host).getAttribute("aria-activedescendant");
  return id === null
    ? undefined
    : document.getElementById(id)?.querySelector(".cv-select__label")?.textContent;
};
// The elements `scrollIntoView` was called on: the whole row (label, reason, ring), never the inner option line.
const scrollTargets = (): unknown[] => vi.mocked(Element.prototype.scrollIntoView).mock.contexts;
const activeRow = (host: HTMLElement): Element | null | undefined => {
  const id = box(host).getAttribute("aria-activedescendant");
  return id === null ? undefined : document.getElementById(id)?.closest(".cv-select__row");
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
  // The type-ahead window reads `performance.now`: only that clock is faked, so no test depends on real time.
  vi.useFakeTimers({ toFake: ["performance"] });
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
    // Ruling (d): the name is the label alone; the reason is a hidden sibling that only describes the option.
    expect(charlie).toHaveAccessibleName("Charlie");
    expect(delta).toHaveAccessibleName("Delta");
    expect(rowOf(charlie)).toHaveAttribute("data-kind", "unavailable");
    expect(rowOf(delta)).toHaveAttribute("data-kind", "locked");
    // The lock shows on the T2 option only.
    expect(delta.querySelector(".cv-select__optlock")).not.toBeNull();
    expect(charlie.querySelector(".cv-select__optlock")).toBeNull();
    expect(rowOf(bravo).querySelector(".cv-select__reason")).toBeNull();
    // The reason is outside the option and hidden from the tree, so the option owns no extra text.
    expect(charlie).not.toHaveTextContent("Not on Bybit");
    expect(rowOf(charlie).querySelector(".cv-select__reason")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
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

  it("announce the reason on a press, never on arrival, and again on every repeat press", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    key(host, "ArrowDown"); // arrives on Charlie: the description is read, the status is silent
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent("");
    expect(options(host)[2]).toHaveAccessibleDescription("Not on Bybit linear.");
    key(host, "Enter");
    const first = status.firstElementChild;
    expect(first).toHaveTextContent("Not on Bybit linear.");
    key(host, "Enter"); // the same text again: a new node, so a polite region speaks it again
    const second = status.firstElementChild;
    expect(second).toHaveTextContent("Not on Bybit linear.");
    expect(second).not.toBe(first);
    // Arrowing away and back stays silent.
    key(host, "ArrowDown");
    key(host, "ArrowUp");
    expect(activeLabel(host)).toBe("Charlie");
    expect(status).toHaveTextContent("");
    // Every other way of moving clears it too.
    key(host, "Enter");
    expect(status).toHaveTextContent("Not on Bybit linear.");
    key(host, "End");
    key(host, "Home");
    key(host, "ArrowDown");
    expect(status).toHaveTextContent("");
  });

  it("Tab leaving the list on a reason option closes it without choosing or announcing", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    key(host, "Enter");
    key(host, "ArrowDown");
    key(host, "Tab");
    expect(within(host).getByRole("status")).toHaveTextContent("");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(onChange).not.toHaveBeenCalled();
    // On an ordinary option Tab still chooses.
    key(host, "ArrowDown");
    key(host, "ArrowDown");
    key(host, "ArrowDown");
    key(host, "ArrowDown"); // opens, then Charlie, Delta, Charlie two
    key(host, "Tab");
    expect(onChange).toHaveBeenCalledWith("e");
  });

  it("a press with no prior pointer move (a tap, an AT click) activates the row and shows its reason", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    const delta = options(host)[3] as HTMLElement;
    act(() => delta.click());
    expect(activeLabel(host)).toBe("Delta");
    expect(within(host).getByRole("status")).toHaveTextContent("Owner only.");
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
  });

  it("the listbox owns only presentational rows, each holding one option; the reason is not in the option", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    const list = within(host).getByRole("listbox");
    for (const row of Array.from(list.children)) {
      expect(row).toHaveAttribute("role", "presentation");
      expect(row.querySelectorAll('[role="option"]')).toHaveLength(1);
    }
    // name = label, description = reason, for every reason kind
    const [, , charlie, delta] = options(host) as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ];
    expect(charlie).toHaveAccessibleName("Charlie");
    expect(charlie).toHaveAccessibleDescription("Not on Bybit linear.");
    expect(delta).toHaveAccessibleName("Delta");
    expect(delta).toHaveAccessibleDescription("Owner only.");
  });

  it("a press or a move on the reason line acts as one on its option (the wrapper owns the pointer)", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    key(host, "Enter");
    const delta = options(host)[3] as HTMLElement;
    const reasonLine = rowOf(delta).querySelector(".cv-select__reason") as HTMLElement;
    await userEvent.hover(reasonLine);
    expect(activeLabel(host)).toBe("Delta");
    expect(within(host).getByRole("status")).toHaveTextContent("");
    await userEvent.click(reasonLine);
    expect(within(host).getByRole("status")).toHaveTextContent("Owner only.");
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
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
    expect(rowOf(b)).toHaveAttribute("data-kind", "unavailable");
    expect(rowOf(c)).toHaveAttribute("data-kind", "locked");
    expect(c).toHaveAccessibleDescription("Why C");
    expect(rowOf(d)).toHaveAttribute("data-kind", "disabled");
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
    key(host, "z"); // "cccz" matches nothing
    expect(activeLabel(host)).toBe("Charlie");
    // The window really passed: the string restarts, so "a" alone reaches Alpha ("ccca" never would).
    vi.advanceTimersByTime(TYPE_AHEAD_MS + 1);
    key(host, "a");
    expect(activeLabel(host)).toBe("Alpha");
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
    expect(scrollTargets()).toEqual([activeRow(host)]);
  });

  it("a Space continues a typed string while the longer string still matches", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "s");
    expect(key(host, "u")).toBe(false);
    type(host, "b-account");
    expect(key(host, " ")).toBe(false);
    key(host, "2");
    expect(activeLabel(host)).toBe("Sub-account 2");
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
  });

  it("a Space at exactly the window edge still continues the string; one ms later it does not", async () => {
    const host = await mount(<Host value="a" />);
    type(host, "sub-account");
    vi.advanceTimersByTime(TYPE_AHEAD_MS);
    expect(key(host, " ")).toBe(false);
    key(host, "2");
    expect(activeLabel(host)).toBe("Sub-account 2");
    // One ms past the window the Space is a lone Space: it chooses, and the string is gone.
    vi.advanceTimersByTime(TYPE_AHEAD_MS + 1);
    key(host, " ");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
    expect(box(host)).toHaveTextContent("Sub-account 2");
  });

  it("a Space after a letter never scrolls: it is always consumed and does its own job", async () => {
    const onChange = fn();
    const tif = [
      { value: "gtc", label: "GTC" },
      { value: "ioc", label: "IOC" },
      { value: "fok", label: "FOK", unavailableReason: "Market orders are always IOC" },
    ];
    // Closed, "g" opens on GTC; the Space ("g " matches nothing) then chooses it.
    const closed = await mount(<Host options={tif} value="ioc" onChange={onChange} />);
    key(closed, "g");
    expect(box(closed)).toHaveAttribute("aria-expanded", "true");
    expect(key(closed, " ")).toBe(false);
    expect(onChange).toHaveBeenLastCalledWith("gtc");
    expect(box(closed)).toHaveAttribute("aria-expanded", "false");
    // Closed, "x" matches nothing and stays closed; the Space opens it instead of being left to the page.
    const none = await mount(<Host options={tif} value="gtc" />);
    expect(key(none, "x")).toBe(true);
    expect(box(none)).toHaveAttribute("aria-expanded", "false");
    expect(key(none, " ")).toBe(false);
    expect(box(none)).toHaveAttribute("aria-expanded", "true");
    // Open, "i" then Space chooses IOC.
    const open = await mount(<Host options={tif} value="gtc" onChange={onChange} />);
    key(open, "Enter");
    key(open, "i");
    expect(activeLabel(open)).toBe("IOC");
    expect(key(open, " ")).toBe(false);
    expect(onChange).toHaveBeenLastCalledWith("ioc");
    expect(box(open)).toHaveAttribute("aria-expanded", "false");
  });

  it("a plain-disabled option is not activated by hover; a keyboard move scrolls, a hover does not", async () => {
    const host = await mount(<Host value="a" />);
    key(host, "Enter");
    const [, bravo, charlie] = options(host) as [HTMLElement, HTMLElement, HTMLElement];
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    await userEvent.hover(bravo);
    expect(activeLabel(host)).toBe("Alpha");
    await userEvent.hover(charlie);
    expect(activeLabel(host)).toBe("Charlie");
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
    key(host, "ArrowDown");
    expect(activeLabel(host)).toBe("Delta");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    expect(scrollTargets()).toEqual([activeRow(host)]);
  });

  it("ignores Ctrl, Alt and Meta chords and Shift+Space", async () => {
    const host = await mount(<Host value="a" />);
    for (const init of [{ ctrlKey: true }, { altKey: true }, { metaKey: true }]) {
      expect(key(host, "c", init)).toBe(true);
    }
    for (const init of [{ ctrlKey: true }, { metaKey: true }, { altKey: true, shiftKey: true }]) {
      expect(key(host, "ArrowDown", init)).toBe(true);
    }
    expect(key(host, "ArrowLeft", { altKey: true })).toBe(true);
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

describe("Select Alt chords", () => {
  it("Alt+Down opens without moving the active option; open, it is consumed and changes nothing", async () => {
    const host = await mount(<Host value="f" />);
    expect(key(host, "ArrowDown", { altKey: true })).toBe(false);
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(activeLabel(host)).toBe("Sub-account 1");
    expect(key(host, "ArrowDown", { altKey: true })).toBe(false); // consumed: the page does not scroll
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(activeLabel(host)).toBe("Sub-account 1");
  });

  it("Alt+Up chooses the active option and closes; closed, it is left to the host", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    expect(key(host, "ArrowUp", { altKey: true })).toBe(true);
    key(host, "Enter");
    key(host, "ArrowDown");
    key(host, "ArrowDown");
    key(host, "ArrowDown"); // Charlie, Delta, Charlie two
    expect(key(host, "ArrowUp", { altKey: true })).toBe(false);
    expect(onChange).toHaveBeenCalledWith("e");
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
  });

  it("Alt+Up on an unavailable option re-shows its reason and keeps the list open", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    key(host, "Enter");
    key(host, "ArrowDown");
    key(host, "ArrowUp", { altKey: true });
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host)).toHaveAttribute("aria-expanded", "true");
    expect(within(host).getByRole("status")).toHaveTextContent("Not on Bybit linear.");
  });

  it("a gated select refuses Alt+Down but leaves Alt+Up alone", async () => {
    const host = await mount(<Host value="a" disabledReason="Owner only" />);
    expect(key(host, "ArrowUp", { altKey: true })).toBe(true);
    expect(key(host, "ArrowDown", { altKey: true })).toBe(false);
    expect(box(host)).toHaveAttribute("aria-expanded", "false");
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
