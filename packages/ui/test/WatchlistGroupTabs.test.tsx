// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { expect, userEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import {
  GatedAnnounceProvider,
  WatchlistGroupTabs,
  type WatchlistGroupTabsProps,
} from "../src/index.js";
import * as stories from "../src/components/WatchlistGroupTabs.stories.js";
import { seriousViolations } from "./axe.js";
import { find, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const GROUPS = [
  { id: "majors", name: "Majors" },
  { id: "setups", name: "My Setups" },
  { id: "alts", name: "Alts" },
  { id: "breakouts", name: "Breakouts" },
];
const COUNTS = { majors: 12, setups: 8, alts: 187, breakouts: 1 };
const READ_ONLY = "Read-only — your role can't change watchlists.";
const noop = (): void => undefined;

type HostProps = Partial<WatchlistGroupTabsProps>;

/** A host that owns the active list, as SCR-100 does. */
function Host({ onSwitch, ...props }: HostProps): JSX.Element {
  const [active, setActive] = useState("majors");
  return (
    <>
      <button type="button">Before</button>
      <WatchlistGroupTabs
        aria-label="Watchlists"
        groups={GROUPS}
        counts={COUNTS}
        activeId={active}
        onSwitch={(id) => {
          onSwitch?.(id);
          setActive(id);
        }}
        onCreate={noop}
        onRename={noop}
        onDuplicate={noop}
        onDelete={noop}
        onManage={noop}
        {...props}
      >
        <p>The {active} grid</p>
      </WatchlistGroupTabs>
      <button type="button">After</button>
    </>
  );
}

const page = within(document.body);
const tab = (name: RegExp | string): HTMLElement => page.getByRole("tab", { name });
const rect = (width: number): DOMRect =>
  ({ width, height: 24, top: 0, left: 0, right: width, bottom: 24, x: 0, y: 0 }) as DOMRect;

/** Lays the strip out 300 px wide, each tab 100 px and "More lists" 80 px: two tabs fit beside it. */
const narrowStrip = (): void => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    if (this.classList.contains("cv-wltabs__strip")) return rect(300);
    if (this.classList.contains("cv-wltabs__ghost-tab")) return rect(100);
    if (this.classList.contains("cv-wltabs__ghost-more")) return rect(80);
    return rect(0);
  });
};

/** Lays the header row out: the strip, "+" (its span), each measured tab copy and "More lists". */
const layout = (sizes: {
  readonly strip: number;
  readonly plus: number;
  readonly tab: number;
  readonly more: number;
}): void => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    if (this.classList.contains("cv-wltabs__strip")) return rect(sizes.strip);
    if (this.classList.contains("cv-wltabs__create")) return rect(sizes.plus);
    if (this.classList.contains("cv-wltabs__ghost-tab")) return rect(sizes.tab);
    if (this.classList.contains("cv-wltabs__ghost-more")) return rect(sizes.more);
    return rect(0);
  });
};

/** A ResizeObserver a test drives: `resize(el)` calls back only the observers watching `el`, as a browser does. */
class FakeResizeObserver {
  static all: FakeResizeObserver[] = [];
  readonly observed = new Set<Element>();
  readonly callback: () => void;
  disconnected = false;
  constructor(callback: () => void) {
    this.callback = callback;
    FakeResizeObserver.all.push(this);
  }
  observe(target: Element): void {
    this.observed.add(target);
  }
  unobserve(target: Element): void {
    this.observed.delete(target);
  }
  disconnect(): void {
    this.disconnected = true;
    this.observed.clear();
  }
  static live(): FakeResizeObserver[] {
    return FakeResizeObserver.all.filter((o) => !o.disconnected);
  }
  static resize(target: Element): void {
    for (const o of FakeResizeObserver.live()) if (o.observed.has(target)) o.callback();
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  FakeResizeObserver.all = [];
});

