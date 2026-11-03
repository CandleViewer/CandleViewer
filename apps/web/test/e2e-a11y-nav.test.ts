// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { Page } from "@playwright/test";
import { ForbiddenPointerApiError, guardPage } from "../e2e/a11y-nav/mouseGuard";
import {
  judgeFocusSequence,
  nameFromAriaLine,
  WRAPPED,
  type FocusStop,
} from "../e2e/a11y-nav/trap";
import { politeBudget } from "../e2e/a11y-nav/liveRegion";
import { focusableCount, trapBudget } from "../e2e/a11y-nav/trapBudget";
import { judgeFocusIndicator, parseRgba } from "../e2e/a11y-nav/focusVisibility";
import { contrastRatio } from "../../../tools/contrast/color-math.mjs";

/** E47-Q03 PR-1: the pure halves of the keyboard-only suite's infrastructure. */
const fakePage = (): Page => {
  const locator = {
    click: () => "clicked",
    press: () => "pressed",
    first: () => locator,
    all: async () => [locator],
    elementHandle: async () => locator,
  };
  const frame = { click: () => "clicked", locator: () => locator };
  const context = { pages: () => [page] };
  const page = {
    locator: () => locator,
    getByRole: () => locator,
    goto: async () => "ok",
    mouse: { move: () => "moved" },
    click: () => "clicked",
    keyboard: { press: () => "pressed" },
    frames: () => [frame],
    frameLocator: () => ({ getByRole: () => locator, owner: () => locator }),
    context: () => context,
    waitForSelector: async () => locator,
    $: async () => locator,
    $$: async () => [locator],
  };
  return page as unknown as Page;
};

describe("the mouse guard (BQ-04 (a))", () => {
  it("throws on page.click, naming the API", () => {
    expect(() => guardPage(fakePage()).click("#x")).toThrow(ForbiddenPointerApiError);
    expect(() => guardPage(fakePage()).click("#x")).toThrow(/"page\.click"/);
  });

  it("throws on a locator click reached through a chain", () => {
    const p = guardPage(fakePage());
    expect(() => p.getByRole("button").first().click()).toThrow(
      /page\.getByRole\(\)\.first\(\)\.click/,
    );
  });

  it("guards a promise's awaited value: elementHandle, waitForSelector, $", async () => {
    const p = guardPage(fakePage());
    await expect(
      p
        .locator("a")
        .elementHandle()
        .then((h) => h?.click()),
    ).rejects.toThrow(ForbiddenPointerApiError);
    await expect(p.waitForSelector("a").then((h) => h.click())).rejects.toThrow(/click/);
    await expect(p.$("a").then((h) => h?.click())).rejects.toThrow(/click/);
  });

  it("guards each element of an array: locator.all(), $$, frames()", async () => {
    const p = guardPage(fakePage());
    const all = await p.locator("a").all();
    expect(() => all[0]?.click()).toThrow(/click/);
    const handles = await p.$$("a");
    expect(() => handles[0]?.click()).toThrow(/click/);
    expect(() => p.frames()[0]?.click("#x")).toThrow(/click/);
  });

  it("guards context().pages() and the frame's locators", () => {
    const p = guardPage(fakePage());
    expect(() => p.context().pages()[0]?.click("#x")).toThrow(/click/);
    expect(() => p.frames()[0]?.locator("a").click()).toThrow(/click/);
  });

  it("guards a frameLocator (it has no click of its own) and what it returns", () => {
    const p = guardPage(fakePage());
    expect(() => p.frameLocator("iframe").getByRole("button").click()).toThrow(/click/);
    expect(() => p.frameLocator("iframe").owner().click()).toThrow(/click/);
  });

  it("throws on any page.mouse member", () => {
    expect(() => guardPage(fakePage()).mouse.move(1, 2)).toThrow(/page\.mouse\.move/);
  });

  it("lets keyboard and navigation calls through", async () => {
    const p = guardPage(fakePage());
    expect(p.locator("a").press("Tab")).toBe("pressed");
    await expect(p.goto("/")).resolves.toBe("ok");
  });

  it("refuses a pointer-typed dispatchEvent but not a keyboard one", () => {
    const inner = { dispatchEvent: () => undefined };
    const p = guardPage({ locator: () => inner } as unknown as Page);
    expect(() => p.locator("a").dispatchEvent("pointerdown")).toThrow(
      /dispatchEvent\("pointerdown"\)/,
    );
    expect(() => p.locator("a").dispatchEvent("keydown")).not.toThrow();
  });
});

const stop = (key: string, name = key, visible = true): FocusStop => ({ key, name, visible });

