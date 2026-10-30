// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, Profiler, useState, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { FuzzyList, fuzzyOptionId, type FuzzyListItem, type FuzzyListProps } from "../src/index.js";
import * as moleculeStories from "../src/components/AllMolecules.stories.js";
import * as stories from "../src/components/FuzzyList.stories.js";
import * as searchStories from "../src/components/SymbolSearchInput.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const ETH: FuzzyListItem = {
  id: "ETHUSDT",
  label: "ETHUSDT",
  matchRanges: [[0, 3]],
  hint: "ETH / USDT",
  values: ["▲ +1.23 %", "—"],
  chip: { label: "Not recorded" },
  tags: ["recent", "favourite"],
  description: "24 hours up 1.23 percent",
};
const LUNA: FuzzyListItem = {
  id: "LUNAUSDT",
  label: "LUNAUSDT",
  group: "Recent",
  chip: { label: "Delisted by the exchange", icon: "cancelled" },
  disabled: true,
  delisted: true,
  reason: "LUNAUSDT is not trading on Bybit.",
};
const XRP: FuzzyListItem = {
  id: "XRP",
  label: "XRPUSDT",
  disabled: true,
  reason: "Not traded here.",
};
const many = (n: number): FuzzyListItem[] =>
  Array.from({ length: n }, (_, i) => ({ id: `S${String(i)}`, label: `S${String(i)}USDT` }));

const page = (): ReturnType<typeof within> => within(document.body);
const options = (): HTMLElement[] => page().queryAllByRole("option");
const props = (over: Partial<FuzzyListProps>): FuzzyListProps => ({
  id: "list",
  "aria-label": "Symbols",
  items: [ETH],
  onActivate: vi.fn(),
  ...over,
});
/** The spacers' heights in rows, before and after the window. */
const spacers = (): string[] =>
  [...(page().getByRole("listbox").querySelectorAll(":scope > [aria-hidden='true']") ?? [])].map(
    (s) => (s as HTMLElement).style.blockSize,
  );