describe("WatchlistGroupTabs (CMP-162): the CMP-042 tabs pattern", () => {
  it("a named tablist; each tab named with its list and count, the active one selected", async () => {
    await mount(<Host />);
    expect(page.getByRole("tablist", { name: "Watchlists" })).toBeInTheDocument();
    expect(page.getAllByRole("tab").map((t) => t.getAttribute("aria-label"))).toEqual([
      "Majors, 12 symbols",
      "My Setups, 8 symbols",
      "Alts, 187 of 200 symbols",
      "Breakouts, 1 symbol",
    ]);
    expect(tab("Majors, 12 symbols")).toHaveAttribute("aria-selected", "true");
  });

  it("a tab draws its list's name and count: Majors · 12", async () => {
    await mount(<Host />);
    expect(tab("Majors, 12 symbols")).toHaveTextContent("Majors · 12");
  });

  it("the active tab controls the panel that holds the host's grid", async () => {
    await mount(<Host />);
    const panel = page.getByRole("tabpanel", { name: "Majors, 12 symbols" });
    expect(panel).toHaveTextContent("The majors grid");
    expect(tab("Majors, 12 symbols")).toHaveAttribute("aria-controls", panel.id);
  });

  it("one Tab stop on the active tab; the arrows move focus and never switch (manual activation)", async () => {
    const onSwitch = vi.fn();
    await mount(<Host onSwitch={onSwitch} />);
    page.getByRole("button", { name: "Before" }).focus();
    await userEvent.tab();
    expect(tab("Majors, 12 symbols")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab("My Setups, 8 symbols")).toHaveFocus();
    expect(onSwitch).not.toHaveBeenCalled();
  });

  it("Enter or Space switches to the focused tab, which keeps focus", async () => {
    const onSwitch = vi.fn();
    await mount(<Host onSwitch={onSwitch} />);
    act(() => tab("Majors, 12 symbols").focus());
    await userEvent.keyboard("{ArrowRight}{Enter}");
    expect(onSwitch).toHaveBeenLastCalledWith("setups");
    expect(tab("My Setups, 8 symbols")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight} ");
    expect(onSwitch).toHaveBeenLastCalledWith("alts");
  });

  it("Enter or Space on the active tab switches nothing: the list is already shown", async () => {
    const onSwitch = vi.fn();
    await mount(<Host onSwitch={onSwitch} />);
    act(() => tab("Majors, 12 symbols").focus());
    await userEvent.keyboard("{Enter} ");
    expect(onSwitch).not.toHaveBeenCalled();
    expect(tab("Majors, 12 symbols")).toHaveFocus();
  });

  it("a click switches", async () => {
    const onSwitch = vi.fn();
    await mount(<Host onSwitch={onSwitch} />);
    await userEvent.click(tab("Alts, 187 of 200 symbols"));
    expect(onSwitch).toHaveBeenCalledWith("alts");
  });

  it("Home and End reach the first and last tab; the arrows wrap", async () => {
    await mount(<Host />);
    act(() => tab("Majors, 12 symbols").focus());
    await userEvent.keyboard("{End}");
    expect(tab("Breakouts, 1 symbol")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab("Majors, 12 symbols")).toHaveFocus();
  });

  it('"+" is an icon button named New watchlist that creates a list', async () => {
    const onCreate = vi.fn();
    await mount(<Host onCreate={onCreate} />);
    await userEvent.click(page.getByRole("button", { name: "New watchlist" }));
    expect(onCreate).toHaveBeenCalledOnce();
  });

  it("headerEnd follows + in the header row, before the panel", async () => {
    await mount(<Host headerEnd={<button type="button">Panel options</button>} />);
    const plus = page.getByRole("button", { name: "New watchlist" });
    const options = page.getByRole("button", { name: "Panel options" });
    expect(plus.compareDocumentPosition(options) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      options.compareDocumentPosition(page.getByRole("tabpanel")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("WatchlistGroupTabs (CMP-162): the tab menu", () => {
  it("Shift+F10 on a tab opens its menu: Rename, Duplicate, Delete…, Manage watchlists…", async () => {
    await mount(<Host />);
    act(() => tab("My Setups, 8 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = page.getByRole("menu", { name: "Actions for My Setups" });
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((i) => i.textContent),
    ).toEqual(["Rename", "Duplicate", "Delete…", "Manage watchlists…"]);
  });

  it("the menu acts on the tab it opened from", async () => {
    const onRename = vi.fn();
    await mount(<Host onRename={onRename} />);
    act(() => tab("My Setups, 8 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}{Enter}");
    expect(onRename).toHaveBeenCalledWith("setups");
  });

  it("Duplicate and Delete… act on the tab the menu opened from", async () => {
    const onDuplicate = vi.fn();
    const onDelete = vi.fn();
    await mount(<Host onDuplicate={onDuplicate} onDelete={onDelete} />);
    act(() => tab("My Setups, 8 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}{ArrowDown}{Enter}");
    expect(onDuplicate).toHaveBeenCalledWith("setups");
    act(() => tab("My Setups, 8 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}{ArrowDown}{ArrowDown}{Enter}");
    expect(onDelete).toHaveBeenCalledWith("setups");
  });

  it("Manage watchlists… opens the manager", async () => {
    const onManage = vi.fn();
    await mount(<Host onManage={onManage} />);
    act(() => tab("Majors, 12 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}{ArrowUp}{Enter}");
    expect(onManage).toHaveBeenCalledOnce();
  });

  it("read-only: Rename, Duplicate and Delete… are T2 with the reason; Manage watchlists… stays", async () => {
    const onDelete = vi.fn();
    await mount(<Host writeReason={READ_ONLY} onDelete={onDelete} />);
    act(() => tab("Majors, 12 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const items = within(page.getByRole("menu")).getAllByRole("menuitem");
    expect(items.map((i) => i.getAttribute("aria-disabled"))).toEqual([
      "true",
      "true",
      "true",
      null,
    ]);
    expect(items[2]).toHaveAccessibleDescription(new RegExp(READ_ONLY));
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(onDelete).not.toHaveBeenCalled();
  });

  // G-T2.2 (E09-D09 §2.2, §11; the orchestrator's design read on #5146): the T2 items are CMP-041's T2 rows, whose
  // label and lock menu.css draws in text.tertiary, never text.disabled or an opacity; Manage watchlists… is no T2 row.
  it("read-only: Rename, Duplicate and Delete… are CMP-041's T2 rows, label and lock in text.tertiary (menu.css)", async () => {
    await mount(<Host writeReason={READ_ONLY} />);
    act(() => tab("Majors, 12 symbols").focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const rows = within(page.getByRole("menu"))
      .getAllByRole("menuitem")
      .map((item) => item.closest(".cv-menu__row"));
    expect(rows.map((row) => row?.getAttribute("data-state"))).toEqual([
      "gated",
      "gated",
      "gated",
      null,
    ]);
    const menu = loadCss("menu.css").normal;
    for (const part of [".cv-menu__item", ".cv-menu__lead"]) {
      const rule = find(menu, `.cv-menu__row[data-state="gated"] ${part}`, "color");
      expect(rule).toContain("color: var(--color-text-tertiary)");
      expect(rule).not.toMatch(/text-disabled|opacity/);
    }
  });

  it('read-only: "+" stays, T2 with the reason, and a press creates nothing', async () => {
    const onCreate = vi.fn();
    await mount(<Host writeReason={READ_ONLY} onCreate={onCreate} />);
    const plus = page.getByRole("button", { name: "New watchlist" });
    expect(plus).toHaveAttribute("aria-disabled", "true");
    expect(plus).toHaveAccessibleDescription(READ_ONLY);
    await userEvent.click(plus);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('read-only: a press on "+" says the reason once', async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host writeReason={READ_ONLY} />
      </GatedAnnounceProvider>,
    );
    await userEvent.click(page.getByRole("button", { name: "New watchlist" }));
    expect(announce.mock.calls).toEqual([[READ_ONLY]]);
  });

  it('writeReasonId: "+" is described by the host\'s one notice, with no copy of its own (G-T2.5)', async () => {
    await mount(
      <>
        <p id="lists-notice">{READ_ONLY}</p>
        <Host writeReason={READ_ONLY} writeReasonId="lists-notice" />
      </>,
    );
    const plus = page.getByRole("button", { name: "New watchlist" });
    expect(plus).toHaveAttribute("aria-describedby", "lists-notice");
    expect(plus).toHaveAccessibleDescription(READ_ONLY);
    expect(page.getAllByText(READ_ONLY)).toHaveLength(1);
  });
});

describe("WatchlistGroupTabs (CMP-162): overflow into More lists", () => {
  it("the tabs that do not fit go into More lists", async () => {
    narrowStrip();
    await mount(<Host />);
    expect(page.getAllByRole("tab").map((t) => t.getAttribute("aria-label"))).toEqual([
      "Majors, 12 symbols",
      "My Setups, 8 symbols",
    ]);
    await userEvent.click(page.getByRole("button", { name: "More lists" }));
    expect(
      within(page.getByRole("menu", { name: "More lists" }))
        .getAllByRole("menuitem")
        .map((i) => i.textContent),
    ).toEqual(["Alts, 187 of 200 symbols", "Breakouts, 1 symbol"]);
  });

  it("a list chosen from More lists is switched to and shows as a tab, the active one always shown", async () => {
    const onSwitch = vi.fn();
    narrowStrip();
    await mount(<Host onSwitch={onSwitch} />);
    await userEvent.click(page.getByRole("button", { name: "More lists" }));
    await userEvent.click(page.getByRole("menuitem", { name: "Breakouts, 1 symbol" }));
    expect(onSwitch).toHaveBeenCalledWith("breakouts");
    expect(page.getAllByRole("tab").map((t) => t.getAttribute("aria-label"))).toEqual([
      "Majors, 12 symbols",
      "Breakouts, 1 symbol",
    ]);
    expect(tab("Breakouts, 1 symbol")).toHaveAttribute("aria-selected", "true");
  });

  it("no More lists while every tab fits", async () => {
    await mount(<Host />);
    expect(page.queryByRole("button", { name: "More lists" })).toBeNull();
  });

  it("no room at all beside +: the active tab alone, the rest in More lists (never every tab)", async () => {
    layout({ strip: 50, plus: 60, tab: 100, more: 80 });
    await mount(<Host />);
    expect(page.getAllByRole("tab").map((t) => t.getAttribute("aria-label"))).toEqual([
      "Majors, 12 symbols",
    ]);
    expect(page.getByRole("button", { name: "More lists" })).toBeInTheDocument();
  });

  /** The strip's computed gap (`space.inset.xs`, 4 px): jsdom resolves no stylesheet, so the test gives it. */
  const stripGap = (px: number): void => {
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) =>
      element instanceof HTMLElement && element.classList.contains("cv-wltabs__strip")
        ? ({ ...real(element, pseudo), columnGap: `${px}px` } as CSSStyleDeclaration)
        : real(element, pseudo),
    );
  };

  it("counts the strip's two gaps beside More lists: at the boundary a tab moves out, More lists never squeezes", async () => {
    stripGap(4);
    // Two tabs, More lists and + need 100 + 100 + 80 + 32 and two 4 px gaps: 320 px. At 316 only one tab fits.
    layout({ strip: 316, plus: 32, tab: 100, more: 80 });
    await mount(<Host />);
    expect(page.getAllByRole("tab").map((t) => t.getAttribute("aria-label"))).toEqual([
      "Majors, 12 symbols",
    ]);
  });

  it("two tabs beside More lists exactly at their width with both gaps", async () => {
    stripGap(4);
    layout({ strip: 320, plus: 32, tab: 100, more: 80 });
    await mount(<Host />);
    expect(page.getAllByRole("tab")).toHaveLength(2);
  });

  it("counts the gap before + while every tab fits: one pixel short sends tabs to More lists", async () => {
    stripGap(4);
    // Four 60 px tabs, the gap and +: 60 × 4 + 4 + 32 = 276 px.
    layout({ strip: 275, plus: 32, tab: 60, more: 80 });
    await mount(<Host />);
    expect(page.getByRole("button", { name: "More lists" })).toBeInTheDocument();
  });

  it("watches the measured copies and +: a text-scale change at a fixed width re-measures", async () => {
    const sizes = { strip: 300, plus: 0, tab: 60, more: 80 };
    layout(sizes);
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    await mount(<Host />);
    expect(page.getAllByRole("tab")).toHaveLength(4);
    // The text grows (in-app text scale or zoom): the copies widen, the strip does not.
    sizes.tab = 100;
    const ghost = document.querySelector(".cv-wltabs__ghost-tab") as Element;
    act(() => FakeResizeObserver.resize(ghost));
    expect(page.getAllByRole("tab").map((t) => t.getAttribute("aria-label"))).toEqual([
      "Majors, 12 symbols",
      "My Setups, 8 symbols",
    ]);
    const observed = FakeResizeObserver.live().flatMap((o) => [...o.observed]);
    expect(observed).toContain(document.querySelector(".cv-wltabs__create"));
    expect(observed).toContain(document.querySelector(".cv-wltabs__ghost-more"));
  });

  it("disconnects its observer on unmount", async () => {
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () => root.render(<Host />));
    const live = FakeResizeObserver.live();
    expect(live.length).toBeGreaterThan(0);
    await act(async () => root.unmount());
    expect(live.every((o) => o.disconnected)).toBe(true);
  });
});

describe("WatchlistGroupTabs (CMP-162): axe", () => {
  it("no serious or critical violation, read-only and overflowing", async () => {
    narrowStrip();
    const host = await mount(<Host writeReason={READ_ONLY} />);
    expect(await seriousViolations(host)).toEqual([]);
  });
});

// Each story's play in jsdom (Chromium runs them with axe in the storybook project): Overflow needs a layout engine.
describe("WatchlistGroupTabs (CMP-162): stories", () => {
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      if (name === "Overflow") continue;
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });
});

// The orchestrator's design read on #5146 (item 6): every catalogued component's stories cover hover and keyboard
// focus (`.claude/rules/30-frontend-react.md`), and host text renders in the design-system font, never the serif.
describe("WatchlistGroupTabs (CMP-162) stories: hover, focus and the stories' font", () => {
  it("has a Hover and a FocusVisible story", () => {
    expect(Object.keys(composeStories(stories))).toEqual(
      expect.arrayContaining(["Hover", "FocusVisible"]),
    );
  });

  it("host text renders in the design-system font (the host's panel)", async () => {
    const { Default } = composeStories(stories);
    const host = await mount(<Default />);
    const text = host.querySelector<HTMLElement>('[role="tabpanel"] p');
    expect(text).not.toBeNull();
    expect(text?.closest<HTMLElement>('[style*="font-family"]')?.style.fontFamily).toContain(
      "var(--font-family-ui)",
    );
  });
});
