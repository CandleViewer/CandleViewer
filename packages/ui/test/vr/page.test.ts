// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cellProblem, storyState, type StoryState } from "../../vr/page.js";

type Preview = {
  currentRender?: { phase?: string; story?: { storyGlobals?: object } };
  storyStoreValue?: { userGlobals: { get: () => object } };
};
/** Storybook's preview global, which the DOM types do not declare. */
const preview = (value: Preview | undefined): void => {
  (window as unknown as { __STORYBOOK_PREVIEW__: Preview | undefined }).__STORYBOOK_PREVIEW__ =
    value;
};
/** Storybook's addons channel as the preview leaves it: the last payload of each event it emitted. */
const channel = (events: Record<string, unknown[]> | undefined): void => {
  const value = events && { last: (event: string) => events[event] };
  (window as unknown as { __STORYBOOK_ADDONS_CHANNEL__: unknown }).__STORYBOOK_ADDONS_CHANNEL__ =
    value;
};
const finished = (): void => preview({ currentRender: { phase: "finished", story: {} } });

afterEach(() => {
  preview(undefined);
  channel(undefined);
  document.body.className = "";
  document.body.innerHTML = "";
});

describe("the story's settled state", () => {
  it("keeps the capture waiting until Storybook finished the render, play function and afterEach included", () => {
    expect(storyState()).toBeNull();
    for (const phase of [
      "loading",
      "rendering",
      "playing",
      "played",
      "completing",
      "completed",
      "afterEach",
    ]) {
      preview({ currentRender: { phase } });
      expect(storyState()).toBeNull();
    }
  });

  it("reports a finished story with the URL's globals and those it pins itself", () => {
    const userGlobals = { get: () => ({ theme: "dark", density: "compact", motion: "on" }) };
    preview({
      currentRender: { phase: "finished", story: { storyGlobals: { theme: "light" } } },
      storyStoreValue: { userGlobals },
    });
    expect(storyState()).toEqual({
      status: "rendered",
      message: "",
      globals: { theme: "dark", density: "compact", motion: "on" },
      pinned: { theme: "light" },
    });
    preview({ currentRender: { phase: "finished", story: {} } });
    expect(storyState()).toEqual({ status: "rendered", message: "", globals: {}, pinned: {} });
  });

  it("reports Storybook's error display with its message, before any phase", () => {
    document.body.innerHTML =
      '<div id="error-message">Boom</div><div id="error-stack">at Story</div>';
    document.body.className = "sb-show-errordisplay";
    preview({ currentRender: { phase: "finished" } });
    expect(storyState()).toMatchObject({ status: "errored", message: "Boom at Story" });
  });

  it("reports a story id Storybook does not know", () => {
    document.body.className = "sb-show-nopreview";
    expect(storyState()).toMatchObject({ status: "missing" });
  });

  it("names a play function that threw, though Storybook 10.6 still reaches finished", () => {
    finished();
    channel({
      playFunctionThrewException: [
        { name: "AssertionError", message: "expected element to have focus", stack: "at play" },
      ],
      storyFinished: [{ storyId: "a-b--one", status: "success", reporters: [] }],
    });
    expect(storyState()).toMatchObject({
      status: "play-failed",
      message: "AssertionError: expected element to have focus",
    });
  });

  it("names errors a play left unhandled, and a story Storybook finished as an error", () => {
    finished();
    channel({
      unhandledErrorsWhilePlaying: [
        [
          { name: "TypeError", message: "x is undefined" },
          { name: "Error", message: "late" },
        ],
      ],
    });
    expect(storyState()).toMatchObject({
      status: "play-failed",
      message: "unhandled while playing: TypeError: x is undefined (and 1 more)",
    });
    channel({
      storyFinished: [{ status: "error", reporters: [{ type: "a11y", status: "failed" }] }],
    });
    expect(storyState()).toMatchObject({
      status: "play-failed",
      message: "Storybook finished the story with status error (failed: a11y)",
    });
    channel({ storyFinished: [{ status: "success", reporters: [] }] });
    expect(storyState()).toMatchObject({ status: "rendered" });
  });
});

describe("a cell Storybook did not render", () => {
  const state = (status: StoryState["status"], message = ""): StoryState => ({
    status,
    message,
    globals: {},
    pinned: {},
  });

  it("fails by name, a failed play never a screenshot of a partial state", () => {
    expect(cellProblem(state("rendered"))).toBeUndefined();
    expect(cellProblem(state("play-failed", "AssertionError: no focus"))).toBe(
      "play function failed: AssertionError: no focus",
    );
    expect(cellProblem(state("errored", "Boom at Story"))).toBe(
      "Storybook showed its error display: Boom at Story",
    );
    expect(cellProblem(state("missing", "Storybook has no story with this id"))).toBe(
      "Storybook has no story with this id",
    );
  });
});
