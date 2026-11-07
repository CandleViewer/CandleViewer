// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  FormField,
  METRIC_CATEGORIES,
  MetricPickerCombobox,
  RbacGate,
  formatRbacReason,
  type MetricCategory,
  type MetricPickerComboboxProps,
  type MetricPickerOption,
} from "../src/index.js";
import * as stories from "../src/components/MetricPickerCombobox.stories.js";
import { seriousViolations } from "./axe.js";
import { find, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const NONE = "No metrics match — clear the search.";
const OWNER_ONLY = formatRbacReason("rbac.owner_only", { verb: "start recording" });
const UNRECORDED = "SOLUSDT is not on the recorded-symbol list";
const RECORD = { method: "POST", path: "/api/v1/recording/symbols", body: { symbol: "SOLUSDT" } };
const noop = (): void => undefined;
// An option's accessible name is its visible text (WCAG 2.5.3, Label in Name): the label, the unit, the estimated
// word and, for an unavailable option, the clause's words before its stop; the `·` separator is presentational.
const PRICE_NAME = "Price price";
const REGIME_NAME = "Market regime enum (estimated)";
const SPREAD_NAME = `Spread (bps) bps (not available — ${UNRECORDED} ·`;
const HUNT_NAME = `In stop-hunt zone (not available — ${UNRECORDED})`;

/** E36-D01 R2's count per category and the estimated among them (13 + 41 + 16 + 11 + 13 + 8 + 3 = 105). */
const COUNTS: Readonly<Record<MetricCategory, readonly [number, number]>> = {
  price: [13, 2],
  orderflow: [41, 7],
  book: [16, 2],
  derivatives: [11, 0],
  position: [13, 2],
  account: [8, 0],
  replay: [3, 0],
};
const UNITS = ["price", "ratio", "pct", "bool", "ms", "count", "zscore", "bps", "enum"];
/** A whole vocabulary's worth of options, given category by category in reverse: the picker orders the groups. */
const FULL: readonly MetricPickerOption[] = [...METRIC_CATEGORIES].reverse().flatMap((category) =>
  Array.from({ length: COUNTS[category][0] }, (_, i) => {
    const n = String(i + 1).padStart(2, "0");
    return {
      id: `${category}_${n}`,
      label: `${category} ${n}`,
      unit: UNITS[i % UNITS.length],
      description: `What ${category}_${n} measures`,
      category,
      estimated: i < COUNTS[category][1],
      available: true,
    };
  }),
);
const PRICE: MetricPickerOption = {
  id: "price",
  label: "Price",
  unit: "price",
  description: "Last / mark / index price",
  category: "price",
  estimated: false,
  available: true,
};
const REGIME: MetricPickerOption = {
  ...PRICE,
  id: "market_regime",
  label: "Market regime",
  unit: "enum",
  description: "Regime from ADX, Hurst and ATR%",
  estimated: true,
};
const SPREAD: MetricPickerOption = {
  id: "spread_bps",
  label: "Spread (bps)",
  unit: "bps",
  description: "Spread in basis points of mid",
  category: "book",
  estimated: false,
  available: false,
  unavailableReason: UNRECORDED,
  recorderAction: RECORD,
};
/** Unavailable with no recorder action: explained, with no Start recording. */
const HUNT: MetricPickerOption = {
  ...SPREAD,
  id: "in_stop_hunt_zone",
  label: "In stop-hunt zone",
  unit: undefined,
  description: "Price within k ticks of a detected stop cluster",
  category: "orderflow",
  recorderAction: undefined,
};
const SMALL = [PRICE, REGIME, SPREAD, HUNT];

/** The host's copy (E36-D05's keys where the deck has them). */
const COPY = {
  groupLabel: (category: MetricCategory, n: number) => `${category} (${String(n)})`,
  estimatedText: "(estimated)",
  unavailableText: (option: MetricPickerOption) =>
    option.recorderAction === undefined
      ? `(not available — ${option.unavailableReason ?? ""})`
      : `(not available — ${option.unavailableReason ?? ""} · Start recording)`,
  startRecordingText: "Start recording",
  countText: (n: number) => `${String(n)} metrics`,
  noResultsText: NONE,
};

type HostProps = Partial<Omit<MetricPickerComboboxProps, "value" | "onChange">> & {
  readonly initial?: string | null;
  readonly spy?: MetricPickerComboboxProps["onChange"];
};

/** A controlled host, as every consumer is. */
function Host({ initial = null, spy = noop, ...rest }: HostProps): JSX.Element {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <MetricPickerCombobox
      aria-label="Metric"
      options={SMALL}
      onStartRecording={noop}
      {...COPY}
      {...rest}
      value={value}
      onChange={(id, option) => {
        setValue(id);
        spy(id, option);
      }}
    />
  );
}

