// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  SymbolSearchInput,
  type FuzzyListItem,
  type SymbolSearchInputProps,
} from "../src/index.js";
import * as stories from "../src/components/SymbolSearchInput.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const row = (id: string, extra: Partial<FuzzyListItem> = {}): FuzzyListItem => ({
  id,
  label: id,
  ...extra,
});
const ROWS = ["BTCUSDT", "ETHUSDT", "ETHFIUSDT", "SOLUSDT", "XRPUSDT"].map((id) => row(id));
const LUNA = row("LUNAUSDT", {
  disabled: true,
  delisted: true,
  reason: "LUNAUSDT is not trading on Bybit.",
});
const noop = (): void => undefined;

type HostProps = Partial<SymbolSearchInputProps> & { readonly initial?: string };
/** A controlled host ranking by substring on each keystroke (the real rank is apps/web's). */
function Host({ initial = "", ...over }: HostProps): JSX.Element {
  const [value, setValue] = useState(initial);
  const q = value.trim().toUpperCase();
  const items = q === "" ? [] : ROWS.filter((r) => r.label.includes(q));
  return (
    <SymbolSearchInput value={value} onChange={setValue} onSelect={noop} items={items} {...over} />
  );
}

const page = (): ReturnType<typeof within> => within(document.body);
const input = (): HTMLElement => page().getByRole("combobox");
const status = (): HTMLElement => page().getByRole("status");
const active = (): string | null => {
  const id = input().getAttribute("aria-activedescendant");
  return id === null ? null : (document.getElementById(id)?.getAttribute("aria-label") ?? "");
};
const press = async (key: string, init: KeyboardEventInit = {}): Promise<boolean> => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  await act(async () => input().dispatchEvent(event));
  return !event.defaultPrevented;
};
const type = (text: string): Promise<void> =>
  act(async () => void fireEvent.change(input(), { target: { value: text } }));
