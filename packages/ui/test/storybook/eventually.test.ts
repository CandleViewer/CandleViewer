// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { eventually, shownWith } from "../../.storybook/eventually.js";

/**
 * The page's clock: `performance.now()` follows the fake timers, plus every hold so far. A hold is a long task
 * elsewhere on the runner's one main thread: the clock moves on and no timer fires until it ends.
 */
let held = 0;

beforeEach(() => {
  held = 0;
  vi.useFakeTimers({ toFake: ["setTimeout", "Date"], now: 0 });
  vi.spyOn(performance, "now").mockImplementation(() => Date.now() + held);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("eventually: a play's wait counted in the page's run time (#5274)", () => {
  it("returns what it finds without waiting", async () => {
    await expect(eventually("the echo", () => "echo")).resolves.toBe("echo");
  });

  it("spends none of its budget while the thread is held: the echo drawn after a 3.2 s hold is found", async () => {
    let drawn = false;
    const wait = eventually("the echo", () => (drawn ? "echo" : null), 3000);
    await vi.advanceTimersByTimeAsync(250);
    held += 3200;
    // The late poll, 3.5 s after the hover by the wall clock: the echo is due, not drawn yet.
    await vi.advanceTimersByTimeAsync(50);
    drawn = true;
    await vi.advanceTimersByTimeAsync(50);
    await expect(wait).resolves.toBe("echo");
  });

  it("gives up once its budget of run time is spent, naming the longest hold", async () => {
    const wait = eventually("the echo", () => null, 1000);
    const settled = expect(wait).rejects.toThrow(
      "the echo: not there after 1000 ms of run time (the longest hold was 3200 ms)",
    );
    await vi.advanceTimersByTimeAsync(100);
    held += 3200;
    await vi.advanceTimersByTimeAsync(1000);
    await settled;
  });
});

describe("shownWith: the shown CMP-016 surface once it reads the words", () => {
  it("passes over a hidden surface and one with other words, and returns the one that reads them", () => {
    const tip = document.createElement("div");
    tip.dataset["cmp"] = "CMP-016";
    tip.hidden = true;
    tip.textContent = "Move Funding % up";
    document.body.append(tip);
    expect(shownWith('[data-cmp="CMP-016"]', "Move Funding % up")).toBeNull();
    tip.hidden = false;
    expect(shownWith('[data-cmp="CMP-016"]', "Move Last up")).toBeNull();
    expect(shownWith('[data-cmp="CMP-016"]', "Move Funding % up")).toBe(tip);
  });
});
