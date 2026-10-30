// @vitest-environment jsdom
import { useEffect, useLayoutEffect, type JSX, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { StoryContext } from "@storybook/react-vite";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mountAfterEffects, withMountSignal } from "../../.storybook/mountAfterEffects.js";
import preview from "../../.storybook/preview.js";

// The generated token CSS exists only after `build:tokens`; test/tokens-build checks those bundles.
vi.mock("../../.storybook/theme-bundles.js", () => ({}));

/**
 * @storybook/react-dom-shim 10.6.2's `renderElement` outside an act environment (a production build): the
 * mount resolves in a layout effect, when the story's first commit lays out, before its passive effects.
 */
function WithCallback(props: { readonly callback: () => void; readonly children: ReactNode }) {
  const { callback, children } = props;
  useLayoutEffect(() => callback(), [callback]);
  return <>{children}</>;
}

/** A story whose render outruns React's 5 ms slice and whose effect marks its canvas. */
function Slow({ canvas }: { readonly canvas: HTMLElement }): JSX.Element {
  const until = performance.now() + 8;
  while (performance.now() < until) {
    // a commit this slow makes React's scheduler yield before the commit's passive effects
  }
  useEffect(() => {
    canvas.dataset["effects"] = "ran";
  }, [canvas]);
  return <p>story</p>;
}

const canvas = { story: "canvas" };
let root: Root | undefined;

/** The slice of a story context a mount reads, with Storybook's runtime `renderToCanvas`. */
function storyContext(render: (host: HTMLElement) => Promise<void>): {
  readonly host: HTMLElement;
  readonly context: StoryContext;
} {
  const host = document.body.appendChild(document.createElement("div"));
  const context = { canvasElement: host, canvas, renderToCanvas: () => render(host) };
  return { host, context: context as unknown as StoryContext };
}

/** The decorated story rendered as Storybook's production mount renders it. */
const slowStory = (host: HTMLElement): Promise<void> =>
  new Promise((resolve) => {
    root = createRoot(host);
    const story = withMountSignal(() => <Slow canvas={host} />, {
      canvasElement: host,
    } as unknown as StoryContext);
    root.render(<WithCallback callback={resolve}>{story}</WithCallback>);
  });

afterEach(() => {
  root?.unmount();
  root = undefined;
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("a play's start in a production build", () => {
  it("would come before the story's effects: React yields after a slow commit (the renderer's own mount)", async () => {
    const { host, context } = storyContext(slowStory);
    const rendererMount = async (): Promise<unknown> => {
      await (context as unknown as { renderToCanvas: () => Promise<void> }).renderToCanvas();
      return context.canvas;
    };
    await expect(rendererMount()).resolves.toBe(canvas);
    expect(host.dataset["effects"]).toBeUndefined();
  });

  it("comes after them: the preview's mount waits for its outermost decorator's effect", async () => {
    expect(preview.mount).toBe(mountAfterEffects);
    const decorators = [preview.decorators ?? []].flat();
    expect(decorators.at(-1)).toBe(withMountSignal);
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { host, context } = storyContext(slowStory);
    await expect(mountAfterEffects(context)()).resolves.toBe(canvas);
    expect(host.dataset["effects"]).toBe("ran");
    expect(vi.getTimerCount()).toBe(0); // its fallback timer is gone, never a timer the capture waits on
  });

  it("keeps the story's own function for mount(null), as the renderer's own mount does", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { context } = storyContext(async () => undefined);
    const own = context as unknown as { originalStoryFn: unknown };
    const story = (): string => "the story";
    own.originalStoryFn = story;
    const mounted = mountAfterEffects(context)(null as never);
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(mounted).resolves.toBe(canvas);
    expect(own.originalStoryFn).toBe(story);
  });

  it("goes ahead after 1 s when no effect ever signals (a story that threw while rendering)", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { context } = storyContext(async () => undefined);
    let done = false;
    const mounted = mountAfterEffects(context)().then((value) => {
      done = true;
      return value;
    });
    await vi.advanceTimersByTimeAsync(999);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(mounted).resolves.toBe(canvas);
  });
});
