/**
 * The command registry (#305, E10-S02): the handlers views register, the metadata SCR-013's cheatsheet and SCR-113's
 * editor read, and the combo map the dispatcher resolves a key through, all over `keymap.json`'s commands.
 *
 * One layer (`05` §3.1 rule 2, §3.3 rule 1; AC1): Global resolves first. A view-local binding on a Global key runs only
 * as a declared shadow (`shadows[]` with a rationale, BQ-4), and only while its context is active. An undeclared one
 * is refused: `registerCommand` refuses a command whose keymap default makes one (a developer error: thrown in
 * development and tests, logged in production), and the combo map drops a profile binding that makes one, so the
 * Global keeps its key.
 */
import {
  KEYMAP,
  bindingAtoms,
  isDangerous,
  isSingleLetter,
  rangeDigit,
  type KeymapCommand,
  type KeymapContext,
} from "./keymap";

export interface DeclaredShadow {
  readonly command: string;
  readonly rationale: string;
}

/** What the cheatsheet and the editor read of a command. */
export interface CommandMeta {
  readonly id: string;
  readonly label: string;
  /** The group it is listed under: its context. */
  readonly group: KeymapContext;
  /** Its default key, before any profile rebinds it. */
  readonly defaultBinding: string;
  /** Where its binding is live. */
  readonly focusContexts: readonly KeymapContext[];
  readonly remappable: boolean;
  /** In BQ-3's set (`DANGEROUS_COMMANDS`): the destructive commands, `ticket.submit` and the arm toggles. */
  readonly dangerous: boolean;
  /** A held key runs it once: all but the steppers, and a dangerous command always. */
  readonly ignoreRepeat: boolean;
  /** Its bare key runs in a text field too. */
  readonly allowInEditable: boolean;
  /** The bindings it shares on purpose, each with its rationale. */
  readonly shadows: readonly DeclaredShadow[];
}

/** A held key repeats only a stepper (`ignoreRepeat: false`), never a dangerous command (A11Y-305A-02, BQ-3). */
export const ignoresRepeat = (c: KeymapCommand): boolean =>
  isDangerous(c) || c.ignoreRepeat !== false;
export const runsInEditable = (c: KeymapCommand): boolean => c.allowInEditable === true;
/** Where a command's binding is live: its focus contexts, by default its own context. */
export const contextsOf = (c: KeymapCommand): readonly KeymapContext[] =>
  c.focusContexts ?? [c.context];
const isLocal = (c: KeymapCommand): boolean => contextsOf(c).some((x) => x !== "Global");
const declared = (c: KeymapCommand): readonly DeclaredShadow[] =>
  (c.shadows ?? []).filter((s) => s.rationale.trim() !== "");

const META = new Map<string, CommandMeta>(
  KEYMAP.map((c) => [
    c.id,
    {
      id: c.id,
      label: c.label,
      group: c.context,
      defaultBinding: c.defaultBinding,
      focusContexts: contextsOf(c),
      remappable: c.editable !== false,
      dangerous: isDangerous(c),
      ignoreRepeat: ignoresRepeat(c),
      allowInEditable: runsInEditable(c),
      shadows: declared(c),
    },
  ]),
);

export const commandMeta = (id: string): CommandMeta | undefined => META.get(id);

/** Why `a` and `b` may share a key: the rationale either lists for the other (`keymap_lint.py`'s `_declares`). */
export function shadowRationale(a: KeymapCommand, b: KeymapCommand): string | undefined {
  return (
    declared(a).find((s) => s.command === b.id)?.rationale ??
    declared(b).find((s) => s.command === a.id)?.rationale
  );
}

/** The rationale a view-local command's current binding shadows a Global one's with, if it does (SCR-013). */
export function globalShadowNote(
  c: KeymapCommand,
  bindings: ReadonlyMap<string, string>,
): string | undefined {
  const own = bindings.get(c.id) ?? c.defaultBinding;
  if (!isLocal(c) || own === "") return undefined; // an unbound command shares no key
  const atoms = bindingAtoms(own);
  for (const g of KEYMAP) {
    if (g.context !== "Global") continue;
    const shared = bindingAtoms(bindings.get(g.id) ?? g.defaultBinding).some((a) =>
      atoms.includes(a),
    );
    const why = shared ? shadowRationale(c, g) : undefined;
    if (why !== undefined) return why;
  }
  return undefined;
}

export interface ComboHit {
  readonly command: KeymapCommand;
  /** The pressed digit of a range binding (`Alt+1..9`). */
  readonly digit?: number;
}

export interface ComboMap {
  /** The commands `binding` reaches in the active contexts, in precedence order. */
  resolve(binding: string, active: ReadonlySet<string>): readonly ComboHit[];
  /** The first command an exact `binding` has in any context: what an inert chord explains. */
  anywhere(binding: string): KeymapCommand | undefined;
}

/**
 * Every command's current binding, atom by atom, per focus context: O(1) at key-down, rebuilt only when the profile
 * changes (Technical notes). In one context an exact binding beats a range on the same key, then keymap order decides.
 * A view-local atom on a Global key stays only as a declared shadow, which `resolve` puts before the Global's.
 */
