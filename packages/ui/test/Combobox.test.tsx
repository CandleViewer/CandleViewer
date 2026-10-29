// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { createRequire } from "node:module";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Combobox,
  Dialog,
  FormField,
  Icon,
  RBAC_REASONS,
  RbacGate,
  type ComboboxOption,
  type ComboboxProps,
} from "../src/index.js";
import * as stories from "../src/components/Combobox.stories.js";
import { mount } from "./theme/mount.js";

type Violation = { id: string; impact?: string | null };
type Axe = { run: (c: object, o?: object) => Promise<{ violations: Violation[] }> };
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const LOCKED = RBAC_REASONS["rbac.account"];
const NONE = "No USDT perpetual matches the query.";
const FAILED = "Couldn't load the instrument list.";
const BTC: ComboboxOption = { value: "btc", label: "BTCUSDT" };
const ETH: ComboboxOption = { value: "eth", label: "ETHUSDT" };
const OPTIONS = [BTC, ETH, { value: "xrp", label: "XRPUSDT", disabledReason: LOCKED }];
const sentences = { noResultsText: NONE, searchFailedText: FAILED };
const noop = (): void => undefined;

/** Everything a host passes besides the controlled pair, per source (local or searched). */
type Source<P = ComboboxProps> = P extends unknown ? Omit<P, "value" | "onChange"> : never;
type HostProps = Source & { initial?: string; spy?: ComboboxProps["onChange"] };

type Call = { query: string; signal: AbortSignal; answer: (o: readonly ComboboxOption[]) => void };
/** A host search that records each call; the test answers it. */
function recorded(): { calls: Call[]; search: NonNullable<ComboboxProps["asyncSearch"]> } {
  const calls: Call[] = [];
  return {
    calls,
    search: (query, signal) => new Promise((answer) => calls.push({ query, signal, answer })),
  };
}

/** A controlled host, as every consumer is. */
function Host({ initial = "", spy = noop, ...source }: HostProps): JSX.Element {
  const [value, setValue] = useState(initial);
  const change: ComboboxProps["onChange"] = (next, option) => {
    setValue(next);
    spy(next, option);
  };
  return <Combobox aria-label="Symbol" {...source} value={value} onChange={change} />;
}

const screen = (): ReturnType<typeof within> => within(document.body);
const input = (): HTMLElement => screen().getByRole("combobox");
/** The input's `aria-*` values, in order. */
const aria = (...names: string[]): (string | null)[] =>
  names.map((name) => input().getAttribute(`aria-${name}`));
const listbox = (): HTMLElement | null => document.querySelector("[role=listbox]");
const status = (): HTMLElement => screen().getByRole("status");
const row = (): Element | null => document.querySelector(".cv-combobox__status");
const labels = (): string[] =>
  screen()
    .queryAllByRole("option")
    .map((o: HTMLElement) => o.textContent ?? "");
const option = (name: string): HTMLElement => screen().getByRole("option", { name });
const activeLabel = (): string | null => {
  const id = input().getAttribute("aria-activedescendant");
  return id === null ? null : (document.getElementById(id)?.textContent ?? "");
};
/** A keydown on the input; true when its default was left to the host. */
const press = async (key: string, init: KeyboardEventInit = {}): Promise<boolean> => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  await act(async () => input().dispatchEvent(event));
  return !event.defaultPrevented;
};
const type = (text: string): Promise<void> =>
  act(async () => void fireEvent.change(input(), { target: { value: text } }));
