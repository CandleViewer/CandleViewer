import reservedRaw from "./reserved-keys.json";
import {
  KEYMAP,
  SAFETY_MODIFIER_DEFAULT,
  bindingAtoms,
  isDangerous,
  isSingleLetter,
  type KeymapCommand,
} from "./keymap";
import { contextsOf, shadowRationale } from "./registry";

export { bindingAtoms };

/** Binding validation shared by SCR-113 rebinding and keymap-profile import (E49-S07; #305's conflict engine). */
export type BindingProblem =
  | { readonly kind: "unknown-command"; readonly reason: string }
  | { readonly kind: "invalid-binding"; readonly reason: string }
  | { readonly kind: "reserved"; readonly reason: string; readonly platform: string }
  | { readonly kind: "not-remappable"; readonly reason: string }
  | { readonly kind: "conflict"; readonly reason: string; readonly with: string }
  /** AC5 (BQ-3): a single unmodified letter on a dangerous command; no acknowledgement lifts it. */
  | { readonly kind: "accidental-trigger"; readonly reason: string }
  | { readonly kind: "unsafe-destructive"; readonly reason: string };

export type KeymapProfile = Readonly<Record<string, string>>;

const BY_ID: ReadonlyMap<string, KeymapCommand> = new Map(KEYMAP.map((c) => [c.id, c]));

// The key-name vocabulary: `keymap_lint.py`'s grammar (`normalise`, `_norm_key`), so every default it accepts imports
// here (D4), plus the named keys `eventBinding` reads that `05` §3.2 uses (Backspace, Home, End). Maps, never plain
// objects: an imported `constructor` or `__proto__` must not reach `Object.prototype` (CR-305B-01).
const MODS = ["Ctrl", "Alt", "Shift"] as const;
const MOD_ALIASES: ReadonlyMap<string, string> = new Map([
  ["ctrl", "Ctrl"],
  ["control", "Ctrl"],
  ["cmd", "Ctrl"],
  ["command", "Ctrl"],
  ["meta", "Ctrl"],
  ["mod", "Ctrl"],
  ["alt", "Alt"],
  ["option", "Alt"],
  ["shift", "Shift"],
]);
const KEY_ALIASES: ReadonlyMap<string, string> = new Map([
  ["esc", "Esc"],
  ["escape", "Esc"],
  ["del", "Del"],
  ["delete", "Del"],
  ["space", "Space"],
  ["spacebar", "Space"],
  ["enter", "Enter"],
  ["return", "Enter"],
  ["tab", "Tab"],
  ["arrowleft", "←"],
  ["left", "←"],
  ["arrowright", "→"],
  ["right", "→"],
  ["arrowup", "↑"],
  ["up", "↑"],
  ["arrowdown", "↓"],
  ["down", "↓"],
  ["backspace", "Backspace"],
  ["home", "Home"],
  ["end", "End"],
  ["pageup", "PageUp"],
  ["pagedown", "PageDown"],
]);
const POINTER = new Set(["click", "drag", "wheel"]);
const FKEY = /^F(?:[1-9]|1\d|2[0-4])$/;
const RANGE = /^(\d)\.\.(\d)$/;

/** `keymap_lint.py`'s `_split_binding`: a trailing `+` is the plus key (`Ctrl++`, `Ctrl+`). */
function splitBinding(raw: string): string[] {
  const s = raw.trim();
  if (s === "+") return ["+"];
  if (s.endsWith("++")) return [...s.slice(0, -2).split("+").filter(Boolean), "+"];
  const parts = s.split("+");
  if (parts.length > 1 && parts[parts.length - 1] === "") {
    return [...parts.slice(0, parts[parts.length - 2] === "" ? -2 : -1), "+"];
  }
  return parts;
}

function keyName(key: string): string | null {
  const alias = KEY_ALIASES.get(key.toLowerCase());
  if (alias !== undefined) return alias;
  if (FKEY.test(key.toUpperCase())) return key.toUpperCase();
  const range = RANGE.exec(key);
  if (range !== null) return Number(range[1]) <= Number(range[2]) ? key : null;
  if ([...key].length !== 1 || !/\S/u.test(key)) return null; // `Ctrl+Banana` (D4)
  const upper = key.toUpperCase();
  return upper.length === 1 ? upper : key; // as `eventBinding` reads it (`ß` stays `ß`)
}

