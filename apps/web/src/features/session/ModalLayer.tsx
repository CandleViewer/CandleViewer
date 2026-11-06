import { useLayoutEffect, useState, type JSX, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { scrim } from "./chrome";

/** The first SCR-005 layer in `body`: the lock, its sign-out confirm or the expiry card. */
const LOCKED = 'body > [data-cv-layer] > [data-keymap-context="Locked"]';

/**
 * A session dialog's scrim (#5561), in a layer of its own at the end of `body`, marked a layer
 * (`data-cv-layer`) as CMP-043's layer roots are. Last: a CMP-043 layer opened before it paints under
 * it (CMP-043 stacks by document order, with no z-index). A layer: an open CMP-043 dialog's inert page
 * spares it (`inertOutside.ts`). A dialog that is not an SCR-005 card and opens while one is up goes
 * in just under it, so the lock stays on top, as before (SCR-006 raised while locked waits under it).
 * The card stays the scrim's child, so `useModalKeys` still refuses a press on the scrim. Temporary
 * chrome (#2725), gone with the re-base on CMP-043.
 */
export function ModalLayer({
  children,
  "data-keymap-context": context,
}: {
  readonly children: ReactNode;
  /** `Locked` on the SCR-005 cards: no global shortcut runs while one is in the document (KeymapHost). */
  readonly "data-keymap-context"?: string;
}): JSX.Element {
  const [layer] = useState(() => {
    const root = document.createElement("div");
    root.setAttribute("data-cv-layer", "");
    return root;
  });
  // before the dialog's own layout effects, so it is in the document when the modals below are held
  useLayoutEffect(() => {
    const lock = context === "Locked" ? null : document.querySelector(LOCKED);
    document.body.insertBefore(layer, lock?.parentElement ?? null);
    return () => layer.remove();
  }, [layer, context]);
  return createPortal(
    <div data-keymap-context={context} style={scrim}>
      {children}
    </div>,
    layer,
  );
}
