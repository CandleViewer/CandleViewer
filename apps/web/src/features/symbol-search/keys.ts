/**
 * E08-D05 §8's key stop, one source for SCR-102 and SCR-041: a symbol surface's React root stops every key typed in
 * it, so the window keymap never runs or reports one, except a Global chord, which closes the surface and goes on to
 * the keymap. A chord is Ctrl or Alt, or a function key (A-D05-2), so a printable key, `/` included, stays in the
 * field even once `/` is a Global command.
 */
import type { KeyboardEvent } from "react";
import { KEYMAP, eventBinding } from "../../keymap/keymap";
import { getBindings } from "../../keymap/profile";

/** A Global command's binding, as the live profile has it, typed as Ctrl or Alt and a key, or a function key. */
export function globalChord(event: KeyboardEvent): boolean {
  const got = eventBinding(event);
  if (!/^(Ctrl|Alt)\+|^F\d{1,2}$/.test(got)) return false;
  const bound = getBindings();
  return KEYMAP.some(
    (c) => c.context === "Global" && (bound.get(c.id) ?? c.defaultBinding) === got,
  );
}

/** The surface root's keydown: a Global chord closes it and goes on; any other key stops here. */
export function stopKeys(event: KeyboardEvent, close: () => void): void {
  if (globalChord(event)) close();
  else event.stopPropagation();
}
