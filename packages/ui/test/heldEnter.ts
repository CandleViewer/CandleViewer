import { act } from "react";

/** A keyboard event as a browser dispatches one: bubbling, cancelable. */
const key = (type: "keydown" | "keyup", repeat: boolean): KeyboardEvent =>
  new KeyboardEvent(type, { key: "Enter", code: "Enter", repeat, bubbles: true, cancelable: true });

/**
 * A held Enter on a native button as a browser delivers it: a keydown, then `repeats` auto-repeat keydowns
 * (`repeat: true`), each activating the button (a click) unless its keydown was prevented, then the keyup. jsdom
 * gives a key no activation, and storybook/test's user-event marks no keydown of a held key as a repeat.
 */
export function holdEnter(button: HTMLElement, repeats: number): void {
  act(() => {
    for (let i = 0; i <= repeats; i += 1) {
      if (button.dispatchEvent(key("keydown", i > 0))) button.click();
    }
    button.dispatchEvent(key("keyup", false));
  });
}