/** The arrows are named keys, so Shift stays on them (`Shift+←`), as on Tab or a function key. */
const ARROWS = new Set(["←", "→", "↑", "↓"]);
/** A digit or a punctuation key, alone or as a range: what `eventBinding` reads as the character Shift typed. */
const typedCharacter = (key: string): boolean =>
  RANGE.test(key) || ([...key].length === 1 && !/\p{L}/u.test(key) && !ARROWS.has(key));

/**
 * Canonicalise a user-typed binding (Ctrl+Alt+Shift+Key; a pointer gesture may take `Space`, and a modifier may stand
 * alone, as `keymap_lint.py` allows); null when the key or a modifier is outside the vocabulary, or when Shift sits on
 * a digit or a punctuation key, which a press reads as the character Shift typed (`?` for US Shift+/), so the binding
 * could never fire (CR-305B-07).
 */
export function normaliseBinding(raw: string): string | null {
  const parts = splitBinding(raw).map((p) => p.trim());
  const last = parts.pop();
  if (last === undefined || last === "") return null;
  const alone = MOD_ALIASES.get(last.toLowerCase());
  if (parts.length === 0 && alone !== undefined) return alone; // a modifier alone (multi-select)
  const pointer = POINTER.has(last.toLowerCase());
  const mods = new Set<string>();
  for (const p of parts) {
    const mod =
      MOD_ALIASES.get(p.toLowerCase()) ?? (pointer && /^space$/i.test(p) ? "Space" : null);
    if (mod === null) return null;
    mods.add(mod);
  }
  const key = pointer ? last.toLowerCase() : keyName(last);
  if (key === null || (!pointer && mods.has("Shift") && typedCharacter(key))) return null;
  const space = mods.has("Space") ? ["Space"] : [];
  return [...MODS.filter((m) => mods.has(m)), ...space, key].join("+");
}

/** What a binding is: a key, a digit range, a pointer gesture or a modifier alone. A rebind keeps its command's. */
function shapeOf(binding: string): string {
  if ((MODS as readonly string[]).includes(binding)) return "modifier";
  const key = splitBinding(binding).pop() ?? "";
  if (POINTER.has(key)) return `pointer:${key}`;
  return RANGE.test(key) ? `range:${key}` : "key";
}

const RESERVED = new Map<string, string>(
  Object.entries(reservedRaw as Record<string, string>).flatMap(([raw, why]) =>
    bindingAtoms(raw).map((atom): [string, string] => [atom, why]),
  ),
);
/** `05` §3.3 rule 3: `Esc` (universal cancel) and `Ctrl+K` (the palette, the way back from a broken keymap). */
const PERMANENT = new Map<string, string>([
  ["Esc", "app (universal cancel)"],
  ["Ctrl+K", "app (command palette)"],
]);

export function reservedBy(binding: string): string | undefined {
  return RESERVED.get(binding);
}

/** Never remappable, never taken by another command (AC4); the dispatcher keeps `Ctrl+K` for the palette (BQ-7). */
export const isPermanentlyReserved = (binding: string): boolean => PERMANENT.has(binding);

const unknown = (id: string): BindingProblem => ({
  kind: "unknown-command",
  reason: `Unknown command ${id}`,
});
const invalid = (raw: string): BindingProblem => ({
  kind: "invalid-binding",
  reason: `"${raw}" is not a valid key binding`,
});
const locked = (c: KeymapCommand): BindingProblem => ({
  kind: "not-remappable",
  reason: `"${c.label}" is not remappable`,
});
const conflict = (binding: string, other: KeymapCommand): BindingProblem => ({
  kind: "conflict",
  with: other.id,
  reason: `${binding} is already bound to "${other.label}" in the ${other.context} context`,
});