describe("the trap detector (judgeFocusSequence)", () => {
  it("passes a loop that returns to its first stop", () => {
    const v = judgeFocusSequence([stop("a"), stop("b"), stop("c"), stop("a")], 20);
    expect(v).toEqual({ ok: true, stops: 3, failures: [] });
  });

  it("passes a loop that wraps out of the document", () => {
    expect(judgeFocusSequence([stop("a"), stop("b"), stop(WRAPPED, "")], 20).ok).toBe(true);
  });

  it("passes a screen with a single tab stop", () => {
    expect(judgeFocusSequence([stop("a"), stop("a")], 20).ok).toBe(true);
  });

  it("fails when focus stalls on one element", () => {
    const v = judgeFocusSequence([stop("a"), stop("b"), stop("b")], 20);
    expect(v.failures.join()).toContain("A11Y-K011");
  });

  it("fails when the loop never closes within N", () => {
    const v = judgeFocusSequence([stop("a"), stop("b"), stop("c")], 3);
    expect(v.failures.join()).toContain("A11Y-K014");
  });

  it("fails a stop with no accessible name, and one with no focus ring", () => {
    const v = judgeFocusSequence(
      [stop("a"), stop("b", "  "), stop("c", "C", false), stop("a")],
      20,
    );
    expect(v.failures).toHaveLength(2);
    expect(v.failures[0]).toContain("A11Y-K012");
    expect(v.failures[1]).toContain("A11Y-K013");
  });

  it("fails an empty sequence", () => {
    expect(judgeFocusSequence([], 5).failures.join()).toContain("A11Y-K010");
  });

  it("reads the name from an ARIA snapshot line", () => {
    expect(nameFromAriaLine('- button "Show \\"it\\""')).toBe('Show "it"');
    expect(nameFromAriaLine("- button")).toBe("");
  });
});

describe("the focus indicator (judgeFocusIndicator)", () => {
  const ring = (c: string) => ({
    outlineStyle: "solid",
    outlineWidth: "2px",
    outlineColor: c,
    boxShadow: "none",
  });

  it("parses rgb and rgba, with a slash or percentage alpha", () => {
    expect(parseRgba("rgb(1, 2, 3)")).toEqual([1, 2, 3, 1]);
    expect(parseRgba("rgba(1,2,3,0.5)")).toEqual([1, 2, 3, 0.5]);
    expect(parseRgba("rgb(1 2 3 / 50%)")).toEqual([1, 2, 3, 0.5]);
    expect(parseRgba("none")).toBeNull();
  });

  it("uses the token linter's contrastRatio (parity on a known pair)", () => {
    const r = judgeFocusIndicator(ring("rgb(0, 0, 0)"), "rgb(255, 255, 255)").ratio;
    expect(r).toBeCloseTo(contrastRatio("#000000", "#ffffff"), 10);
    expect(r).toBeCloseTo(21, 5);
  });

  it("fails an indicator under 3:1 and passes one at or over it", () => {
    expect(judgeFocusIndicator(ring("rgb(200, 200, 200)"), "rgb(255, 255, 255)").ok).toBe(false);
    expect(judgeFocusIndicator(ring("rgb(0, 95, 204)"), "rgb(255, 255, 255)").ok).toBe(true);
  });

  it("composites a translucent ring over the background before judging", () => {
    const faint = judgeFocusIndicator(ring("rgba(0, 0, 0, 0.1)"), "rgb(255, 255, 255)");
    expect(faint.present).toBe(true);
    expect(faint.ok).toBe(false);
  });

  it("falls back to the box-shadow when there is no outline, and reports none when neither", () => {
    const shadow = {
      outlineStyle: "none",
      outlineWidth: "0px",
      outlineColor: "rgb(0, 0, 0)",
      boxShadow: "rgb(0, 0, 0) 0px 0px 0px 2px",
    };
    expect(judgeFocusIndicator(shadow, "rgb(255, 255, 255)").ok).toBe(true);
    expect(judgeFocusIndicator({ ...shadow, boxShadow: "none" }, "rgb(255, 255, 255)")).toEqual({
      present: false,
      ratio: null,
      ok: false,
    });
  });
});

describe("the trap budget (BQ-07, PROPOSED)", () => {
  const tree = [
    "- main:",
    '  - button "A"',
    '  - link "B"',
    '  - button "C" [disabled]',
    '  - textbox "D"',
    "  - text: x",
  ].join("\n");

  it("counts focusable nodes and skips disabled ones", () => {
    expect(focusableCount(tree)).toBe(3);
  });

  it("is ceil(1.5 x stops) + 10, with no ceiling", () => {
    expect(trapBudget(tree)).toBe(15);
    expect(trapBudget(Array.from({ length: 100 }, () => '- button "x"').join("\n"))).toBe(160);
  });
});

describe("the polite budget (s6.2)", () => {
  it("allows one write per 2 s per field plus the opening write", () => {
    expect(politeBudget(0)).toBe(1);
    expect(politeBudget(2_000)).toBe(2);
    expect(politeBudget(2_001, 5)).toBe(15);
  });
});
