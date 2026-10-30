import { useEffect, type JSX, type ReactNode } from "react";
import type { Decorator, Preview } from "@storybook/react-vite";

/**
 * A play starts after its story's mount effects (E05-T04). Storybook's React renderer resolves a mount when
 * the story's first commit lays out. Under act (the storybook Vitest project, `storybook dev`) that commit's
 * effects have run by then; a production build has no act, and React 18 runs a commit's passive effects in a
 * later task whenever the commit outran its 5 ms slice. Then a play's first step raced them: before the
 * theme runtime applied the cell's theme and density, a checkbox took its `indeterminate` state, or a
 * context menu bound its listener. Passive effects run children first, so the outermost decorator's effect
 * runs after every other effect of the commit; the mount waits for it, then one more task for the renders
 * those effects scheduled. A story that throws while rendering never commits it, so the wait ends after
 * `CAP_MS`.
 */
const CAP_MS = 1_000;

/** The waiting mount of each canvas, called by the decorator's effect. */
const waiting = new WeakMap<Element, () => void>();

function MountSignal(props: {
  readonly canvas: Element | undefined;
  readonly children: ReactNode;
}): JSX.Element {
  const { canvas, children } = props;
  useEffect(() => {
    if (canvas === undefined) return;
    waiting.get(canvas)?.();
    waiting.delete(canvas);
  });
  return <>{children}</>;
}

/** The outermost decorator (preview.ts lists it last): its effect is the mount's signal. */
export const withMountSignal: Decorator = (Story, { canvasElement }) => (
  <MountSignal canvas={canvasElement ?? undefined}>
    <Story />
  </MountSignal>
);

/** One trip through the task queue, behind any task the effects posted (React's scheduler included). */
const nextTask = (): Promise<void> =>
  new Promise((resolve) => {
    const { port1, port2 } = new MessageChannel();
    port1.onmessage = () => {
      port1.close();
      port2.close();
      resolve();
    };
    port2.postMessage(null);
  });

/**
 * The React renderer's mount (Storybook 10.6: set the story function, render, return the canvas), with the
 * wait above between the render and the play. `renderToCanvas` is on every story context at run time,
 * though Storybook's context type leaves it out.
 */
export const mountAfterEffects: NonNullable<Preview["mount"]> = (context) => async (ui) => {
  // `!= null`, as the renderer's own mount: `mount(null)` keeps the story's function.
  if (ui != null) context.originalStoryFn = () => ui;
  const canvas: Element | undefined = context.canvasElement ?? undefined;
  // Registered before the render: under act the effect runs inside `renderToCanvas`.
  const effects = new Promise<void>((resolve) => {
    if (canvas === undefined) {
      resolve(); // no canvas, no signal to wait for
    } else {
      const cap = setTimeout(resolve, CAP_MS);
      waiting.set(canvas, () => {
        clearTimeout(cap);
        resolve();
      });
    }
  });
  await (context as unknown as { renderToCanvas: () => Promise<void> }).renderToCanvas();
  await effects;
  if (canvas !== undefined) waiting.delete(canvas);
  await nextTask();
  return context.canvas;
};