/** What refuses a binding whatever else is bound: a dangerous single letter, a reserved key, a locked command. */
function ownProblem(cmd: KeymapCommand, binding: string): BindingProblem | null {
  // `05` §3.3 rule 2, AC5 (PR A): refused before any conflict, so the stated reason is always this one.
  if (isDangerous(cmd) && isSingleLetter(binding)) {
    return {
      kind: "accidental-trigger",
      reason: `"${cmd.label}" needs Ctrl or Alt with a letter: ${binding} alone could trigger it by accident`,
    };
  }
  const own = binding === cmd.defaultBinding;
  for (const atom of bindingAtoms(binding)) {
    const kept = PERMANENT.get(atom);
    const platform = kept ?? RESERVED.get(atom);
    // A command holding its reviewed default keeps it: a locked one its reserved key, an override its OS key.
    const reviewed = own && (kept !== undefined ? cmd.editable === false : overridden(cmd));
    if (platform !== undefined && !reviewed) {
      return { kind: "reserved", platform, reason: `${atom} is reserved by ${platform}` };
    }
  }
  return cmd.editable === false && !own ? locked(cmd) : null;
}

/**
 * E49-S07's audited acknowledgement, over the whole dangerous set (CR-305B-04, SEC-305A-01): a key with no Ctrl or Alt
 * that is neither a letter (refused outright) nor the command's reviewed default, so `ticket.submit` and the arm
 * toggles never take a digit, Enter, Space or a function key without it. Shift leaves a key bare, as the dispatcher's
 * `isBareBinding` reads it (CR-305BD-03): `Shift+Enter` on Submit order needs it too. Diverging from `isBareBinding` on
 * a function key is deliberate and fails closed: that check exempts one because typing never makes one, while this one
 * guards a single press firing a dangerous command, and a function key fires even inside a text field.
 */
function needsAcknowledgement(cmd: KeymapCommand, binding: string): boolean {
  const bare = !/^(?:Ctrl|Alt)\+/.test(binding); // canonical order: Ctrl, Alt, Shift
  return isDangerous(cmd) && SAFETY_MODIFIER_DEFAULT && bare && binding !== cmd.defaultBinding;
}
/** `05` §3.3 rule 1 calls submit, cancel and flatten trading-critical: the reason names what the command is. */
const unsafe = (c: KeymapCommand): BindingProblem => ({
  kind: "unsafe-destructive",
  reason: `"${c.label}" is ${c.destructive ? "destructive" : "trading-critical"}; a bare key needs an explicit warning acknowledgement`,
});

/** Does this command carry a deliberate, reviewed override of the reserved key? */
function overridden(c: KeymapCommand): boolean {
  return Boolean(c.reservedOverride?.rationale.trim());
}

/** SCR-013's "reserved by the browser or OS" (E10-D04 §15): a reviewed override, while it holds that default. */
export const holdsReservedOverride = (c: KeymapCommand, binding: string): boolean =>
  binding === c.defaultBinding && overridden(c);

/**
 * Two commands are never live at once: their focus-context sets are disjoint views, or one is a Global key the other
 * shadows on purpose (BQ-4). Global is the wildcard; distinct views are exclusive, as in `keymap_lint.py`.
 */
function exclusive(a: KeymapCommand, b: KeymapCommand): boolean {
  const [ac, bc] = [contextsOf(a), contextsOf(b)];
  const [ag, bg] = [ac.includes("Global"), bc.includes("Global")];
  if (ag || bg) return ag !== bg && shadowRationale(a, b) !== undefined;
  return !ac.some((x) => bc.includes(x));
}

/** `a` on `aBinding` and `b` on `bBinding` collide: a shared key while both can be live. */
function collides(a: KeymapCommand, aBinding: string, b: KeymapCommand, bBinding: string): boolean {
  if (aBinding === "" || bBinding === "" || exclusive(a, b)) return false;
  const atoms = bindingAtoms(aBinding);
  return bindingAtoms(bBinding).some((x) => atoms.includes(x));
}

function sharing(
  cmd: KeymapCommand,
  binding: string,
  current: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KeymapCommand>,
): KeymapCommand[] {
  const atoms = bindingAtoms(binding);
  return [...byId.values()].filter((other) => {
    const held = current.get(other.id) ?? other.defaultBinding;
    return other.id !== cmd.id && held !== "" && bindingAtoms(held).some((a) => atoms.includes(a));
  });
}

