// E11-Q02 (#444, Technical notes): a drag with a physically plausible velocity. Two events a frame
// apart read as an absurd speed and test nothing, so the gesture is dispatched in the page on the
// animation-frame cadence: one `pointermove` per frame over `durationMs`, the pointer released after
// the last. Waiting on frames (not timers) keeps it sleep-free.
import type { Page } from "@playwright/test";

/** Dispatches pointerdown at (x, y), per-frame moves totalling (dx, dy) over `durationMs`, pointerup. */
export async function flick(
  page: Page,
  from: { readonly x: number; readonly y: number },
  delta: { readonly dx: number; readonly dy: number },
  durationMs: number,
  holdFrames = 0,
): Promise<void> {
  await page.evaluate(
    async ({ x, y, dx, dy, ms, hold }) => {
      const el = document.elementFromPoint(x, y);
      if (el === null) throw new Error("flick: nothing under the pointer");
      const fire = (type: string, px: number, py: number, buttons: number): void => {
        el.dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            cancelable: true,
            composed: true,
            pointerId: 1,
            pointerType: "mouse",
            isPrimary: true,
            button: 0,
            buttons,
            clientX: px,
            clientY: py,
          }),
        );
      };
      const nextFrame = (): Promise<number> => new Promise((r) => requestAnimationFrame(r));
      fire("pointerdown", x, y, 1);
      const start = await nextFrame();
      for (;;) {
        const t = await nextFrame();
        const k = Math.min(1, (t - start) / ms);
        fire("pointermove", x + dx * k, y + dy * k, 1);
        if (k >= 1) break;
      }
      // Held still before the release: no velocity, no coast.
      for (let i = 0; i < hold; i += 1) await nextFrame();
      fire("pointerup", x + dx, y + dy, 0);
    },
    { x: from.x, y: from.y, dx: delta.dx, dy: delta.dy, ms: durationMs, hold: holdFrames },
  );
}
