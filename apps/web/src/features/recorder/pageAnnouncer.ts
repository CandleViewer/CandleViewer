/**
 * SCR-140's one voice for what a press says (E16-D02 §10.5; E16-D06 R-5, SR-14, BG-05): a T2
 * reason, a refusal at the point of action, the grid's and the filters' lines, each once and
 * politely through the shell announcer (`features/app-shell/announcer.tsx`), never the summary
 * region. The key is forgotten first, so the same sentence pressed twice is said twice.
 */
import { announce, forget } from "../app-shell/announcer";

const KEY = "recorder:press";

export function sayPolitely(text: string): void {
  const words = text.trim();
  if (words === "") return;
  forget(KEY);
  announce("polite", words, KEY);
}