/** `05` §3.3 rule 2: the commands a binding collides with, a shared key in intersecting focus-context sets. */
export function conflictsWith(
  cmd: KeymapCommand,
  binding: string,
  current: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KeymapCommand> = BY_ID,
): KeymapCommand[] {
  return sharing(cmd, binding, current, byId).filter((other) => !exclusive(cmd, other));
}

export interface SharedMeaning {
  readonly command: KeymapCommand;
  /** The declared shadow's rationale, when the keymap gives one. */
  readonly rationale?: string;
}

/** `05` §3.3 rule 1 (3): the other meanings a key keeps in exclusive contexts, shown beside it (the dual meaning). */
export function sharedWith(
  commandId: string,
  rawBinding: string,
  current: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KeymapCommand> = BY_ID,
): SharedMeaning[] {
  const cmd = byId.get(commandId);
  const binding = normaliseBinding(rawBinding);
  if (cmd === undefined || binding === null) return [];
  return sharing(cmd, binding, current, byId)
    .filter((other) => exclusive(cmd, other))
    .map((command) => {
      const rationale = shadowRationale(cmd, command);
      return rationale === undefined ? { command } : { command, rationale };
    });
}

/** Validate one binding for one command against the current profile (map lookups only). */
export function validateBinding(
  commandId: string,
  rawBinding: string,
  current: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KeymapCommand> = BY_ID,
  opts: { readonly acknowledgedUnsafe?: boolean } = {},
): BindingProblem | null {
  const cmd = byId.get(commandId);
  if (!cmd) return unknown(commandId);
  const binding = normaliseBinding(rawBinding);
  if (binding === null || shapeOf(binding) !== shapeOf(cmd.defaultBinding)) {
    return invalid(rawBinding);
  }
  const own = ownProblem(cmd, binding);
  if (own !== null) return own;
  const [other] = conflictsWith(cmd, binding, current, byId);
  if (other !== undefined) return conflict(binding, other);
  return needsAcknowledgement(cmd, binding) && opts.acknowledgedUnsafe !== true
    ? unsafe(cmd)
    : null;
}

/** Unbinding, WCAG 2.1.4's turn-off: any command but a locked one. */
export function validateUnbind(
  commandId: string,
  byId: ReadonlyMap<string, KeymapCommand> = BY_ID,
): BindingProblem | null {
  const cmd = byId.get(commandId);
  if (!cmd) return unknown(commandId);
  return cmd.editable === false ? locked(cmd) : null;
}

/** `05` §3.3 rule 2's one-click swap: the command takes the key, its one holder takes the command's current key. */
export interface SwapPlan {
  readonly a: string;
  readonly aTo: string;
  readonly b: string;
  readonly bTo: string;
}

/** The swap that resolves a conflict, or null: not exactly one holder, or either side refused in the swapped profile. */
export function planSwap(
  commandId: string,
  rawBinding: string,
  current: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KeymapCommand> = BY_ID,
): SwapPlan | null {
  const cmd = byId.get(commandId);
  const aTo = normaliseBinding(rawBinding);
  if (cmd === undefined || aTo === null) return null;
  const holders = conflictsWith(cmd, aTo, current, byId);
  const holder = holders.length === 1 ? holders[0] : undefined;
  const bTo = current.get(cmd.id) ?? cmd.defaultBinding;
  if (holder === undefined || bTo === "") return null;
  const next = new Map(current).set(cmd.id, aTo).set(holder.id, bTo);
  const fits = (id: string, to: string): boolean => validateBinding(id, to, next, byId) === null;
  return fits(cmd.id, aTo) && fits(holder.id, bTo) ? { a: cmd.id, aTo, b: holder.id, bTo } : null;
}

export interface ImportReport {
  readonly applied: ReadonlyMap<string, string>;
  readonly rejected: readonly {
    readonly commandId: string;
    readonly binding: string;
    readonly problem: BindingProblem;
  }[];
}

/**
 * One binding on its own: the vocabulary, its command's shape, a reserved key, a locked command and a dangerous single
 * letter. An import cannot acknowledge, so E49-S07's acknowledgement refuses it there; a stored binding was
 * acknowledged when it was made.
 */
