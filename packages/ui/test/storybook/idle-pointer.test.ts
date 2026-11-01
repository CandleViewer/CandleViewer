// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { inVitestTester, muteIdlePointer, stopTrusted } from "../../.storybook/idlePointer.js";
import preview from "../../.storybook/preview.js";

// The generated token CSS exists only after `build:tokens`; test/tokens-build checks those bundles.
vi.mock("../../.storybook/theme-bundles.js", () => ({}));

const tester = globalThis as { __vitest_browser__?: unknown };
const MUTED = [
  "pointerover",
  "pointerout",
  "pointerenter",
  "pointerleave",
  "pointermove",
  "mouseover",
  "mouseout",
  "mouseenter",
  "mouseleave",
  "mousemove",
];

/** An event as `stopTrusted` sees it. A page cannot dispatch a trusted one, so this is its shape alone. */
const seen = (isTrusted: boolean): { readonly event: Event; readonly stop: () => void } => {
  const stop = vi.fn();
  return { event: { isTrusted, stopImmediatePropagation: stop } as unknown as Event, stop };
};

afterEach(() => {
  delete tester.__vitest_browser__;
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("the runner's idle pointer while a play runs (#5274)", () => {
  it("stops a trusted event, the browser's own from the idle pointer, and lets a play's synthetic one pass", () => {
    const fromRunner = seen(true);
    stopTrusted(fromRunner.event);
    expect(fromRunner.stop).toHaveBeenCalledOnce();
    const fromPlay = seen(false);
    stopTrusted(fromPlay.event);
    expect(fromPlay.stop).not.toHaveBeenCalled();
  });

  it("listens ahead of the story, in the capture phase, for each move and boundary event, and undoes it all", () => {
    const target = new EventTarget();
    const add = vi.spyOn(target, "addEventListener");
    const remove = vi.spyOn(target, "removeEventListener");
    const undo = muteIdlePointer(target);
    expect(add.mock.calls).toEqual(MUTED.map((type) => [type, stopTrusted, true]));
    undo();
    expect(remove.mock.calls).toEqual(MUTED.map((type) => [type, stopTrusted, true]));
  });

  it("leaves a play's synthetic hover reaching the story while muted", () => {
    const undo = muteIdlePointer();
    const cell = document.body.appendChild(document.createElement("td"));
    const reached = vi.fn();
    cell.addEventListener("pointerover", reached);
    cell.dispatchEvent(new Event("pointerover", { bubbles: true }));
    undo();
    expect(reached).toHaveBeenCalledOnce();
  });

  it("mutes only in Vitest's tester: Storybook itself keeps a person's pointer", async () => {
    const hook = preview.beforeEach;
    if (typeof hook !== "function") throw new Error("the preview's beforeEach is one function");
    const context = {} as Parameters<typeof hook>[0];
    expect(inVitestTester()).toBe(false);
    expect(await hook(context)).toBeUndefined();

    tester.__vitest_browser__ = true;
    expect(inVitestTester()).toBe(true);
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const undo = await hook(context);
    expect(add).toHaveBeenCalledTimes(MUTED.length);
    expect(typeof undo).toBe("function");
    if (typeof undo === "function") await undo();
    expect(remove).toHaveBeenCalledTimes(MUTED.length);
  });
});
