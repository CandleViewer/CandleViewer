import { useEffect, useRef, type RefObject } from "react";

/**
 * Focus follows an in-place view change (A11Y-P-02, CMP-200; WCAG 2.4.3): when `view` changes, the
 * element carrying the returned ref (the new view's heading or status) takes focus, so a screen
 * reader hears it and a keyboard user is not dropped on `body`. The first value is left alone, so
 * an autofocused control or the shell's route focus keeps its move. Keyed on the previous value, so
 * StrictMode's double effect run cannot count as a change. A target that is not focusable takes
 * `tabindex="-1"` for the move and loses it on blur, as `useRouteFocus` does. Focus is only taken
 * from `body` (the old view's control just unmounted) or from inside the target's `main`: a user who
 * has already moved to a control elsewhere is never pulled away.
 */
export function useFocusOnView<T extends HTMLElement = HTMLHeadingElement>(
  view: string,
): RefObject<T> {
  const ref = useRef<T>(null);
  const previous = useRef(view);
  useEffect(() => {
    if (previous.current === view) return;
    previous.current = view;
    const target = ref.current;
    if (target === null) return;
    const active = document.activeElement;
    const main = target.closest("main");
    if (active !== null && active !== document.body && !(main?.contains(active) ?? false)) return;
    if (!target.hasAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
      target.addEventListener("blur", () => target.removeAttribute("tabindex"), { once: true });
    }
    target.focus();
  }, [view]);
  return ref;
}