function entryProblem(
  commandId: string,
  value: unknown,
  shown: string,
  acknowledged: boolean,
): BindingProblem | null {
  const cmd = BY_ID.get(commandId);
  if (cmd === undefined) return unknown(commandId);
  if (typeof value !== "string") return invalid(shown);
  if (value.trim() === "") return validateUnbind(commandId);
  const binding = normaliseBinding(value);
  if (binding === null || shapeOf(binding) !== shapeOf(cmd.defaultBinding)) return invalid(value);
  const own = ownProblem(cmd, binding);
  return own ?? (!acknowledged && needsAcknowledgement(cmd, binding) ? unsafe(cmd) : null);
}

/**
 * Validate an imported profile as one profile (D4): each entry alone, then the profile the accepted entries make with
 * the defaults, so a valid swap imports. A key two entries claim stays with the first; an entry on a key the profile
 * keeps is refused. A refused entry keeps its default and is reported, never dropped silently (AC7), except that one
 * that lost its key to an earlier entry is left unbound when that entry holds its default too (CR-305B-07). An empty
 * binding unbinds its command.
 */
export const importProfile = (profile: Readonly<Record<string, unknown>>): ImportReport =>
  checkProfile(profile, false);

/**
 * A stored profile at load, by the same rules as an import (CR-305B-05, SEC-305B-01), so a legacy binding made before
 * these checks returns to its default: `dom.zoom_in` on Esc, an acknowledged letter on a dangerous command, or a Global
 * the earlier per-context editor saved on a view's chord, which would take the view's binding from it unreported.
 */
export const storedProfile = (profile: Readonly<Record<string, unknown>>): ImportReport =>
  checkProfile(profile, true);

function checkProfile(
  profile: Readonly<Record<string, unknown>>,
  acknowledged: boolean,
): ImportReport {
  const rejected: ImportReport["rejected"][number][] = [];
  const accepted = new Map<string, string>();
  const shownOf = new Map<string, string>();
  for (const [commandId, value] of Object.entries(profile)) {
    const shown = typeof value === "string" ? value : (JSON.stringify(value) ?? String(value));
    const problem = entryProblem(commandId, value, shown, acknowledged);
    if (problem !== null) rejected.push({ commandId, binding: shown, problem });
    else {
      accepted.set(commandId, normaliseBinding(shown) ?? "");
      shownOf.set(commandId, shown);
    }
  }
  const yielded = new Set<string>(); // entries that lost their key to an earlier entry
  // A yielded entry's default, unless an accepted entry holds it: then no key, so the first keeps it.
  const fallback = (c: KeymapCommand): string =>
    yielded.has(c.id) &&
    [...accepted].some(([id, b]) => {
      const other = BY_ID.get(id);
      return other !== undefined && collides(c, c.defaultBinding, other, b);
    })
      ? ""
      : c.defaultBinding;
  for (;;) {
    const applied = new Map(KEYMAP.map((c) => [c.id, accepted.get(c.id) ?? fallback(c)]));
    const order = [...accepted.keys()];
    // An entry loses to a binding the profile keeps or to an earlier entry, never to a later one.
    const kept = (id: string, at: number): boolean => !accepted.has(id) || order.indexOf(id) < at;
    let loser:
      { readonly id: string; readonly binding: string; readonly holder: KeymapCommand } | undefined;
    for (const [at, id] of order.entries()) {
      const cmd = BY_ID.get(id);
      const binding = accepted.get(id) ?? "";
      if (cmd === undefined || binding === "") continue;
      const holder = conflictsWith(cmd, binding, applied).find((o) => kept(o.id, at));
      if (holder !== undefined) {
        loser = { id, binding, holder };
        break;
      }
    }
    if (loser === undefined) return { applied, rejected };
    const { id, binding, holder } = loser;
    const problem = conflict(binding, holder);
    rejected.push({ commandId: id, binding: shownOf.get(id) ?? binding, problem });
    if (accepted.has(holder.id)) yielded.add(id);
    accepted.delete(id); // it falls back; the next pass checks the profile that leaves
  }
}
