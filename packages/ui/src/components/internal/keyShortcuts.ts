/** The keymap's display words that `aria-keyshortcuts` spells differently (UI Events key values). */
const ARIA_KEYS: Readonly<Record<string, string>> = {
  Ctrl: "Control",
  Cmd: "Meta",
  Opt: "Alt",
  Del: "Delete",
  Esc: "Escape",
  Ins: "Insert",
  PgUp: "PageUp",
  PgDn: "PageDown",
  Return: "Enter",
  "↑": "ArrowUp",
  "↓": "ArrowDown",
  "←": "ArrowLeft",
  "→": "ArrowRight",
};

/** The keys as an `aria-keyshortcuts` value (`["Ctrl", "D"]` → "Control+D"); undefined when unbound. */
export const keyShortcuts = (keys: readonly string[] | undefined): string | undefined => {
  const bound = (keys ?? []).map((key) => key.trim()).filter((key) => key !== "");
  if (bound.length === 0) return undefined;
  return bound.map((key) => (Object.hasOwn(ARIA_KEYS, key) ? ARIA_KEYS[key] : key)).join("+");
};