/** A host that moves the active option and swaps the list, as a combobox does. */
let move: (activeId: string | undefined) => void = () => undefined;
let swap: (items: FuzzyListItem[]) => void = () => undefined;
function Moving({ items: first }: { readonly items: FuzzyListItem[] }): JSX.Element {
  const [activeId, setActive] = useState<string | undefined>(undefined);
  const [items, setItems] = useState(first);
  move = setActive;
  swap = setItems;
  return <FuzzyList {...props({ items, activeId, visibleRows: 16 })} />;
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("FuzzyList (CMP-213)", () => {
  it("an option holds text and chips only: its name (the worded values too), the matched <mark>, cells and description (axe)", async () => {
    const host = await mount(<FuzzyList {...props({ items: [ETH, LUNA, XRP] })} />);
    expect(page().getByRole("listbox")).toHaveAccessibleName("Symbols");
    const eth = page().getByRole("option", {
      name: "ETHUSDT, ETH / USDT, ▲ +1.23 %, Not recorded, recent, favourite", // an absent "—" says nothing
    });
    expect([eth.id, eth.querySelector("mark")?.textContent]).toEqual([
      fuzzyOptionId("list", "ETHUSDT"),
      "ETH",
    ]);
    expect(eth).toHaveTextContent("ETHUSDT↺ ★ ETH / USDT ▲ +1.23 % — Not recorded"); // a space between cells
    expect(eth).toHaveAccessibleDescription("24 hours up 1.23 percent");
    // No control inside an option (axe `nested-interactive`): nothing focusable but the listbox itself.
    expect(host.querySelectorAll("button, a, input, [tabindex]:not([role=listbox])")).toHaveLength(
      0,
    );
    expect(host.querySelectorAll('[data-cmp="CMP-213"]')).toHaveLength(1);
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("unavailable: aria-disabled and described by its reason at mount; delisted struck with its chip, T2 led by the lock", async () => {
    const host = await mount(<FuzzyList {...props({ items: [LUNA, XRP] })} />);
    const [luna, xrp] = options();
    expect([luna?.getAttribute("aria-disabled"), xrp?.getAttribute("aria-disabled")]).toEqual([
      "true",
      "true",
    ]);
    expect(luna).toHaveAccessibleDescription("LUNAUSDT is not trading on Bybit.");
    expect(xrp).toHaveAccessibleDescription("Not traded here.");
    expect([luna?.hasAttribute("data-delisted"), xrp?.hasAttribute("data-delisted")]).toEqual([
      true,
      false,
    ]);
    expect([luna, xrp].map((o) => o?.querySelector(".cv-fuzzylist__lead svg") !== null)).toEqual([
      false,
      true,
    ]);
    expect(page().getByRole("group", { name: "Recent" })).toContainElement(luna ?? null);
    expect(await seriousViolations(host)).toEqual([]);
  });

  it("activeId marks the host's option; a press activates any option and never takes focus; a right-click is the host's", async () => {
    const onActivate = vi.fn();
    const onContextMenu = vi.fn();
    await mount(
      <FuzzyList
        {...props({ items: [ETH, LUNA], activeId: "LUNAUSDT", onActivate, onContextMenu })}
      />,
    );
    expect(options().map((o) => o.getAttribute("aria-selected"))).toEqual([null, "true"]);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
    expect(fireEvent.mouseDown(options()[0] ?? document.body)).toBe(false); // prevented: focus stays put
    await act(async () => void fireEvent.click(options()[1] ?? document.body));
    expect(onActivate).toHaveBeenCalledWith(LUNA);
    const menu = fireEvent.contextMenu(options()[0] ?? document.body, { clientX: 5, clientY: 9 });
    expect([menu, onContextMenu.mock.calls]).toEqual([false, [[ETH, { x: 5, y: 9 }]]]);
    document.body.replaceChildren();
    await mount(<FuzzyList {...props({})} />);
    expect(fireEvent.contextMenu(options()[0] ?? document.body)).toBe(true); // no host menu: the native one
  });

  it("an item's icon leads it, decorative; a reason and a description both describe it, the reason first", async () => {
    await mount(
      <FuzzyList
        {...props({
          items: [
            { ...ETH, icon: "pin" },
            { ...XRP, description: "No 24 h values." },
          ],
        })}
      />,
    );
    const [eth, xrp] = options();
    expect(eth?.querySelector(".cv-fuzzylist__lead svg")).toHaveAttribute("aria-hidden", "true");
    expect(xrp?.getAttribute("aria-describedby")).toBe(
      `${xrp?.id ?? ""}-why ${xrp?.id ?? ""}-more`,
    );
    expect(xrp).toHaveAccessibleDescription("Not traded here. No 24 h values.");
  });

  it("a malformed or overlapping range is skipped, never drawn twice", async () => {
    await mount(
      <FuzzyList
        {...props({
          items: [
            {
              ...ETH,
              matchRanges: [
                [0, 3],
                [2, 4],
                [5, 5],
                [5, 7],
              ],
            },
          ],
        })}
      />,
    );
    expect([...document.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["ETH", "DT"]);
  });

  it("loading: a busy listbox of static skeleton rows; nothing listed: the host's empty state, no listbox (axe)", async () => {
    const busy = await mount(<FuzzyList {...props({ items: [], loading: true })} />);
    expect([page().getByRole("listbox").getAttribute("aria-busy"), options()]).toEqual([
      "true",
      [],
    ]);
    expect(busy.querySelectorAll(".cv-fuzzylist__skeleton .cv-skeleton__row")).toHaveLength(6);
    expect(await seriousViolations(busy)).toEqual([]);
    document.body.replaceChildren();
    await mount(<FuzzyList {...props({ items: [], emptyMessage: <p>No match.</p> })} />);
    expect([page().queryByRole("listbox"), page().getByText("No match.").tagName]).toEqual([
      null,
      "P",
    ]);
  });
});

describe("FuzzyList windowing (E08-D05 §5; `15`'s 1,000 items)", () => {
  it("at most twice the visible rows renders all, without positions; above, the window and its spacers", async () => {
    await mount(<FuzzyList {...props({ items: many(32), visibleRows: 16 })} />);
    expect([options().length, options()[0]?.hasAttribute("aria-posinset"), spacers()]).toEqual([
      32,
      false,
      [],
    ]);
    document.body.replaceChildren();
    await mount(<FuzzyList {...props({ items: many(33), visibleRows: 16 })} />);
    expect([options().length, options()[0]?.getAttribute("aria-setsize"), spacers()]).toEqual([
      20,
      "33",
      ["calc(13 * var(--size-row-height))"],
    ]);
  });

  it("1,000 items: at most 24 option nodes as the active option moves, the window following it (timed)", async ({
    annotate,
  }) => {
    const timed = async (step: () => Promise<unknown>): Promise<number> => {
      const t = performance.now();
      await step();
      return performance.now() - t;
    };
    const mounted = await timed(() => mount(<Moving items={many(1000)} />));
    const path: number[] = [];
    const moves: number[] = [];
    for (const at of [0, 15, 16, 500, 999, 998, 400, 20]) {
      moves.push(await timed(() => act(async () => move(`S${String(at)}`))));
      path.push(options().length);
      expect(page().getByRole("option", { selected: true }).id).toBe(
        fuzzyOptionId("list", `S${String(at)}`),
      );
    }
    // The window is the 16 visible rows and 4 each way, clipped at the ends; it follows the active option.
    expect(path).toEqual([20, 20, 21, 24, 20, 20, 24, 24]);
    expect(spacers()).toEqual([
      "calc(16 * var(--size-row-height))",
      "calc(960 * var(--size-row-height))",
    ]);
    expect(options()[0]?.getAttribute("aria-posinset")).toBe("17");
    const relisted = await timed(() => act(async () => swap(many(1000).reverse())));
    const ms = (n: number): string => `${n.toFixed(1)} ms`;
    await annotate(
      `1,000 items (jsdom): mount ${ms(mounted)}; a move ${ms(moves.sort((x, y) => x - y)[4] ?? 0)} median, ${ms(moves[7] ?? 0)} max; a new list ${ms(relisted)}`,
    );
  });

  it("a scroll moves the window by the scroll offset; a new list starts at its top, an active one stays", async () => {
    await mount(<Moving items={many(1000)} />);
    const listbox = page().getByRole("listbox");
    Object.defineProperty(listbox, "scrollHeight", { value: 24_000, configurable: true });
    Object.defineProperty(listbox, "scrollTop", {
      value: 14_400,
      configurable: true,
      writable: true,
    });
    await act(async () => void fireEvent.scroll(listbox));
    expect([options()[0]?.textContent, options().length]).toEqual(["S596USDT", 24]);
    await act(async () => move("S600"));
    await act(async () => swap(many(999)));
    expect(listbox.scrollTop).toBe(14_400); // the active option keeps its place
    await act(async () => move(undefined));
    await act(async () => swap(many(998)));
    expect([listbox.scrollTop, options()[0]?.textContent]).toEqual([0, "S0USDT"]);
  });

  it("a re-rank that keeps the active option but moves it far scrolls it into view, in step with the window", async () => {
    await mount(<Moving items={many(50)} />);
    await act(async () => move("S30"));
    const scrolled = vi.mocked(Element.prototype.scrollIntoView);
    scrolled.mockClear();
    await act(async () => swap([...many(50).slice(28), ...many(50).slice(0, 28)])); // S30 to the third row
    const active = page().getByRole("option", { selected: true });
    expect([active.getAttribute("aria-posinset"), scrolled.mock.contexts.length]).toEqual(["3", 1]);
    expect(scrolled.mock.contexts[0]).toBe(active);
  });

  it("a scroll never unmounts the active option: it stays drawn past the window, within 24 nodes", async () => {
    await mount(<Moving items={many(1000)} />);
    await act(async () => move("S600"));
    const active = page().getByRole("option", { selected: true });
    const listbox = page().getByRole("listbox");
    Object.defineProperty(listbox, "scrollHeight", { value: 24_000, configurable: true });
    const scrollTo = async (row: number): Promise<void> => {
      Object.defineProperty(listbox, "scrollTop", {
        value: row * 24,
        configurable: true,
        writable: true,
      });
      await act(async () => void fireEvent.scroll(listbox));
    };
    await scrollTo(100); // the window is rows 96 to 119, one overscan row given up for the active one
    expect([options().length, options()[0]?.textContent]).toEqual([24, "S96USDT"]);
    expect(options()[23]).toBe(active); // the same node
    expect(spacers()).toEqual(
      ["96", "481", "399"].map((n) => `calc(${n} * var(--size-row-height))`),
    );
    await scrollTo(590); // back in the window: still the same node
    expect(page().getByRole("option", { selected: true })).toBe(active);
    expect(options()).toHaveLength(24);
  });

  it("a scroll past the active option draws it above the window, first, the overscan row given up (CR-B2AD-01)", async () => {
    await mount(<Moving items={many(1000)} />);
    await act(async () => move("S10"));
    const active = page().getByRole("option", { selected: true });
    const listbox = page().getByRole("listbox");
    Object.defineProperty(listbox, "scrollHeight", { value: 24_000, configurable: true });
    Object.defineProperty(listbox, "scrollTop", { value: 7_200, configurable: true }); // row 300
    await act(async () => void fireEvent.scroll(listbox));
    // The window is rows 296 to 319: row 296 goes, the active row 10 comes first, the same node.
    expect([options().length, options()[0]]).toEqual([24, active]);
    expect(options()[1]?.textContent).toBe("S297USDT");
    expect(options()[23]?.textContent).toBe("S319USDT");
    expect(spacers()).toEqual(
      ["10", "286", "680"].map((n) => `calc(${n} * var(--size-row-height))`),
    );
  });

  it("a scroll within the row the window is at, or of a list that never windows, renders nothing (CR-B2AD-01)", async () => {
    const renders = vi.fn();
    const scrollTo = async (listbox: HTMLElement, px: number): Promise<number> => {
      Object.defineProperty(listbox, "scrollTop", {
        value: px,
        configurable: true,
        writable: true,
      });
      await act(async () => void fireEvent.scroll(listbox));
      return renders.mock.calls.length;
    };
    await mount(
      <Profiler id="list" onRender={renders}>
        <Moving items={many(1000)} />
      </Profiler>,
    );
    const big = page().getByRole("listbox");
    Object.defineProperty(big, "scrollHeight", { value: 24_000, configurable: true });
    const moved = await scrollTo(big, 2_400); // row 100: the window moves
    // Row 100 still. React may call the list once more to find its state unchanged, then never again.
    const settled = await scrollTo(big, 2_410);
    expect(settled - moved).toBeLessThanOrEqual(1);
    expect(await scrollTo(big, 2_423)).toBe(settled);
    expect(await scrollTo(big, 2_401)).toBe(settled);
    await act(async () => swap(many(20))); // 20 rows of 16 visible: it never windows
    const swapped = renders.mock.calls.length;
    // Row 2 if the list read a row height it does not window by (24,000 / 20): it reads none.
    expect(await scrollTo(big, 2_400)).toBe(swapped);
  });

  it("a new list at its top writes no scroll offset, so a keystroke forces no layout; a scrolled one goes back to 0", async () => {
    await mount(<Moving items={many(1000)} />);
    const listbox = page().getByRole("listbox");
    let at = 0;
    const writes: number[] = [];
    Object.defineProperty(listbox, "scrollTop", {
      configurable: true,
      get: () => at,
      set: (value: number) => void writes.push((at = value)),
    });
    await act(async () => swap(many(999)));
    await act(async () => swap(many(998)));
    expect(writes).toEqual([]);
    at = 2_400;
    await act(async () => void fireEvent.scroll(listbox));
    await act(async () => swap(many(997)));
    expect([writes, at]).toEqual([[0], 0]);
  });

  it("grouped and windowed: an option's aria-posinset / aria-setsize count within its own group", async () => {
    const run = (group: string, n: number): FuzzyListItem[] =>
      Array.from({ length: n }, (_, i) => ({
        id: `${group}${String(i)}`,
        label: `${group}${String(i)}USDT`,
        group,
      }));
    await mount(<Moving items={[...run("Fav", 20), ...run("Rest", 60)]} />);
    for (const [id, group, at, of] of [
      ["Fav15", "Fav", "16", "20"],
      ["Rest14", "Rest", "15", "60"],
    ] as const) {
      await act(async () => move(id));
      const active = page().getByRole("option", { selected: true });
      expect([active.getAttribute("aria-posinset"), active.getAttribute("aria-setsize")]).toEqual([
        at,
        of,
      ]);
      expect(page().getByRole("group", { name: group })).toContainElement(active);
    }
    // The window now holds the end of Fav and the start of Rest: each option counts in its own group.
    const counts = options().map((o) => [
      o.getAttribute("aria-posinset"),
      o.getAttribute("aria-setsize"),
    ]);
    const own = options().map((o) => {
      const [, group, i] = /^list-(Fav|Rest)(\d+)$/.exec(o.id) ?? [];
      return [String(Number(i) + 1), group === "Fav" ? "20" : "60"];
    });
    expect([counts, page().getAllByRole("group").length]).toEqual([own, 2]);
  });
});

/** The rows a listbox stands for: its drawn rows and its spacers' (axe sees a scroll box by its overflow). */
const rowsIn = (listbox: Element): number =>
  [...listbox.querySelectorAll<HTMLElement>("*")].reduce(
    (sum, el) =>
      el.matches('[role="option"], .cv-fuzzylist__header')
        ? sum + 1
        : sum + Number(/^calc\((\d+) \*/.exec(el.style.blockSize)?.[1] ?? 0),
    0,
  );

it("a story whose list scrolls draws it as a combobox's popup, so axe's scrollable-region-focusable passes", async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    if (Story.tags.includes("perf")) continue;
    const host = await mount(<Story />);
    for (const listbox of within(host).queryAllByRole("listbox")) {
      const shown = (listbox.parentElement as HTMLElement).style.getPropertyValue(
        "--cv-fuzzylist-rows",
      );
      if (rowsIn(listbox) <= Number(shown)) continue;
      const combobox = host.querySelector(`[role="combobox"][aria-controls~="${listbox.id}"]`);
      expect(combobox, name).not.toBeNull();
    }
    document.body.replaceChildren();
  }
});

/**
 * axe 4.14's `label-content-name-mismatch` (WCAG 2.5.3), which only CI's Chromium run applies: jsdom has no canvas, so
 * the rule's icon-ligature step throws here and axe reports nothing. An option's text on screen is its text nodes
 * joined with nothing between its elements (a clipped reason or description is off screen); read as words (NFKD,
 * letters and digits only, lower case), it must be one run of its name's words, in order.
 */
const onScreen = (node: Node): string =>
  [...node.childNodes]
    .map((child) => {
      if (child.nodeType === Node.TEXT_NODE) return child.nodeValue ?? "";
      if (!(child instanceof Element) || child.matches(".cv-visually-hidden")) return "";
      return child.localName === "br" ? " " : onScreen(child);
    })
    .join("");
const words = (text: string): string[] =>
  text
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .split(" ")
    .filter(Boolean);
/** The options in `host` whose words on screen are not one run of their name's, as "story: text ≠ name". */
const misnamed = (story: string, host: HTMLElement): string[] => {
  const names = new Map<Element, string>();
  within(host).queryAllByRole("option", {
    name: (name, option) => {
      names.set(option, name);
      return true;
    },
  });
  return [...names].flatMap(([option, name]) => {
    const [seen, all] = [words(onScreen(option)), words(name)];
    const held = all.some((_, at) => seen.every((word, i) => all[at + i] === word));
    return seen.length === 0 || held ? [] : [`${story}: "${onScreen(option)}" ≠ "${name}"`];
  });
};

/** Draws `ui` in a root of its own for `look`, then unmounts it, so its portals and ids go before the next story. */
const drawn = async (
  ui: JSX.Element,
  look: (host: HTMLElement) => Promise<void> | void,
): Promise<void> => {
  const host = document.body.appendChild(document.createElement("div"));
  const root = createRoot(host);
  await act(async () => root.render(ui));
  try {
    await look(host);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
};

it("every story's option holds its words on screen, in order, in its name (axe's label-content-name-mismatch)", async () => {
  const found: string[] = [];
  let rows = 0;
  const check = (story: string, host: HTMLElement): void => {
    rows += within(host).queryAllByRole("option").length;
    found.push(...misnamed(story, host));
  };
  // The matrix draws one page in every theme and density: its first story holds every row the others do.
  const { DarkCompact } = composeStories(moleculeStories);
  await drawn(<DarkCompact />, (host) => check("AllMolecules", host));
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    if (!Story.tags.includes("perf"))
      await drawn(<Story />, (host) => check(`FuzzyList/${name}`, host));
  }
  for (const [name, Story] of Object.entries(composeStories(searchStories))) {
    await drawn(<Story />, async (host) => {
      check(`SymbolSearchInput/${name}`, host);
      // Every illustrative symbol holds "usdt": the query lists each ranked row these stories can draw.
      const input = within(host).queryByRole("combobox");
      if (input instanceof HTMLInputElement && !input.readOnly && !input.disabled) {
        await act(async () => void fireEvent.change(input, { target: { value: "usdt" } }));
        check(`SymbolSearchInput/${name} "usdt"`, host);
      }
    });
  }
  expect([found, rows > 0]).toEqual([[], true]);
});

// One test: each story's play in turn (the storybook project runs them in Chromium; `perf` stories are skipped, and
// so are the theme stories, whose plays wait on the preview's theme runtime, which only that project loads).
it("runs each FuzzyList story's play function", { timeout: 20_000 }, async () => {
  for (const [name, Story] of Object.entries(composeStories(stories))) {
    if (Story.tags.includes("perf") || Story.globals["theme"] !== undefined) continue;
    const canvasElement = document.body.appendChild(document.createElement("div"));
    await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
  }
});
