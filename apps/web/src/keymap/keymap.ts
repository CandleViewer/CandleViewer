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
  | "Settings"
  /** SCR-100's panel (E08-D07 §6.2). */
  | "Watchlist";

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
  /** The contexts where its binding is live (#305); default: its own context. */
  readonly focusContexts?: readonly KeymapContext[];
  /**
   * `false` marks a stepper (zoom, step, cycle, reorder, undo), which a held key repeats. Every other command runs once
   * per press (E10-D04 G-07; WCAG 2.3.1, A11Y-305A-02), and a dangerous one always does.
   */
  readonly ignoreRepeat?: boolean;
  /** Its bare key runs in a text field too (E08-D05 A-D05-2: `ticket.clear` Esc, `global.auth.submit` Enter). */
  readonly allowInEditable?: boolean;
  /** `false` keeps it out of SCR-113 (`keymap_lint.py` then wants an `editableException`). */
  readonly editable?: boolean;
  /** The dangerous set's commands: a rebind is audited (#305, D10; SEC-305A-01). */
  readonly audited?: boolean;
  /**
   * The dangerous set's commands: the command declares that its handler opens the confirm flow (E30 SCR-076, E39
   * CMP-044); the registry runs none (BQ-5; `22` `confirm`). On an arm toggle it means the arming flow: a disarm never
   * confirms.
   */
  readonly confirm?: boolean;
  /**
   * An order entry `22`'s `ArmToken` forces the arm on (BQ-5; `requires_arm`): inert while the session reads unarmed.
   * Never a protective command, whose cancel, close or stop no arm may hold back (C-2.6).
   */
  readonly requiresArm?: boolean;
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

/**
 * BQ-3's dangerous set (#305 ruling of record; `05` §3.3 rule 2; AC5): the shipped destructive commands, `ticket.submit`
 * and the arm toggles. Each refuses a single unmodified letter, with no acknowledgement to lift it, and runs once per
 * press. Its membership lives here only: a ruling that takes the protective commands (cancel, close) out edits this.
 */
export const DANGEROUS_COMMANDS: ReadonlySet<string> = new Set([
  "chart.delete_drawing",
  "rules.delete",
  "dom.cancel_all",
  "positions.close",
  "positions.close_all",
  "ticket.submit",
  "dom.arm",
  "ticket.arm",
]);

export const isDangerous = (c: KeymapCommand): boolean => DANGEROUS_COMMANDS.has(c.id);
/** BQ-5's arm set: the five order entries `keymap.json` declares `requiresArm` on (the contract pin holds them). */
export const requiresArm = (c: KeymapCommand): boolean => c.requiresArm === true;

