import keymapData from "./keymap.json";

export type KeymapContext =
  | "Global"
  | "Auth"
  | "Workspace"
  | "Chart"
  | "DOM"
  | "Ticket"
  | "Positions"
  | "Replay"
  | "Rules"
  | "Admin"
  | "Settings";

export interface KeymapCommand {
  readonly id: string;
  readonly label: string;
  readonly context: KeymapContext;
  readonly defaultBinding: string;
  readonly destructive: boolean;
  readonly validWhen: string;
  readonly visibleControl: boolean | string;
  readonly screens?: readonly string[];
  readonly shadows?: readonly { readonly command: string; readonly rationale: string }[];
  readonly reservedOverride?: { readonly rationale: string };
}

interface KeymapFile {
  readonly safetyModifierDefault: boolean;
  readonly commands: readonly KeymapCommand[];
}

const file = keymapData as unknown as KeymapFile;

/** Default keymap: the single source of truth, validated by scripts/keymap_lint.py (E49-T04). */
export const KEYMAP: readonly KeymapCommand[] = file.commands;
export const SAFETY_MODIFIER_DEFAULT: boolean = file.safetyModifierDefault;

const BY_ID = new Map(KEYMAP.map((c) => [c.id, c]));

export function getCommand(id: string): KeymapCommand | undefined {
  return BY_ID.get(id);
}

/** Default binding for a command id; throws on unknown ids so typos fail loudly. */
export function bindingFor(id: string): string {
  const c = BY_ID.get(id);
  if (!c) throw new Error(`Unknown keymap command: ${id}`);
  return c.defaultBinding;
}

const KEY_NAMES: Readonly<Record<string, string>> = {
  Escape: "Esc",
  Delete: "Del",
  " ": "Space",
  ArrowLeft: "←",
  ArrowRight: "→",
  ArrowUp: "↑",
  ArrowDown: "↓",
};

export interface KeyEventLike {
  readonly key: string;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly altKey: boolean;
  readonly shiftKey: boolean;
}

/** Normalise a KeyboardEvent to the canonical binding string (Ctrl+Alt+Shift+Key; Cmd folds to Ctrl). */
export function eventBinding(e: KeyEventLike): string {
  const k = KEY_NAMES[e.key] ?? (e.key.length === 1 ? e.key.toUpperCase() : e.key);
  const mods = [
    e.ctrlKey || e.metaKey ? "Ctrl" : "",
    e.altKey ? "Alt" : "",
    e.shiftKey ? "Shift" : "",
  ].filter(Boolean);
  return [...mods, k].join("+");
}

/** The digit a binding string supplies to a range binding (`Alt+1..9`); null when it is not one. */
export function rangeDigit(binding: string, got: string): number | null {
  const m = /^(.*?)(\d)\.\.(\d)$/.exec(binding);
  if (!m) return null;
  const [, prefix = "", lo = "0", hi = "0"] = m;
  if (!got.startsWith(prefix)) return null;
  const d = got.slice(prefix.length);
  return /^\d$/.test(d) && Number(d) >= Number(lo) && Number(d) <= Number(hi) ? Number(d) : null;
}

/** True when the event matches the command's default binding (digit ranges `1..9` supported). */
export function matchesCommand(id: string, e: KeyEventLike): boolean {
  const binding = bindingFor(id);
  const got = eventBinding(e);
  return got === binding || rangeDigit(binding, got) !== null;
}
