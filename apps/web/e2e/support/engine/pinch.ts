// E11-Q02 (#444): a two-finger pinch about `center`, spreading from `d0` to `d1` px apart over
// `frames` animation frames. Playwright's touchscreen only taps, so the pointers are dispatched in
// the page (as flick.ts does); each frame moves both fingers, so the engine sees a gesture, not a jump.
import type { Page } from "@playwright/test";

export async function pinch(
  page: Page,
  center: { readonly x: number; readonly y: number },
  d0: number,
  d1: number,
  frames: number,
): Promise<void> {
  await page.evaluate(
    async ({ x, y, a, b, n }) => {
      const el = document.elementFromPoint(x, y);
      if (el === null) throw new Error("pinch: nothing under the fingers");
      const fire = (type: string, id: number, px: number, buttons: number): void => {
        el.dispatchEvent(
          new PointerEvent(type, {
            bubbles: true,
            cancelable: true,
            pointerId: id,
            pointerType: "touch",
            isPrimary: id === 1,
            buttons,
            clientX: px,
            clientY: y,
          }),
        );
      };
      const frame = (): Promise<number> => new Promise((r) => requestAnimationFrame(r));
      fire("pointerdown", 1, x - a / 2, 1);
      fire("pointerdown", 2, x + a / 2, 1);
      for (let i = 1; i <= n; i += 1) {
        await frame();
        const d = a + ((b - a) * i) / n;
        fire("pointermove", 1, x - d / 2, 1);
        fire("pointermove", 2, x + d / 2, 1);
      }
      await frame();
      fire("pointerup", 1, x - b / 2, 0);
      fire("pointerup", 2, x + b / 2, 0);
    },
    { x: center.x, y: center.y, a: d0, b: d1, n: frames },
  );
}