const wait = (ms: number): Promise<void> => act(() => vi.advanceTimersByTimeAsync(ms).then(noop));
/** No serious or critical axe violation in this state (the Storybook gate's levels). */
const axeClean = async (): Promise<void> => {
  vi.useRealTimers();
  const { violations } = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Combobox (CMP-048)", () => {
  it("renders closed; typing opens the list only at the settle, filtered by a case-insensitive match", async () => {
    vi.useFakeTimers();
    const host = await mount(<Host options={OPTIONS} />);
    expect(aria("autocomplete", "expanded", "controls")).toEqual(["list", "false", null]);
    expect(host.querySelectorAll('[data-cmp="CMP-048"]')).toHaveLength(1);
    await type("sdt");
    await wait(499);
    expect([...aria("expanded"), listbox()]).toEqual(["false", null]); // closed before the settle
    await wait(1);
    expect(labels()).toEqual(["BTCUSDT", "ETHUSDT", "XRPUSDT"]);
    await type("eth");
    expect([...aria("expanded"), listbox()]).toEqual(["false", null]); // a keystroke waits again
    await wait(500);
    expect(labels()).toEqual(["ETHUSDT"]);
    expect(aria("expanded", "controls")).toEqual(["true", listbox()?.id]);
    expect(listbox()).toHaveAccessibleName("Symbol");
    expect(option("ETHUSDT").querySelector(".cv-combobox__match")?.textContent).toBe("ETH");
  });

  it("Gherkin 'Combobox keyboard': the arrows move the active option, named by aria-activedescendant", async () => {
    await mount(<Host options={OPTIONS} />);
    await type("usdt");
    const path: (string | null)[] = [];
    for (const key of ["ArrowDown", "ArrowDown", "ArrowDown", "ArrowDown", "ArrowUp", "ArrowUp"]) {
      expect(await press(key)).toBe(false);
      path.push(activeLabel());
    }
    // The T2 XRPUSDT is reached, and there is no wrap.
    expect(path).toEqual(["BTCUSDT", "ETHUSDT", "XRPUSDT", "XRPUSDT", "ETHUSDT", "BTCUSDT"]);
    expect(option("BTCUSDT")).toHaveAttribute("aria-selected", "true");
    expect(option("ETHUSDT")).not.toHaveAttribute("aria-selected");
    await axeClean();
    // Home and End move the caret: not consumed, nothing else moves.
    expect([await press("Home"), await press("End")]).toEqual([true, true]);
    expect(activeLabel()).toBe("BTCUSDT");
    await press("ArrowUp"); // ↑ on the first option returns to the text
    expect([activeLabel(), ...aria("expanded")]).toEqual([null, "true"]);
  });

  it("↓ opens a closed list on the first option; Alt+↓ opens without moving; Alt+↑ closes", async () => {
    await mount(<Host options={OPTIONS} />);
    expect(await press("ArrowDown", { altKey: true })).toBe(false);
    expect([...aria("expanded"), activeLabel(), labels().length]).toEqual(["true", null, 3]);
    await press("ArrowUp", { altKey: true });
    expect(aria("expanded")).toEqual(["false"]);
    await press("ArrowDown");
    expect(activeLabel()).toBe("BTCUSDT");
  });

  it("Enter chooses the active option, shows its label and closes; with none active it is the host's", async () => {
    const spy = vi.fn();
    await mount(<Host options={OPTIONS} spy={spy} />);
    await type("eth");
    expect(await press("Enter")).toBe(true);
    await press("ArrowDown");
    expect(await press("Enter")).toBe(false);
    expect(spy).toHaveBeenLastCalledWith("ETHUSDT", ETH);
    expect([(input() as HTMLInputElement).value, ...aria("expanded")]).toEqual([
      "ETHUSDT",
      "false",
    ]);
  });

  it("a T2 option is reached, never chosen: Enter or a press says its reason, once per press", async () => {
    const spy = vi.fn();
    await mount(<Host options={OPTIONS} spy={spy} />);
    await type("xrp");
    await press("ArrowDown");
    expect(option("XRPUSDT")).toHaveAttribute("aria-disabled", "true");
    expect(option("XRPUSDT")).toHaveAccessibleDescription(LOCKED);
    expect(await press("Enter")).toBe(false);
    expect(status()).toHaveTextContent(LOCKED);
    const said = status().firstElementChild;
    await act(async () => void fireEvent.click(option("XRPUSDT")));
    expect(status().firstElementChild).not.toBe(said); // a new node: said again
    expect([spy.mock.calls, ...aria("expanded")]).toEqual([[["xrp", undefined]], "true"]);
  });

  it("Esc closes the list and keeps the text, a second Esc bubbles; leaving never chooses", async () => {
    vi.useFakeTimers();
    const spy = vi.fn();
    await mount(<Host options={OPTIONS} spy={spy} />);
    await type("eth");
    await press("ArrowDown"); // an arrow opens at once
    expect(await press("Escape")).toBe(false);
    expect([(input() as HTMLInputElement).value, ...aria("expanded")]).toEqual(["eth", "false"]);
    expect(await press("Escape")).toBe(true);
    await type("et"); // before the settle nothing is open: Esc bubbles, and the list never opens
    expect(await press("Escape")).toBe(true);
    await wait(500);
    expect(aria("expanded")).toEqual(["false"]);
    await act(async () => input().focus());
    await press("ArrowDown");
    await act(async () => input().blur());
    expect([spy.mock.calls.length, ...aria("expanded")]).toEqual([2, "false"]);
  });

  it("inside a Dialog the list portals into its layer; Esc closes the list only, the next the dialog", async () => {
    const onOpenChange = vi.fn();
    function InDialog(): JSX.Element {
      const [value, setValue] = useState("");
      return (
        <Dialog open title="Search symbols" onOpenChange={onOpenChange}>
          <Combobox aria-label="Symbol" options={OPTIONS} value={value} onChange={setValue} />
        </Dialog>
      );
    }
    await mount(<InDialog />);
    expect(input()).toHaveFocus();
    await type("eth");
    await press("ArrowDown");
    const layer = screen().getByRole("dialog").closest("[data-cv-layer]");
    expect(listbox()?.closest("[data-cv-layer]")).toBe(layer);
    await press("Escape");
    expect([...aria("expanded"), onOpenChange.mock.calls]).toEqual(["false", []]);
    await press("Escape");
    expect(onOpenChange).toHaveBeenCalledWith(false, "escape");
  });

  it("a hover makes a row active without scrolling; a key move scrolls; a press keeps focus and chooses", async () => {
    const spy = vi.fn();
    const scroll = vi.mocked(Element.prototype.scrollIntoView);
    await mount(<Host options={OPTIONS} spy={spy} />);
    await act(async () => input().focus());
    await type("usdt");
    await press("ArrowDown", { altKey: true }); // opens at once, nothing active
    await act(async () => void fireEvent.mouseMove(option("ETHUSDT")));
    expect([activeLabel(), scroll.mock.calls.length]).toEqual(["ETHUSDT", 0]);
    await press("ArrowDown");
    expect([activeLabel(), scroll.mock.calls.length]).toEqual(["XRPUSDT", 1]);
    expect(fireEvent.mouseDown(option("BTCUSDT"))).toBe(false); // prevented: focus stays
    await act(async () => void fireEvent.click(option("BTCUSDT")));
    expect(spy).toHaveBeenLastCalledWith("BTCUSDT", BTC);
    expect(input()).toHaveFocus();
  });
});