/** A single unmodified letter (AC5); Shift only picks its capital, so `Shift+Y` is one too (A-D05-2's bare key). */
export function isSingleLetter(binding: string): boolean {
  return /^(?:Shift\+)?\p{L}$/u.test(binding);
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

/** What the dispatcher reads of a key press: a DOM or a React `KeyboardEvent` satisfies it. */
export interface KeyEventLike {
  readonly key: string;
  /** The physical key (`Digit1`); a synthetic event may leave it out. */
  readonly code?: string;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly altKey: boolean;
  readonly shiftKey: boolean;
  /** Key auto-repeat: the key is held down. */
  readonly repeat?: boolean;
  /** The key belongs to an IME composition. */
  readonly isComposing?: boolean;
  /** 229 marks a key an IME took, such as Safari's Enter that ends a composition with `isComposing` false. */
  readonly keyCode?: number;
  /** A handler before the window's already took the key. */
  readonly defaultPrevented?: boolean;
  /** Where the key was typed: a text field keeps its bare keys (A-D05-2). */
  readonly target?: EventTarget | null;
}

const DIGIT_CODE = /^Digit(\d)$/;
const LETTER_CODE = /^Key([A-Z])$/;

/**
 * The key of a binding, in `keymap_lint.py`'s grammar, and whether Shift is part of the chord (#305, D5). A named key
 * or a letter keeps Shift (`Shift+Tab`, `Ctrl+Shift+A`). A digit or a punctuation mark is the character the layout
 * typed, so the Shift that selected it folds away: US `+` (Shift+=), German `/` (Shift+7), AZERTY `1` (Shift+&). A
 * chord (Ctrl, Cmd or Alt) reads its key (`event.code`) where the character is no use to a binding: on the digit row
 * without Shift, anything but a digit (AZERTY `Alt+&` and `Ctrl+-` are `Alt+1` and `Ctrl+6`, as the row's own digit
 * chords); on a letter key, anything but a Latin letter (Russian `Ctrl+С` is `Ctrl+C`). macOS Option and AltGr (Ctrl+
 * Alt on Windows) compose characters on those keys: Option+F types `ƒ` and reads `Alt+F`, Option+7 types `|` on a
 * German Mac and reads `Alt+7`; AltGr+8 types `[` on German Windows and reads `Ctrl+Alt+8`, so `[` `]` need a remap
 * there. In a text field any such composed character is typing (`composesCharacter`).
 */
function keyPart(e: KeyEventLike): { readonly key: string; readonly shift: boolean } {
  const named = KEY_NAMES[e.key];
  if (named !== undefined) return { key: named, shift: e.shiftKey };
  const chord = e.ctrlKey || e.metaKey || e.altKey;
  const digit = DIGIT_CODE.exec(e.code ?? "")?.[1];
  if (chord && digit !== undefined && !e.shiftKey && !/^\d$/.test(e.key)) {
    return { key: digit, shift: false };
  }
  const letter = LETTER_CODE.exec(e.code ?? "")?.[1];
  if (chord && letter !== undefined && !/^[a-z]$/i.test(e.key)) {
    return { key: letter, shift: e.shiftKey };
  }
  if (e.key.length !== 1) return { key: e.key, shift: e.shiftKey };
  const upper = e.key.toUpperCase();
  const isLetter = upper !== e.key.toLowerCase();
  return { key: upper.length === 1 ? upper : e.key, shift: e.shiftKey && isLetter };
}

/**
 * An Alt chord that types a character of its own on a digit or letter key (macOS Option, AltGr): Option+7 is `|` on a
 * German Mac, AltGr+Q `@` on German Windows. In a text field that is typing, never a shortcut (CR-305A-03).
 */
export function composesCharacter(e: KeyEventLike): boolean {
  if (!e.altKey || (e.key.length !== 1 && e.key !== "Dead")) return false;
  if (DIGIT_CODE.test(e.code ?? "")) return !/^\d$/.test(e.key);
  return LETTER_CODE.test(e.code ?? "") && !/^[a-z]$/i.test(e.key);
}

/** Normalise a key press to its canonical binding (Ctrl+Alt+Shift+Key; Cmd folds to Ctrl). */
export function eventBinding(e: KeyEventLike): string {
  const { key, shift } = keyPart(e);
  const mods = [
    e.ctrlKey || e.metaKey ? "Ctrl" : "",
    e.altKey ? "Alt" : "",
    shift ? "Shift" : "",
  ].filter(Boolean);
  return [...mods, key].join("+");
}

const FUNCTION_KEY = /(?:^|\+)F(?:[1-9]|1\d|2[0-4])$/;

/** A binding with no Ctrl, Alt or function key (A-D05-2): typing makes one, so a text field keeps it. */
export function isBareBinding(binding: string): boolean {
  return !/^(?:Ctrl|Alt)\+/.test(binding) && !FUNCTION_KEY.test(binding);
}

/** A range binding's atoms (`Alt+1..9` → `Alt+1` … `Alt+9`); any other binding is its own atom. */
export function bindingAtoms(binding: string): string[] {
  const m = /^(.*?)(\d)\.\.(\d)$/.exec(binding);
  if (!m) return [binding];
  const out: string[] = [];
  for (let d = Number(m[2]); d <= Number(m[3]); d++) out.push(`${m[1] ?? ""}${d}`);
  return out;
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