const screen = (): ReturnType<typeof within> => within(document.body);
const input = (): HTMLInputElement => screen().getByRole("combobox");
const aria = (...names: string[]): (string | null)[] =>
  names.map((name) => input().getAttribute(`aria-${name}`));
const listbox = (): HTMLElement | null => document.querySelector("[role=listbox]");
const status = (): HTMLElement => screen().getByRole("status");
const option = (name: string): HTMLElement => screen().getByRole("option", { name });
/**
 * Each option's accessible name in `root`, from the role query: `dom-accessibility-api`, the engine of the stories'
 * plays too. It trims each element's text and, with the `beforeEach` spy, spaces children as it does in a browser.
 */
const namesIn = (root: HTMLElement): Map<Element, string> => {
  const seen = new Map<Element, string>();
  within(root).queryAllByRole("option", {
    name: (name: string, element: Element) => {
      seen.set(element, name);
      return true;
    },
  });
  return seen;
};
const names = (): string[] => [...namesIn(document.body).values()];
const activeId = (): string | null => input().getAttribute("aria-activedescendant");
/** The accessible name of the active stop: an option's visible text, or Start recording's words. */
const activeName = (): string | null => {
  const node = document.getElementById(activeId() ?? "");
  if (node === null) return null;
  return namesIn(node.closest<HTMLElement>(".cv-select__row") ?? document.body).get(node) ?? null;
};
/** A node's text outside every `aria-hidden` element, as it stands: how the native accessibility tree joins it. */
const shownText = (node: Node): string => {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (!(node instanceof Element) || node.getAttribute("aria-hidden") === "true") return "";
  return [...node.childNodes].map(shownText).join("");
};
const flat = (text: string): string => text.trim().replace(/\s+/g, " ");
/** The words a node shows: its text nodes outside every `aria-hidden` element (the `·` separator), each trimmed. */
const shownWords = (node: Node): string[] => {
  if (node.nodeType === Node.TEXT_NODE)
    return [(node.textContent ?? "").trim()].filter((word) => word !== "");
  if (!(node instanceof Element) || node.getAttribute("aria-hidden") === "true") return [];
  return [...node.childNodes].flatMap(shownWords);
};
/** The names from the text alone, as the native tree joins it: the 105-option list's check (the role query is slow). */
const shownNames = (): string[] =>
  screen()
    .queryAllByRole("option")
    .map((o: HTMLElement) => flat(shownText(o)));
const headings = (): (string | null | undefined)[] =>
  screen()
    .queryAllByRole("group")
    .map(
      (g: HTMLElement) =>
        document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent,
    );
/** A keydown on the input; true when its default was left to the host (or the caret). */
const press = async (key: string, init: KeyboardEventInit = {}): Promise<boolean> => {
  const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  await act(async () => input().dispatchEvent(event));
  return !event.defaultPrevented;
};
const type = (text: string): Promise<void> =>
  act(async () => void fireEvent.change(input(), { target: { value: text } }));