const wait = (ms: number): Promise<void> => act(() => vi.advanceTimersByTimeAsync(ms).then(noop));

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("SymbolSearchInput (CMP-160)", () => {
  it("the APG combobox over CMP-213 in place: names, the search glyph, 32 characters; axe idle and typed", async () => {
    const host = await mount(<Host recentSymbols={[row("ETHUSDT"), LUNA]} />);
    expect(input()).toHaveAccessibleName("Search symbols");
    expect([input().getAttribute("maxlength"), input().getAttribute("aria-autocomplete")]).toEqual([
      "32",
      "list",
    ]);
    const listbox = page().getByRole("listbox", { name: "Symbols" });
    expect([input().getAttribute("aria-expanded"), input().getAttribute("aria-controls")]).toEqual([
      "true",
      listbox.id,
    ]);
    expect(host.querySelector(".cv-field__affix svg")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelectorAll('[data-cmp="CMP-160"] [data-cmp="CMP-213"]')).toHaveLength(1);
    expect(page().getByRole("group", { name: "Recent" })).toBeVisible();
    expect(await seriousViolations(host)).toEqual([]);
    await type("eth"); // a query hides Recent: one ranked list
    expect([page().queryByRole("group"), page().getAllByRole("option").length]).toEqual([null, 2]);
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("the list follows every keystroke; the count is said once, 300 ms after the last one; message and total", async () => {
    vi.useFakeTimers();
    const host = await mount(<Host />);
    for (const text of ["e", "et", "eth"]) {
      await type(text);
      await wait(200);
      expect(status().textContent).toBe(""); // each keystroke restarts the rest
    }
    expect(page().getAllByRole("option").length).toBe(2); // no settle before the list
    expect(host.querySelector(".cv-symbolsearch__count")?.textContent).toBe("2 results");
    await wait(100);
    expect(status()).toHaveTextContent("2 results");
    document.body.replaceChildren();
    await mount(<Host total={213} />);
    await type("s");
    await wait(300);
    expect(status()).toHaveTextContent("213 results");
    document.body.replaceChildren();
    await mount(<Host message="Checking Bybit for XYZZYUSDT…" />);
    await type("xyzzy");
    await wait(300);
    expect(status()).toHaveTextContent("Checking Bybit for XYZZYUSDT…");
  });

  it("the host's message is said at once, an empty query too (E08-D05 §6.2 Loading); typing never says it again", async () => {
    await mount(<Host loading message="Loading the instrument list…" />);
    expect(status()).toHaveTextContent("Loading the instrument list…");
    const said = status().firstElementChild;
    await type("btc"); // the query is kept; the same node, so nothing is said again
    expect(input()).toHaveValue("btc");
    expect(status().firstElementChild).toBe(said);
  });

  it("settleMs, placeholder, aria-describedby and listLabel are the host's", async () => {
    vi.useFakeTimers();
    await mount(
      <>
        <p id="hints">Enter opens the symbol.</p>
        <Host
          recentSymbols={[row("ETHUSDT")]}
          settleMs={50}
          placeholder="BTC, ETH…"
          aria-describedby="hints"
          listLabel="Results"
        />
      </>,
    );
    expect(input()).toHaveAttribute("placeholder", "BTC, ETH…");
    expect(input()).toHaveAccessibleDescription("Enter opens the symbol.");
    expect(page().getByRole("listbox")).toHaveAccessibleName("Results");
    await type("eth");
    await wait(50);
    expect(status()).toHaveTextContent("2 results");
  });

  it("↓ / ↑ move without wrapping, ↑ on the first back to the text; PageDown / PageUp by the visible rows", async () => {
    await mount(<Host initial="usdt" visibleRows={2} />);
    const path: (string | null)[] = [];
    for (const key of [
      "ArrowDown",
      "ArrowUp",
      "PageDown",
      "PageDown",
      "PageDown",
      "PageUp",
      "PageUp",
      "End",
    ]) {
      await press(key);
      path.push(active());
    }
    expect(path).toEqual([
      "BTCUSDT",
      null,
      "ETHUSDT",
      "SOLUSDT",
      "XRPUSDT",
      "ETHFIUSDT",
      "BTCUSDT",
      "BTCUSDT",
    ]);
    for (let i = 0; i < 6; i += 1) await press("ArrowDown");
    expect(active()).toBe("XRPUSDT"); // no wrap
    expect([await press("Home"), await press("ArrowDown", { shiftKey: true })]).toEqual([
      true,
      true,
    ]);
  });

  it("Enter chooses the active option (once per press); with none active it is the host's; an unavailable one says why", async () => {
    const onSelect = vi.fn();
    await mount(<Host recentSymbols={[LUNA]} onSelect={onSelect} />);
    expect(await press("Enter")).toBe(true);
    await press("ArrowDown");
    expect([await press("Enter"), onSelect.mock.calls]).toEqual([false, []]);
    expect(status()).toHaveTextContent("LUNAUSDT is not trading on Bybit.");
    const said = status().firstElementChild;
    await act(async () => void fireEvent.click(page().getByRole("option")));
    expect(status().firstElementChild).not.toBe(said); // said again, per press
    await type("btc");
    await press("ArrowDown");
    await press("Enter", { repeat: true });
    expect(onSelect).not.toHaveBeenCalled(); // a held key chooses nothing more
    await press("Enter");
    expect(onSelect).toHaveBeenCalledWith("BTCUSDT", ROWS[0]);
  });

  it("onKeyDown runs first with the active option; its preventDefault skips the input's own handling", async () => {
    const seen: string[] = [];
    const onSelect = vi.fn();
    const onKeyDown: SymbolSearchInputProps["onKeyDown"] = (event, item) => {
      seen.push(`${event.key}:${item?.id ?? ""}`);
      if (event.key === "Enter") event.preventDefault();
    };
    await mount(<Host initial="eth" onKeyDown={onKeyDown} onSelect={onSelect} />);
    await press("ArrowDown");
    expect(await press("Enter")).toBe(false);
    await press("ArrowDown", { isComposing: true }); // an IME composition owns its keys
    expect([seen, onSelect.mock.calls, active()]).toEqual([
      ["ArrowDown:", "Enter:ETHUSDT"],
      [],
      "ETHUSDT",
    ]);
  });

  it("onActiveChange and a right-click: the host gets the item, a Recent row's own; a re-rank that drops it says none", async () => {
    const onActiveChange = vi.fn();
    const onContextMenu = vi.fn();
    const recent = row("ETHUSDT", { tags: ["recent"] });
    await mount(
      <Host
        recentSymbols={[recent]}
        onActiveChange={onActiveChange}
        onContextMenu={onContextMenu}
      />,
    );
    expect(onActiveChange).not.toHaveBeenCalled(); // a change, never the mount
    await act(
      async () =>
        void fireEvent.contextMenu(page().getByRole("option"), { clientX: 3, clientY: 4 }),
    );
    expect([active(), onContextMenu.mock.calls]).toEqual([
      "ETHUSDT, recent",
      [[recent, { x: 3, y: 4 }]],
    ]);
    expect(onActiveChange).toHaveBeenLastCalledWith(recent);
    await type("btc");
    expect(onActiveChange).toHaveBeenLastCalledWith(undefined);
  });
});

describe("SymbolSearchInput: a host's menu, T2 and the target (E08-D05 §6.3, D-10; E08-D07 §6.6)", () => {
  it("carry 1: Shift+F10's menu takes focus, the list and its active option stay; Esc returns to the input, same option, and a second Esc is the host's", async () => {
    const { HostMenu } = composeStories(stories); // the host binds Shift+F10 to a CMP-041 Menu on the option
    const onKeyDown = vi.fn<NonNullable<SymbolSearchInputProps["onKeyDown"]>>();
    const escapes = (): number => onKeyDown.mock.calls.filter(([e]) => e.key === "Escape").length;
    await mount(<HostMenu onKeyDown={onKeyDown} />);
    await act(async () => input().focus());
    await press("ArrowDown");
    await press("ArrowDown");
    const before = input().getAttribute("aria-activedescendant");
    await press("F10", { shiftKey: true });
    expect(page().getByRole("menuitem", { name: "Open in Chart 1" })).toHaveFocus();
    expect([
      input().getAttribute("aria-activedescendant"),
      page().getAllByRole("option").length,
    ]).toEqual([before, 2]);
    await userEvent.keyboard("{Escape}");
    expect(input()).toHaveFocus();
    expect([input().getAttribute("aria-activedescendant"), active(), escapes()]).toEqual([
      before,
      "ETHFIUSDT, ETHFI / USDT",
      0, // the menu's
    ]);
    await userEvent.keyboard("{Escape}"); // the host's (SCR-102 closes on it), with the same option
    const [event, item] = onKeyDown.mock.lastCall ?? [];
    expect([escapes(), event?.key, item?.id]).toEqual([1, "Escape", "ETHFIUSDT"]);
    expect(input()).toHaveFocus();
  });

  it("T2: the lock leads, read-only and focusable, no list; a refused key says the reason once. Disabled is native", async () => {
    const reason = "Watching 200 symbols — remove some to add more";
    const host = await mount(<Host initial="eth" disabledReason={reason} />);
    expect(page().getByRole("img", { name: "Not available" })).toBeVisible();
    expect([input().getAttribute("aria-disabled"), input().hasAttribute("readonly")]).toEqual([
      "true",
      true,
    ]);
    expect(input()).toHaveAccessibleDescription(reason);
    expect([input().getAttribute("aria-expanded"), page().queryByRole("listbox")]).toEqual([
      "false",
      null,
    ]);
    await act(async () => input().focus());
    expect([await press("ArrowDown"), await press("PageDown")]).toEqual([false, false]);
    expect(status()).toHaveTextContent(reason);
    expect(await seriousViolations(host)).toEqual([]);
    document.body.replaceChildren();
    await mount(<Host disabled />);
    expect([input().hasAttribute("disabled"), page().queryByRole("listbox")]).toEqual([true, null]);
  });

  it("the target chip names the pane, with E30-D02's ARMED pill when armed; nothing listed shows the host's state", async () => {
    await mount(
      <Host
        target={{ label: "Changes Chart 1 · BTCUSDT 1m", armed: true, id: "t" }}
        emptyMessage={<p>None.</p>}
      />,
    );
    expect(document.getElementById("t")).toHaveTextContent("Changes Chart 1 · BTCUSDT 1m ARMED");
    expect(document.querySelector(".cv-symbolsearch__armed svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect([page().getByText("None.").tagName, input().getAttribute("aria-expanded")]).toEqual([
      "P",
      "false",
    ]);
  });
});

it("runs each SymbolSearchInput story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    canvasElement.remove();
  }
});