describe("Combobox states and the settled query", () => {
  it("asyncSearch runs once per settled query: closed until then, Searching… while in flight", async () => {
    vi.useFakeTimers();
    const { calls, search } = recorded();
    await mount(<Host asyncSearch={search} {...sentences} />);
    for (const text of ["b", "bt", "btc"]) {
      await type(text);
      await wait(100);
    }
    expect([calls, ...aria("expanded"), listbox(), row()]).toEqual([[], "false", null, null]);
    await wait(400);
    expect(calls.map((c) => c.query)).toEqual(["btc"]);
    expect([...aria("expanded"), listbox()?.getAttribute("aria-busy")]).toEqual(["true", "true"]);
    expect(row()).toHaveTextContent("Searching…");
    expect(status().textContent).toBe(""); // "Searching…" is shown, never said
    await act(async () => calls[0]?.answer([BTC]));
    expect([labels(), listbox()?.getAttribute("aria-busy")]).toEqual([["BTCUSDT"], null]);
    expect(status()).toHaveTextContent("1 result");
  });

  it.each([
    ["upper-cases it", (text: string) => text.toUpperCase(), "BTC"],
    ["caps it at 2 characters", (text: string) => text.slice(0, 2), "bt"],
  ])(
    "a host that %s: the settle searches its value, and the answer ends busy",
    async (_s, fit, sent) => {
      vi.useFakeTimers();
      const { calls, search } = recorded();
      function Normalising(): JSX.Element {
        const [value, setValue] = useState("");
        const change = (next: string): void => setValue(fit(next));
        return (
          <Combobox
            aria-label="Symbol"
            {...sentences}
            asyncSearch={search}
            value={value}
            onChange={change}
          />
        );
      }
      await mount(<Normalising />);
      await type("btc");
      await wait(500);
      expect(calls.map((c) => c.query)).toEqual([sent]);
      await act(async () => calls[0]?.answer([BTC]));
      expect([labels(), listbox()?.getAttribute("aria-busy")]).toEqual([["BTCUSDT"], null]);
    },
  );

  it("a stale answer never overwrites a newer query's results; the old request is aborted", async () => {
    vi.useFakeTimers();
    const { calls, search } = recorded();
    await mount(<Host asyncSearch={search} {...sentences} />);
    await type("eth");
    await wait(500);
    await type("btc");
    await wait(500);
    expect(calls.map((c) => c.query)).toEqual(["eth", "btc"]);
    expect(calls.map((c) => c.signal.aborted)).toEqual([true, false]);
    await act(async () => calls[1]?.answer([BTC]));
    await act(async () => calls[0]?.answer([ETH]));
    expect(labels()).toEqual(["BTCUSDT"]);
  });

  it.each([
    ["no results", NONE, () => Promise.resolve([])],
    ["search failed", FAILED, () => Promise.reject(new Error("offline"))],
  ])("%s: the host's sentence in a status row, said once", async (_s, text, search) => {
    vi.useFakeTimers();
    await mount(<Host asyncSearch={search} {...sentences} />);
    await type("xyz");
    await wait(500);
    expect([labels(), listbox()?.getAttribute("aria-busy")]).toEqual([[], null]);
    expect(row()).toHaveTextContent(text);
    expect(row()?.querySelector("svg") !== null).toBe(text === FAILED); // the `danger` glyph
    expect(status()).toHaveTextContent(text);
    await axeClean();
  });

  it.each([
    ["loading", { loading: true }, "Searching…", "true"],
    ["no match", { noResultsText: NONE }, NONE, null],
  ])("local options, %s: a status row at the settle", async (_s, extra, text, busy) => {
    vi.useFakeTimers();
    await mount(<Host options={OPTIONS} {...extra} />);
    await type("xyz");
    await wait(500);
    expect([...aria("expanded"), listbox()?.getAttribute("aria-busy")]).toEqual(["true", busy]);
    expect(row()).toHaveTextContent(text);
    await axeClean();
  });

  it("says the count once per settled query, 500 ms after the last keystroke, never per keystroke", async () => {
    vi.useFakeTimers();
    await mount(<Host options={OPTIONS} />);
    const region = status();
    const heard: string[] = [];
    new MutationObserver(() => {
      if (region.textContent !== "") heard.push(region.textContent ?? "");
    }).observe(region, { childList: true, characterData: true, subtree: true });
    for (const text of ["u", "us", "usd", "usdt"]) {
      await type(text);
      await wait(300);
    }
    await wait(199);
    expect([heard, region.textContent, ...aria("expanded")]).toEqual([[], "", "false"]);
    await wait(1);
    expect([heard, ...aria("expanded")]).toEqual([["3 results"], "true"]);
    await wait(2000);
    await press("ArrowDown");
    await type("eth");
    await wait(500);
    await type("xyz"); // a local no match without a sentence closes the list and says the count
    await wait(500);
    expect([heard, ...aria("expanded")]).toEqual([["3 results", "1 result", "0 results"], "false"]);
  });

  it.each([
    ["aria-label", { "aria-label": "Symbol" }],
    ["aria-labelledby", { "aria-labelledby": "symbol-name" }],
  ])("outside a FormField, %s names the input and the list (axe, open)", async (_s, name) => {
    await mount(
      <>
        <span id="symbol-name">Symbol</span>
        <Combobox {...name} options={OPTIONS} value="" onChange={noop} />
      </>,
    );
    await press("ArrowDown", { altKey: true });
    expect(input()).toHaveAccessibleName("Symbol");
    expect(listbox()).toHaveAccessibleName("Symbol");
    await axeClean();
  });

  it("a press on the well (the prefix glyph) focuses the input and keeps an open list open", async () => {
    await mount(<Host options={OPTIONS} prefix={<Icon name="search" />} />);
    const glyph = document.querySelector(".cv-field__affix svg") ?? document.body;
    expect([fireEvent.mouseDown(glyph), document.activeElement === input()]).toEqual([false, true]);
    await press("ArrowDown", { altKey: true });
    await act(async () => void fireEvent.mouseDown(glyph));
    expect([document.activeElement === input(), ...aria("expanded")]).toEqual([true, "true"]);
  });

  it("prefix sits in the well as CMP-007's, its glyph aria-hidden; a T2 lock comes first", async () => {
    const plain = await mount(<Host options={OPTIONS} prefix={<Icon name="search" />} />);
    expect(plain.querySelector(".cv-field")).toHaveAttribute("data-lead");
    expect(plain.querySelector(".cv-field__affix svg")).toHaveAttribute("aria-hidden", "true");
    plain.remove();
    const gated = await mount(
      <Host options={OPTIONS} prefix={<Icon name="search" />} disabledReason={LOCKED} />,
    );
    const leads = [...gated.querySelectorAll(".cv-field > .cv-field__lead")];
    expect(leads.map((lead) => lead.className)).toEqual([
      "cv-field__lead cv-field__lock",
      "cv-field__lead cv-field__affix",
    ]);
    await axeClean();
  });

  it("invalid: aria-invalid and the danger well; in a FormField its error describes the input", async () => {
    const host = await mount(<Host options={OPTIONS} invalid />);
    expect(aria("invalid")).toEqual(["true"]);
    expect(host.querySelector("[data-invalid]")).toHaveClass("cv-field");
    host.remove();
    await mount(
      <FormField label="Symbol" error="Choose a listed symbol.">
        <Combobox options={OPTIONS} value="zz" onChange={noop} />
      </FormField>,
    );
    expect(aria("invalid")).toEqual(["true"]);
    expect(input()).toHaveAccessibleDescription("Choose a listed symbol.");
    await axeClean();
  });

  it("plain disabled is native: out of the Tab order, and the list never opens", async () => {
    await mount(<Host options={OPTIONS} initial="BTC" disabled />);
    expect(input()).toBeDisabled();
    await press("ArrowDown");
    expect([...aria("expanded"), listbox()]).toEqual(["false", null]);
    await axeClean();
  });

  it("T2 through CMP-079 and CMP-040: the lock leads the value; focusable, read-only; keys refused, said once", async () => {
    const spy = vi.fn();
    const host = await mount(
      <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
        <FormField label="Metric">
          <Combobox options={OPTIONS} value="BTC" onChange={spy} />
        </FormField>
      </RbacGate>,
    );
    const lock = screen().getByRole("img", { name: "Not available" });
    expect(lock.compareDocumentPosition(input()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(input()).toHaveAccessibleName("Metric");
    expect(input()).toHaveAccessibleDescription("Read-only while viewing as alex.");
    expect([...aria("disabled"), input().hasAttribute("disabled")]).toEqual(["true", false]);
    expect(input()).toHaveAttribute("readonly");
    expect(host.querySelector("[data-gated]")).not.toBeNull();
    await act(async () => input().focus());
    expect([await press("ArrowDown"), await press("x")]).toEqual([false, false]);
    expect(aria("expanded")).toEqual(["false"]);
    expect(status()).toHaveTextContent("Read-only while viewing as alex.");
    expect(spy).not.toHaveBeenCalled();
    await axeClean();
  });

  it("type: asyncSearch needs both host sentences, and a list is local or searched, never both", () => {
    const search = async (): Promise<readonly ComboboxOption[]> => [];
    const pair = { value: "", onChange: noop };
    // @ts-expect-error a searched list must say what no match means: `noResultsText` is required.
    const silent: ComboboxProps = { ...pair, asyncSearch: search, searchFailedText: FAILED };
    // @ts-expect-error a list is local (`options`) or searched (`asyncSearch`), never both.
    const both: ComboboxProps = { ...pair, options: [], asyncSearch: search, ...sentences };
    expect([silent, both]).toHaveLength(2);
  });
});

describe("Combobox host hooks (E08-D05 A-D05-6)", () => {
  const S = (n: number): string => `S${String(n).padStart(2, "0")}USDT`;
  const MANY: ComboboxOption[] = Array.from({ length: 25 }, (_, i) => ({
    value: S(i + 1),
    label: S(i + 1),
  }));

  it.each([
    [
      "the whole rows that fit the list (118 px over 24 px rows: 4.9, so 4)",
      true,
      [4, 8, 12, 16, 20, 24, 25, 25],
      21,
    ],
    ["10 when nothing is laid out", false, [10, 20, 25, 25], 15],
  ])(
    "PageDown / PageUp move by a page, %s, within the list: no wrap, never back to the text",
    async (_s, laidOut, downs, firstUp) => {
      await mount(<Host options={MANY} />);
      expect(await press("PageDown")).toBe(true); // a closed list: the key is the page's
      expect(aria("expanded")).toEqual(["false"]);
      await press("ArrowDown", { altKey: true }); // open, nothing active
      expect(document.querySelector(".cv-combobox__popup")).not.toHaveAttribute("data-animated");
      expect([await press("PageUp"), activeLabel()]).toEqual([false, null]); // the text stays
      expect([await press("PageDown", { altKey: true }), activeLabel()]).toEqual([true, null]);
      // jsdom lays nothing out: the page reads only these two heights.
      const measured = [
        [listbox(), 118],
        [document.querySelector(".cv-select__row"), 24],
      ] as const;
      for (const [node, height] of laidOut ? measured : [])
        if (node !== null)
          vi.spyOn(node, "getBoundingClientRect").mockReturnValue({ height } as DOMRect);
      const path: (string | null)[] = [];
      while (path.length < downs.length) {
        expect(await press("PageDown")).toBe(false);
        path.push(activeLabel());
      }
      expect(path).toEqual(downs.map(S));
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled(); // a key move scrolls its row in
      expect(await press("PageUp")).toBe(false);
      expect(activeLabel()).toBe(S(firstUp));
      for (let i = 0; i < 6; i += 1) await press("PageUp");
      expect([activeLabel(), ...aria("expanded")]).toEqual([S(1), "true"]); // never the text
    },
  );

  it("settleMs sets the rest before the list opens and the count is said (CMP-160 passes 300)", async () => {
    vi.useFakeTimers();
    await mount(<Host options={OPTIONS} settleMs={300} />);
    await type("eth");
    await wait(299);
    expect([...aria("expanded"), status().textContent]).toEqual(["false", ""]);
    await wait(1);
    expect([...aria("expanded"), status().textContent]).toEqual(["true", "1 result"]);
  });

  it("a key a native listener prevented before the host's turn is still the combobox's", async () => {
    await mount(<Host options={OPTIONS} onKeyDown={noop} />);
    input().addEventListener("keydown", (event) => event.preventDefault());
    await press("ArrowDown");
    expect([...aria("expanded"), activeLabel()]).toEqual(["true", "BTCUSDT"]);
  });

  it("onKeyDown runs first with the active option; its preventDefault skips the combobox's own handling", async () => {
    const seen: string[] = [];
    const spy = vi.fn();
    const onKeyDown: ComboboxProps["onKeyDown"] = (event, active) => {
      seen.push(`${event.key}:${active?.label ?? ""}`);
      if (["Enter", "Escape", "F10"].includes(event.key)) event.preventDefault();
    };
    await mount(<Host options={OPTIONS} spy={spy} onKeyDown={onKeyDown} />);
    expect(await press("ArrowDown")).toBe(false); // left to the combobox: it opens on BTCUSDT
    for (const [key, shiftKey] of [
      ["F10", true],
      ["Enter", true],
      ["Enter", false],
      ["Escape", false],
    ] as const)
      expect(await press(key, { shiftKey })).toBe(false);
    expect(seen.join(" ")).toBe(
      "ArrowDown: F10:BTCUSDT Enter:BTCUSDT Enter:BTCUSDT Escape:BTCUSDT",
    );
    // Nothing chosen, nothing closed: the host took Enter and Esc.
    expect([spy.mock.calls, ...aria("expanded"), activeLabel()]).toEqual([[], "true", "BTCUSDT"]);
    await press("Enter", { isComposing: true }); // an IME composition is never the host's
    expect(seen).toHaveLength(5);
  });
});

// One test: the runner unmounts a story as the next one starts, before `mount` empties the page. Each play waits
// its real settle, so the loop has its own budget: 14 stories took 5.1 s on a loaded runner, past the 5 s default.
it("runs each catalogued story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
  }
});
