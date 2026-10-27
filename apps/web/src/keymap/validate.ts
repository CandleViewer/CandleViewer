import reservedRaw from "./reserved-keys.json";
import { KEYMAP, SAFETY_MODIFIER_DEFAULT, type KeymapCommand } from "./keymap";

/** Binding validation shared by SCR-113 rebinding and keymap-profile import (E49-S07). */
export type BindingProblem =
  | { readonly kind: "unknown-command"; readonly reason: string }
  | { readonly kind: "invalid-binding"; readonly reason: string }
  | { readonly kind: "reserved"; readonly reason: string; readonly platform: string }
  | { readonly kind: "conflict"; readonly reason: string; readonly with: string }
  | { readonly kind: "unsafe-destructive"; readonly reason: string };

export type KeymapProfile = Readonly<Record<string, string>>;

const MODS = ["Ctrl", "Alt", "Shift"] as const;
const MOD_ALIASES: Readonly<Record<string, string>> = {
  ctrl: "Ctrl",
  control: "Ctrl",
  cmd: "Ctrl",
  meta: "Ctrl",
  mod: "Ctrl",
  alt: "Alt",
  option: "Alt",
  shift: "Shift",
};
const KEY_ALIASES: Readonly<Record<string, string>> = {
  esc: "Esc",
  escape: "Esc",
  del: "Del",
  delete: "Del",
  space: "Space",
  enter: "Enter",
  return: "Enter",
};

/** Canonicalise a user-typed binding (Ctrl+Alt+Shift+Key); null when empty/invalid. */
export function normaliseBinding(raw: string): string | null {
  const parts = raw
    .trim()
    .split(/\+(?!$)/)
    .map((p) => p.trim());
  const key = parts.pop();
  if (!key) return null;
  const mods = new Set<string>();
  for (const p of parts) {
    const m = MOD_ALIASES[p.toLowerCase()];
    if (!m) return null;
    mods.add(m);
  }
  const k = KEY_ALIASES[key.toLowerCase()] ?? (key.length === 1 ? key.toUpperCase() : key);
  if (MOD_ALIASES[k.toLowerCase()]) return null;
  return [...MODS.filter((m) => mods.has(m)), k].join("+");
}

/** A range binding's atoms (`Alt+1..9` → `Alt+1` … `Alt+9`); any other binding is its own atom. */
export function bindingAtoms(binding: string): string[] {
  const m = /^(.*?)(\d)\.\.(\d)$/.exec(binding);
  if (!m) return [binding];
  const out: string[] = [];
  for (let d = Number(m[2]); d <= Number(m[3]); d++) out.push(`${m[1] ?? ""}${d}`);
  return out;
}

const RESERVED = new Map<string, string>(
  Object.entries(reservedRaw as Record<string, string>).flatMap(([raw, why]) =>
    bindingAtoms(raw).map((atom): [string, string] => [atom, why]),
  ),
);

export function reservedBy(binding: string): string | undefined {
  return RESERVED.get(binding);
}

/** Does this command carry a deliberate, reviewed override of the reserved key? */
function overridden(c: KeymapCommand): boolean {
  return Boolean(c.reservedOverride?.rationale.trim());
}

/** Validate one binding for one command against the current profile (map lookups only). */
export function validateBinding(
  commandId: string,
  rawBinding: string,
  current: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, KeymapCommand> = new Map(KEYMAP.map((c) => [c.id, c])),
  opts: { readonly acknowledgedUnsafe?: boolean } = {},
): BindingProblem | null {
  const cmd = byId.get(commandId);
  if (!cmd) return { kind: "unknown-command", reason: `Unknown command ${commandId}` };
  const binding = normaliseBinding(rawBinding);
  if (!binding) {
    return { kind: "invalid-binding", reason: `"${rawBinding}" is not a valid key binding` };
  }
  // A range is checked per atom, and against the atoms of every range already bound.
  const atoms = bindingAtoms(binding);
  const hit = atoms.find((a) => RESERVED.has(a));
  const platform = hit === undefined ? undefined : RESERVED.get(hit);
  if (platform && !(binding === cmd.defaultBinding && overridden(cmd))) {
    return { kind: "reserved", platform, reason: `${hit ?? binding} is reserved by ${platform}` };
  }
  for (const [otherId, otherBinding] of current) {
    const other = byId.get(otherId);
    const overlaps = bindingAtoms(otherBinding).some((a) => atoms.includes(a));
    if (otherId !== commandId && overlaps && other?.context === cmd.context) {
      return {
        kind: "conflict",
        with: otherId,
        reason: `${binding} is already bound to "${other.label}" in the ${cmd.context} context`,
      };
    }
  }
  const bare = !binding.includes("+") || binding.endsWith("++");
  if (cmd.destructive && SAFETY_MODIFIER_DEFAULT && bare && !opts.acknowledgedUnsafe) {
    return {
      kind: "unsafe-destructive",
      reason: `"${cmd.label}" is destructive; a bare key needs an explicit warning acknowledgement`,
    };
  }
  return null;
}

export interface ImportReport {
  readonly applied: ReadonlyMap<string, string>;
  readonly rejected: readonly {
    readonly commandId: string;
    readonly binding: string;
    readonly problem: BindingProblem;
  }[];
}

/** Validate an imported profile per binding; unsafe ones are rejected, safe ones applied. */
export function importProfile(profile: KeymapProfile): ImportReport {
  const byId = new Map(KEYMAP.map((c) => [c.id, c]));
  const applied = new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));
  const rejected: { commandId: string; binding: string; problem: BindingProblem }[] = [];
  for (const [commandId, binding] of Object.entries(profile)) {
    const problem = validateBinding(commandId, binding, applied, byId);
    if (problem) rejected.push({ commandId, binding, problem });
    else applied.set(commandId, normaliseBinding(binding) ?? binding);
  }
  return { applied, rejected };
}