const wait = (ms: number): Promise<void> => act(() => vi.advanceTimersByTimeAsync(ms).then(noop));
const click = (node: Element): Promise<void> => act(async () => void fireEvent.click(node));
const axeClean = async (): Promise<void> => {
  vi.useRealTimers();
  expect(await seriousViolations(document.body)).toEqual([]);
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  // An empty `display` reads `inline`, as a browser's does for a span; `afterEach` restores it (see `namesIn`).
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) => {
    const style = real(element, pseudo);
    const read = style.getPropertyValue.bind(style);
    style.getPropertyValue = (name) => read(name) || (name === "display" ? "inline" : "");
    return style;
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("MetricPickerCombobox (CMP-157)", () => {
  // Each category's search lists its options; the first and last of each are searched for by name. The settle is
  // 1 ms here (the 500 ms rest is the count test's), and a loaded runner gets a budget.
  it(
    "Gherkin 'The whole vocabulary is reachable on canvas': every option sits in its group, in group order, and is found by search with its unit",
    { timeout: 20_000 },
    async () => {
      vi.useFakeTimers();
      const host = await mount(<Host options={FULL} settleMs={1} />);
      expect(host.querySelectorAll('[data-cmp="CMP-157"]')).toHaveLength(1);
      await press("ArrowDown", { altKey: true }); // opens at once, nothing active
      expect(headings()).toEqual([
        "price (13)",
        "orderflow (41)",
        "book (16)",
        "derivatives (11)",
        "position (13)",
        "account (8)",
        "replay (3)",
      ]);
      const named = (o: MetricPickerOption): string =>
        [o.label, o.unit, o.estimated ? COPY.estimatedText : undefined]
          .filter((word) => word !== undefined)
          .join(" ");
      const inGroupOrder = METRIC_CATEGORIES.flatMap((c) => FULL.filter((o) => o.category === c));
      expect(shownNames()).toEqual(inGroupOrder.map(named)); // the arrows' order, though given in reverse
      await press("ArrowDown");
      expect(activeName()).toBe("price 01 price (estimated)");
      await press("End");
      expect(activeName()).toBe("replay 03 pct");
      const found: string[] = [];
      for (const category of METRIC_CATEGORIES) {
        await type(`${category} `); // every label of the category, and no description
        await wait(1);
        const members = inGroupOrder.filter((o) => o.category === category);
        expect(shownNames()).toEqual(members.map(named));
        const shown = [...document.querySelectorAll('[role="option"]')];
        members.forEach((each, i) => {
          expect(shown[i]?.textContent, each.id).toContain(` · ${each.unit ?? ""}`);
          found.push(each.id);
        });
        for (const each of [members[0], members.at(-1)]) {
          if (each === undefined) continue;
          await type(each.label);
          await wait(1);
          expect(shownNames()).toEqual([named(each)]);
          expect(option(named(each))).toHaveAccessibleDescription(each.description);
        }
      }
      expect(found.sort()).toEqual(FULL.map((o) => o.id).sort());
    },
  );

  it("Gherkin 'Estimated metrics are badged as text': the word is a text node in the option, so it is in the option's name", async () => {
    await mount(<Host />);
    await press("ArrowDown", { altKey: true });
    const tagged = option(REGIME_NAME);
    const words = [...tagged.querySelectorAll("span")].map((span) =>
      [...span.childNodes]
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent?.trim()),
    );
    expect(words.flat()).toContain("(estimated)");
    expect(tagged.querySelector("svg")).toBeNull(); // a word, never a glyph alone
    expect(option(PRICE_NAME).textContent).not.toContain("(estimated)");
    await axeClean();
  });

  it("Gherkin 'Unavailable metric is explained, not hidden': reached, described, never chosen; → reaches Start recording, one press one call", async () => {
    const spy = vi.fn();
    const started = vi.fn();
    await mount(<Host spy={spy} onStartRecording={started} />);
    await type("spread");
    await press("ArrowDown");
    const spread = option(SPREAD_NAME);
    expect([activeId(), spread.getAttribute("aria-disabled")]).toEqual([spread.id, "true"]);
    expect(spread).toHaveAccessibleDescription(
      `(not available — ${UNRECORDED} · Start recording) Spread in basis points of mid`,
    );
    expect(await press("Enter")).toBe(false); // nothing staged; the clause is said again
    expect(status()).toHaveTextContent(`(not available — ${UNRECORDED} · Start recording)`);
    await click(spread);
    expect([spy.mock.calls, aria("expanded")[0]]).toEqual([[], "true"]);
    expect(await press("ArrowRight")).toBe(false);
    const stop = option("Start recording");
    expect([activeId(), stop.getAttribute("aria-disabled")]).toEqual([stop.id, null]);
    await axeClean();
    expect(await press("Enter")).toBe(false);
    expect(started.mock.calls).toEqual([[SPREAD]]);
    await click(stop);
    expect([started.mock.calls.length, spy.mock.calls.length]).toEqual([2, 0]); // a click is one call
    expect(await press("ArrowRight")).toBe(true); // the last stop: the caret's
    expect(await press("ArrowLeft")).toBe(false);
    expect(activeId()).toBe(spread.id);
    expect(await press("ArrowLeft")).toBe(true);
  });

  it("an unavailable option without a recorder action is explained, with no second stop", async () => {
    await mount(<Host />);
    await type("stop-hunt");
    await press("ArrowDown");
    const hunt = option(HUNT_NAME);
    expect(hunt).toHaveAccessibleDescription(
      `(not available — ${UNRECORDED}) Price within k ticks of a detected stop cluster`,
    );
    expect(await press("ArrowRight")).toBe(true);
    expect([activeId(), screen().queryByRole("option", { name: "Start recording" })]).toEqual([
      hunt.id,
      null,
    ]);
  });

  it("a clause without the action's words: Start recording follows it", async () => {
    await mount(<Host unavailableText={() => "(not recorded)"} />);
    await press("ArrowDown", { altKey: true });
    const line = option("Spread (bps) bps (not recorded)").parentElement;
    expect(line?.textContent).toBe("Spread (bps) · bps (not recorded) Start recording");
  });

  it("Start recording is T2 without the permission: the lock leads the full label, aria-disabled, the reason at mount; a press calls nothing", async () => {
    const started = vi.fn();
    await mount(<Host onStartRecording={started} startRecordingReason={OWNER_ONLY} />);
    await press("ArrowDown", { altKey: true });
    const stop = option("Start recording");
    expect(stop).toHaveAccessibleDescription(OWNER_ONLY); // in the DOM before any key
    expect([stop.getAttribute("aria-disabled"), stop.hasAttribute("disabled")]).toEqual([
      "true",
      false,
    ]);
    // The lock leads the full label.
    expect(stop.firstElementChild?.matches(".cv-select__optlock")).toBe(true);
    expect(stop.firstElementChild?.querySelector("svg")).not.toBeNull();
    expect(stop.textContent).toBe("Start recording");
    await type("spread");
    await press("ArrowDown");
    await press("ArrowRight");
    expect(activeId()).toBe(option("Start recording").id); // reached
    expect(await press("Enter")).toBe(false);
    await click(option("Start recording"));
    expect(started).not.toHaveBeenCalled();
    expect(status()).toHaveTextContent(OWNER_ONLY);
    await axeClean();
  });

  it("a whitespace-only Start recording reason is no reason: no lock, not aria-disabled, a press calls once", async () => {
    const started = vi.fn();
    await mount(<Host onStartRecording={started} startRecordingReason="  " />);
    await press("ArrowDown", { altKey: true });
    const stop = option("Start recording");
    expect([stop.getAttribute("aria-disabled"), stop.querySelector(".cv-select__optlock")]).toEqual(
      [null, null],
    );
    await click(stop);
    expect(started.mock.calls).toEqual([[SPREAD]]);
  });

  it("a T1 Start recording is described by its option's clause, which names the symbol", async () => {
    await mount(<Host />);
    await press("ArrowDown", { altKey: true });
    expect(option("Start recording")).toHaveAccessibleDescription(
      `(not available — ${UNRECORDED} · Start recording)`,
    );
  });

  it("says the count once per settled query, never per keystroke; no match says the host's sentence", async () => {
    vi.useFakeTimers();
    await mount(<Host options={FULL} />);
    const region = status();
    const heard: string[] = [];
    new MutationObserver(() => {
      if (region.textContent !== "") heard.push(region.textContent ?? "");
    }).observe(region, { childList: true, characterData: true, subtree: true });
    for (const text of ["o", "or", "ord"]) {
      await type(text);
      await wait(300);
    }
    await wait(199);
    expect([heard, aria("expanded")[0]]).toEqual([[], "false"]);
    await wait(1);
    expect([heard, aria("expanded")[0]]).toEqual([["41 metrics"], "true"]);
    await type("xyz");
    await wait(500);
    expect(heard).toEqual(["41 metrics", NONE]);
    expect(document.querySelector(".cv-combobox__status")).toHaveTextContent(NONE);
    expect(names()).toEqual([]);
    await axeClean();
  });

  it("Enter chooses an available option: its id, then its label in the well; leaving restores the chosen label", async () => {
    vi.useFakeTimers();
    const spy = vi.fn();
    await mount(<Host spy={spy} />);
    await type("regime");
    expect(await press("Enter")).toBe(true); // nothing active: the host's
    await wait(500);
    expect(option(REGIME_NAME).querySelector(".cv-combobox__match")?.textContent).toBe("regime");
    await press("ArrowDown");
    expect(await press("Enter")).toBe(false);
    expect(spy).toHaveBeenLastCalledWith("market_regime", REGIME);
    expect([input().value, aria("expanded")[0]]).toEqual(["Market regime", "false"]);
    await act(async () => input().focus());
    await type("pri");
    await act(async () => input().blur());
    expect([input().value, spy.mock.calls.length]).toEqual(["Market regime", 1]);
  });

  it("Home and End jump in an open list, else the caret's; Esc closes and keeps the text, a second bubbles", async () => {
    await mount(<Host />);
    expect(await press("Home")).toBe(true);
    await press("ArrowDown");
    expect(await press("End")).toBe(false);
    expect(activeName()).toBe(SPREAD_NAME);
    expect(await press("Home")).toBe(false);
    expect(activeName()).toBe(PRICE_NAME);
    await press("ArrowUp"); // ↑ on the first returns to the text
    expect([activeId(), aria("expanded")[0]]).toEqual([null, "true"]);
    expect(await press("Escape")).toBe(false);
    expect(await press("Escape")).toBe(true);
    await press("ArrowDown", { altKey: true });
    await press("ArrowUp", { altKey: true });
    expect(aria("expanded")[0]).toBe("false");
    expect([await press("ArrowDown", { ctrlKey: true }), aria("expanded")[0]]).toEqual([
      true,
      "false",
    ]);
  });

  it("category shows that group alone; a value not among the options shows its id", async () => {
    await mount(<Host category="book" initial="vanished_metric" />);
    expect(input().value).toBe("vanished_metric");
    await press("ArrowDown", { altKey: true });
    expect([headings(), names()]).toEqual([["book (1)"], [SPREAD_NAME, "Start recording"]]);
  });

  it("a hover makes a row active without scrolling; a key move scrolls; a press on the stop never chooses", async () => {
    const spy = vi.fn();
    const scroll = vi.mocked(Element.prototype.scrollIntoView);
    await mount(<Host spy={spy} />);
    await press("ArrowDown", { altKey: true });
    const row = (name: string): Element | null => option(name).closest(".cv-select__row");
    await act(async () => void fireEvent.mouseMove(row(PRICE_NAME) ?? document.body));
    expect([activeName(), scroll.mock.calls.length]).toEqual([PRICE_NAME, 0]);
    await act(async () => void fireEvent.mouseMove(option("Start recording")));
    expect(activeName()).toBe("Start recording");
    await press("ArrowDown");
    expect(scroll).toHaveBeenCalled();
    expect(fireEvent.mouseDown(option(PRICE_NAME))).toBe(false); // prevented: focus stays
    await click(row(PRICE_NAME) ?? document.body);
    expect(spy).toHaveBeenLastCalledWith("price", PRICE);
  });

  it("T2 through CMP-079 and CMP-040: the lock leads the value; keys refused and said once; the list never opens", async () => {
    const spy = vi.fn();
    const host = await mount(
      <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
        <FormField label="Metric">
          <MetricPickerCombobox
            {...COPY}
            options={SMALL}
            value="price"
            onChange={spy}
            onStartRecording={noop}
          />
        </FormField>
      </RbacGate>,
    );
    expect(screen().getByRole("img", { name: "Not available" })).toBeInTheDocument();
    expect(input()).toHaveAccessibleName("Metric");
    expect(input()).toHaveAccessibleDescription("Read-only while viewing as alex.");
    expect([aria("disabled")[0], input().hasAttribute("disabled")]).toEqual(["true", false]);
    expect(host.querySelector("[data-gated]")).not.toBeNull();
    await act(async () => input().focus());
    expect([await press("ArrowDown"), await press("x")]).toEqual([false, false]);
    expect([aria("expanded")[0], listbox()]).toEqual(["false", null]);
    expect(status()).toHaveTextContent("Read-only while viewing as alex.");
    expect(spy).not.toHaveBeenCalled();
    await axeClean();
  });

  it("plain disabled is native: out of the Tab order, and the list never opens", async () => {
    await mount(<Host disabled />);
    expect(input()).toBeDisabled();
    await press("ArrowDown");
    expect([aria("expanded")[0], listbox()]).toEqual(["false", null]);
  });

  // WCAG 2.5.3, Label in Name: what an option shows is in its name. axe's rule for it, `label-content-name-mismatch`,
  // cannot fail in jsdom (its text check needs a canvas, so a mismatch there ends as "incomplete", never as a
  // violation; the Storybook gate's Chromium run is the rule's), so each name is read against the words its option
  // shows (`aria-hidden` ones left out) by two models: `namesIn` (the plays' engine) and `shownText` (the native tree).
  const shows: [string, number, () => JSX.Element][] = [
    [
      "the SevenCategories story's sixteen metrics, estimated and unavailable, and Spread's stop",
      17,
      () => {
        const { SevenCategories } = composeStories(stories);
        return <SevenCategories />;
      },
    ],
    ["estimated, unavailable with a stop, unavailable with no unit and no stop", 5, () => <Host />],
    ["a T2 Start recording stop", 5, () => <Host startRecordingReason={OWNER_ONLY} />],
  ];
  it.each(shows)("Label in Name: each option's name holds %s", async (_, count, render) => {
    await mount(render());
    await press("ArrowDown", { altKey: true });
    const shown: HTMLElement[] = screen().getAllByRole("option");
    expect(shown).toHaveLength(count);
    // Not hollow: the options show their units and the estimated word, and each name is checked against them.
    expect(shown.flatMap(shownWords)).toEqual(expect.arrayContaining(["bps", "(estimated)"]));
    const named = namesIn(document.body);
    for (const node of shown) {
      const name = named.get(node);
      expect(flat(shownText(node)), "the text as the native tree joins it").toBe(name);
      for (const word of shownWords(node)) expect(name, word).toContain(word);
      for (const part of node.querySelectorAll(":not([aria-hidden])"))
        expect(part.textContent?.trim(), "a read element").not.toBe("·");
    }
  });
});