export function buildComboMap(
  commands: readonly KeymapCommand[] = KEYMAP,
  bindings?: ReadonlyMap<string, string>,
): ComboMap {
  const slots = new Map<string, Map<string, ComboHit>>();
  const exact = new Map<string, KeymapCommand>();
  const put = (context: string, atom: string, hit: ComboHit): void => {
    const own = slots.get(context) ?? new Map<string, ComboHit>();
    slots.set(context, own);
    if (!own.has(atom)) own.set(atom, hit);
  };
  // AC5: a stored single letter on a dangerous command never runs; an unbound command (`""`, WCAG 2.1.4) takes no key.
  const bound = commands
    .map((c) => [c, bindings?.get(c.id) ?? c.defaultBinding] as const)
    .filter(([c, binding]) => binding !== "" && !(isDangerous(c) && isSingleLetter(binding)));
  for (const [c, binding] of bound) {
    if (bindingAtoms(binding)[0] !== binding) continue; // a range: indexed after every exact binding
    for (const context of contextsOf(c)) put(context, binding, { command: c });
    if (!exact.has(binding)) exact.set(binding, c);
  }
  for (const [c, binding] of bound) {
    for (const atom of bindingAtoms(binding)) {
      const digit = rangeDigit(binding, atom);
      if (digit === null) continue;
      for (const context of contextsOf(c)) put(context, atom, { command: c, digit });
    }
  }
  const global = slots.get("Global");
  for (const [context, own] of slots) {
    if (context === "Global") continue;
    for (const [atom, hit] of own) {
      const held = global?.get(atom);
      if (held !== undefined && shadowRationale(hit.command, held.command) === undefined) {
        own.delete(atom); // never a silent override (AC1): the Global keeps the key
      }
    }
  }
  return {
    resolve(binding, active) {
      // Innermost context first (`activeContexts` lists them from the focused element out); a local hit on a Global
      // key is a declared shadow, which goes before the Global's own.
      const locals = [...active]
        .filter((context) => context !== "Global")
        .flatMap((context) => slots.get(context)?.get(binding) ?? []);
      const held = active.has("Global") ? global?.get(binding) : undefined;
      return held === undefined ? locals : [...locals, held];
    },
    anywhere: (binding) => exact.get(binding),
  };
}

/** A refused registration (AC1's developer-facing error). */
export class KeymapRegistryError extends Error {
  override readonly name = "KeymapRegistryError";
}

interface Handler {
  readonly run: (digit?: number) => void;
  readonly isValid: () => boolean;
}

export interface CommandRegistry {
  /**
   * A view registers the handler of one of the keymap's commands; the returned function unregisters it. A developer
   * error is refused: an unknown id, a second handler for one id, or a view-local default on a Global key with no
   * declared shadow (AC1). Development and tests throw; production logs it and registers nothing.
   */
  register(id: string, run: (digit?: number) => void, isValid?: () => boolean): () => void;
  /** A handler is registered and its predicate holds. */
  isValid(id: string): boolean;
  /** Run the registered handler; `digit` is a range binding's pressed digit. */
  run(id: string, digit?: number): void;
}

export function createCommandRegistry(
  commands: readonly KeymapCommand[] = KEYMAP,
): CommandRegistry {
  const byId = new Map(commands.map((c) => [c.id, c]));
  const globals = commands.filter((c) => c.context === "Global");
  const handlers = new Map<string, Handler>();
  const clash = (c: KeymapCommand): string | undefined => {
    if (!isLocal(c)) return undefined;
    const atoms = bindingAtoms(c.defaultBinding);
    for (const g of globals) {
      const shared = bindingAtoms(g.defaultBinding).find((a) => atoms.includes(a));
      if (shared !== undefined && shadowRationale(c, g) === undefined) {
        return `${c.id} (${c.context}) binds ${shared}, which Global ${g.id} holds, with no declared shadow`;
      }
    }
    return undefined;
  };
  const refuse = (problem: string): (() => void) => {
    const message = `registerCommand: ${problem}`;
    if (import.meta.env.DEV) throw new KeymapRegistryError(message);
    console.error(message);
    return () => undefined;
  };
  return {
    register(id, run, isValid = () => true) {
      const c = byId.get(id);
      if (c === undefined) return refuse(`unknown keymap command "${id}"`);
      if (handlers.has(id)) return refuse(`"${id}" already has a handler; unregister it first`);
      const taken = clash(c);
      if (taken !== undefined) return refuse(taken);
      const handler: Handler = { run, isValid };
      handlers.set(id, handler);
      return () => {
        if (handlers.get(id) === handler) handlers.delete(id);
      };
    },
    isValid: (id) => handlers.get(id)?.isValid() ?? false,
    run: (id, digit) => handlers.get(id)?.run(digit),
  };
}

const app = createCommandRegistry();
/** The app's registry. Views import `registerCommand` from `KeymapHost.tsx`, its one path for app code. */
export const registerCommand: CommandRegistry["register"] = (id, run, isValid) =>
  app.register(id, run, isValid);
export const isCommandValid = (id: string): boolean => app.isValid(id);
export const runCommand = (id: string, digit?: number): void => app.run(id, digit);
