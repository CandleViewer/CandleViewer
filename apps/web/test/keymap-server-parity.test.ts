import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { generated } from "@candleviewer/protocol";
import {
  KEYMAP,
  bindingAtoms,
  getCommand,
  isSingleLetter,
  requiresArm,
} from "../src/keymap/keymap";
import { httpProfileStore } from "../src/keymap/profileStore";
import { normaliseBinding, storedProfile, type BindingProblem } from "../src/keymap/validate";

/**
 * E10-T05 (#5211, BQ-4): the server's port of the binding rules (`services/api/candleviewer/api/hotkey_rules.py`) is
 * pinned to this client by one case table, `packages/fixtures/golden/hotkeys/profile_cases.json`. pytest runs every
 * case through the server's judge (`services/api/tests/unit/api/test_hotkey_rules_cases.py`); this file runs each
 * against `validate.ts`, reading a profile as `storedProfile` reads a stored one: the import's rules, with the
 * acknowledgement taken as given, since the server checks none (CR-305BD-04). A server rule maps to the problem that
 * refuses the same entry here; a conflict to the entry the client rejects, naming the command that keeps the key; a
 * rewrite to the arm and confirm the keymap gives the command. The `server_only` cases name a rule a map of command id
 * to binding cannot express (a duplicate, a scope, params); pytest pins that they are only those.
 */
type ProfileInput = generated.rest.components["schemas"]["HotkeyProfileInput"];
interface Binding {
  readonly action: string;
  readonly keys: string;
  readonly scope?: string;
  readonly requires_arm?: boolean;
  readonly confirm?: boolean;
}
interface Refusal {
  readonly field: string;
  readonly rule: string;
}
interface Clash {
  readonly field: string;
  readonly action: string;
  readonly other: string;
}
interface ProfileCase {
  readonly id: string;
  readonly bindings: readonly Binding[] | "client_default";
  readonly expect: {
    readonly accepted?: {
      readonly rewritten: readonly string[];
      readonly stored?: Readonly<Record<string, string>>;
    };
    readonly invalid?: readonly Refusal[];
    readonly conflict?: readonly Clash[];
  };
  readonly server_only?: string;
}
interface Cases {
  readonly grammar: readonly { readonly raw: string; readonly canonical: string | null }[];
  readonly atoms: readonly { readonly binding: string; readonly atoms: readonly string[] }[];
  readonly single_letter: readonly { readonly binding: string; readonly single: boolean }[];
  readonly profiles: readonly ProfileCase[];
}

const CASES = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../packages/fixtures/golden/hotkeys/profile_cases.json"),
    "utf8",
  ),
) as Cases;

/** The client problem that refuses an entry the server refuses by `rule`. */
const KIND: Readonly<Record<string, BindingProblem["kind"]>> = {
  unknown_action: "unknown-command",
  invalid_keys: "invalid-binding",
  shape_mismatch: "invalid-binding",
  bare_letter_dangerous: "accidental-trigger",
  reserved_key: "reserved",
  locked_command: "not-remappable",
};

const parity = CASES.profiles.filter(
  (c): c is ProfileCase & { readonly bindings: readonly Binding[] } =>
    c.server_only === undefined && c.bindings !== "client_default",
);
const profileOf = (bindings: readonly Binding[]): Record<string, string> =>
  Object.fromEntries(bindings.map((b) => [b.action, b.keys]));
/** The entry a server `field` (`bindings[2].keys`) names. */
const entryOf = (bindings: readonly Binding[], field: string): Binding | undefined =>
  bindings[Number(/^bindings\[(\d+)\]/.exec(field)?.[1] ?? Number.NaN)];
/** The actions whose sent `requires_arm` or `confirm` is not the keymap's: what the server rewrites. */
function rewrittenBy(bindings: readonly Binding[]): string[] {
  return bindings
    .filter((b) => {
      const c = getCommand(b.action);
      if (c === undefined) return false;
      const arm = b.requires_arm !== undefined && b.requires_arm !== requiresArm(c);
      return arm || (b.confirm !== undefined && b.confirm !== (c.confirm === true));
    })
    .map((b) => b.action);
}

describe("the server's grammar is validate.ts's (normaliseBinding, bindingAtoms, isSingleLetter)", () => {
  it.each(CASES.grammar.map((c) => [JSON.stringify(c.raw), c.raw, c.canonical] as const))(
    "%s",
    (_shown, raw, canonical) => {
      expect(normaliseBinding(raw)).toBe(canonical);
    },
  );
  it.each(CASES.atoms.map((c) => [c.binding, c.atoms] as const))("atoms of %s", (b, atoms) => {
    expect(bindingAtoms(b)).toEqual(atoms);
  });
  it.each(CASES.single_letter.map((c) => [c.binding, c.single] as const))(
    "a single letter: %s",
    (b, single) => {
      expect(isSingleLetter(b)).toBe(single);
    },
  );
});

describe("each profile case is judged here as the server judges it", () => {
  it.each(parity.map((c) => [c.id, c] as const))("%s", (_id, c) => {
    const report = storedProfile(profileOf(c.bindings));
    const rejected = report.rejected.map((r) => [
      r.commandId,
      r.problem.kind,
      r.problem.kind === "conflict" ? r.problem.with : null,
    ]);
    if (c.expect.accepted !== undefined) {
      expect(rejected).toEqual([]);
      for (const [action, keys] of Object.entries(c.expect.accepted.stored ?? {})) {
        expect(report.applied.get(action)).toBe(keys);
      }
      expect(rewrittenBy(c.bindings)).toEqual(c.expect.accepted.rewritten);
    } else if (c.expect.invalid !== undefined) {
      expect(rejected).toEqual(
        c.expect.invalid.map((e) => [entryOf(c.bindings, e.field)?.action, KIND[e.rule], null]),
      );
    } else {
      const [loses] = c.expect.conflict ?? [];
      expect(rejected).toEqual([[loses?.action, "conflict", loses?.other]]);
    }
  });

  it("names every rule the client can express, and a conflict and a rewrite case", () => {
    const rules = new Set(parity.flatMap((c) => (c.expect.invalid ?? []).map((e) => e.rule)));
    expect([...rules].sort()).toEqual(Object.keys(KIND).sort());
    expect(parity.some((c) => c.expect.conflict !== undefined)).toBe(true);
    expect(parity.some((c) => (c.expect.accepted?.rewritten.length ?? 0) > 0)).toBe(true);
  });
});

describe("the client's own default profile, which the server accepts as it is", () => {
  it("is the body profileStore.ts sends: every command at its default, its scope, arm and confirm", async () => {
    const [found] = CASES.profiles.filter((c) => c.bindings === "client_default");
    expect(found?.expect).toEqual({ accepted: { rewritten: [] } });
    const sent: ProfileInput[] = [];
    const store = httpProfileStore(
      async (_path: RequestInfo | URL, init: RequestInit = {}) => {
        if ((init.method ?? "GET") === "GET") return Response.json({ items: [] });
        sent.push(JSON.parse(String(init.body)) as ProfileInput);
        return new Response(null, { status: 503 }); // nothing more to send here
      },
      () => "u-1",
    );
    store.write("u-1", new Map());
    await store.flush();
    const [body] = sent;
    expect(body?.name).toBe("CandleViewer Default");
    const bindings = body?.bindings ?? [];
    expect(bindings.map((b) => [b.action, b.keys])).toEqual(
      KEYMAP.map((c) => [c.id, c.defaultBinding]),
    );
    expect(rewrittenBy(bindings)).toEqual([]);
    expect(storedProfile(profileOf(bindings)).rejected).toEqual([]);
  });
});