describe("metricpicker.css (CMP-157), forced colours included", () => {
  const { all, normal, forced } = loadCss("metricpicker.css");
  const colourRules = [...normal.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, , body]) => /(^|[\s;])(color|background|outline)\s*:/.test(body ?? ""))
    .map(([, selector]) => (selector ?? "").replace(/\s+/g, " ").trim());

  it("binds tokens only, and is static: no transition or animation", () => {
    expect(normal).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(normal.replace(/\* 1px/g, "")).not.toMatch(/\d+px/);
    expect(all).not.toMatch(/transition|animation/);
  });

  it("every rule that sets a colour has a forced-colours twin in system colours", () => {
    expect(colourRules.length).toBeGreaterThan(4);
    for (const selector of colourRules) expect(forced, selector).toContain(`${selector} {`);
    expect(forced).not.toMatch(/var\(--/);
  });

  it("the active stop is Highlight, T2 stays CanvasText (never GrayText), and an active row's words turn HighlightText", () => {
    const activeStop = find(forced, ".cv-metricpicker__record[data-active]", "background");
    expect(activeStop).toContain("background: Highlight");
    expect(activeStop).toContain("color: HighlightText");
    expect(find(forced, ".cv-metricpicker__record[data-gated]", "color")).toContain(
      "color: CanvasText",
    );
    expect(forced).not.toContain("GrayText");
    for (const part of ["word", "desc", "record"])
      expect(
        find(forced, `.cv-select__row[data-active] .cv-metricpicker__${part}`, "color"),
      ).toContain("color: HighlightText");
    expect(forced.indexOf("[data-gated]")).toBeLessThan(forced.indexOf("[data-active] {"));
  });

  it("T2 is the tertiary label, no underline; never opacity or the disabled colour", () => {
    const gated = find(normal, ".cv-metricpicker__record[data-gated]", "color");
    expect(gated).toContain("color: var(--color-text-tertiary)");
    expect(gated).toContain("text-decoration: none");
    expect(all).not.toMatch(/opacity|--color-text-disabled/);
  });
});

// One test: the runner unmounts a story as the next one starts, before `mount` empties the page. Each play waits
// its real settle, so the loop has its own budget.
it("runs each catalogued story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
  }
});
