import { announce, forget } from "../app-shell/announcer";
import type { Say } from "./episodes";

let seq = 0;

/**
 * Writes into the shell's one live-region pair (E17-D02 §11); this page owns no region of its own. The
 * announcer says a key once, so a fresh key per press lets a repeat press say its reason again.
 */
export const sayToShell: Say = (politeness, text, key) => {
  announce(politeness, text, key);
};

/** One polite line per call, e.g. a gated control's reason (G-T2.3), say-once per press. */
export function politeOnce(text: string): void {
  seq += 1;
  const key = `connectivity:press:${seq}`;
  announce("polite", text, key);
  forget(key);
}
