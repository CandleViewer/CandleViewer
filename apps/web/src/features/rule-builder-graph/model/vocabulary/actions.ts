/**
 * The action entries of the node library and the action inspector (E37-S02): every served action, in the order
 * served, with its treatment as the server states it (E36-D02 §8), its destructive word, its stop line (C-2.6,
 * E37-D02 A1) and its `targets` sentence. The client reads the served `available`, `simulate_only`,
 * `required_permissions`, `restriction`, `places_orders`, `params_schema` and `targets` only: no permission
 * arithmetic and no action list (AC 1, AC 4). Pure: no React, no DOM global.
 */
import type { generated } from "@candleviewer/protocol";
import { text, type CopyKey } from "./copy.js";
import type { RuleVocabulary, VocabularyAction } from "./types.js";

/** An IR action's `targets` value (`22` `RuleAction.targets`); `scope_accounts` when the action names none. */
export type ActionTargets = generated.rest.components["schemas"]["RuleAction"]["targets"];

/**
 * Whether `action` can open or add to a position. Only a served `false` says no: "An absent `places_orders`
 * means unknown, and a client treats the action as placing orders" (`22` `RuleVocabulary.actions[]`).
 */
export const placesOrders = (action: VocabularyAction): boolean => action.places_orders !== false;

/** T1 · T1 in simulate framing, pickable with its tag · T2, shown and arrow-reachable, never chosen (E09-D09 §2.2). */
export type ActionAvailability = "available" | "simulate" | "gated";

export interface ActionTreatment {
  readonly availability: ActionAvailability;
  /** E36-D05's "simulate only", after the notes, in simulate framing. */
  readonly tag: string | undefined;
  /** The T2 reason (E09-D09 §3.1), by the permission the action requires. */
  readonly reasonKey: CopyKey | undefined;
  readonly reason: string | undefined;
  /** The served `restriction`: in the details only, never the reason (P10; it names permission ids). */
  readonly details: string | undefined;
  /** The destructive class's word: "places orders", or "flattens" for `flatten_*` (E36-D02 §8). */
  readonly destructive: string | undefined;
}

/**
 * The T2 reason per required permission (E09-D09 §3.2's verbs, E36-D02 §8 (ii) and (iii)), owner-only first: when
 * an action needs both, the owner-only sentence holds for every non-owner role, the other one not for a Manager.
 */
const REASONS: readonly (readonly [permission: string, key: CopyKey])[] = [
  ["rules:arm_live", "rbac.owner_only.arm_live"],
  ["orders:write", "rbac.permission.place_orders"],
];

/** The destructive class beyond the placing actions: `places_orders` ∪ `flatten_*` (E36-D02 §8, PROPOSED). */
const FLATTENS = "flatten_";

/** How the action is offered: simulate framing first (the server serves it as unavailable too), then T2. */
export function actionTreatment(action: VocabularyAction): ActionTreatment {
  const destructive = placesOrders(action)
    ? text("rules.editor.action.places_orders")
    : action.id.startsWith(FLATTENS)
      ? text("rules.editor.action.flattens")
      : undefined;
  const base = { tag: undefined, reasonKey: undefined, reason: undefined, destructive };
  const details = action.restriction;
  if (action.simulate_only) {
    return {
      ...base,
      availability: "simulate",
      tag: text("rules.editor.action.simulate_only"),
      details,
    };
  }
  if (action.available) return { ...base, availability: "available", details };
  const reasonKey = REASONS.find(([permission]) =>
    action.required_permissions.includes(permission),
  )?.[1];
  const reason = reasonKey === undefined ? undefined : text(reasonKey);
  return { ...base, availability: "gated", reasonKey, reason, details };
}

/** A placing action's own native stop parameter (E36-D02 §8: `place_order`'s `stop_loss`). */
export const STOP_FIELD = "stop_loss";

/** The stop-management actions: the ratchet on the card and `sl.note` in the inspector (E36-D02 §8; FZ-6). */
const STOP_ACTIONS: ReadonlySet<string> = new Set([
  "modify_stop_loss",
  "tighten_stop",
  "move_to_breakeven",
]);

/** FZ-7's one action: it adds to a position whose native stop stays, and has no stop of its own (D02-G16). */
const KEEPS_POSITION_STOP = "scale_in";

/** How a placing action's native stop shows (E37-D02 A1): its own field, or a read-only line from server truth. */
export type NativeStop =
  | { readonly kind: "field"; readonly param: typeof STOP_FIELD }
  | { readonly kind: "exchange"; readonly text: string }
  | { readonly kind: "server"; readonly text: string };

export interface StopLine {
  /** Every action that can open or add to a position has one: `stop_loss` · FZ-7 · FZ-8 (C-2.6). */
  readonly native: NativeStop | undefined;
  /** A stop action's ratchet: FZ-6 "only tighten" on the card, FS-3 "Rules never loosen a stop." beneath it. */
  readonly ratchet: { readonly label: string; readonly line: string } | undefined;
  /** `sl.note` (FS-1) under the stop field and on the stop rows of the inspector; no other row carries it. */
  readonly note: string | undefined;
}

const hasStopField = (action: VocabularyAction): boolean => {
  const properties = action.params_schema?.["properties"];
  return (
    typeof properties === "object" && properties !== null && Object.hasOwn(properties, STOP_FIELD)
  );
};

const nativeStopOf = (action: VocabularyAction): NativeStop => {
  if (hasStopField(action)) return { kind: "field", param: STOP_FIELD };
  if (action.id === KEEPS_POSITION_STOP) {
    return { kind: "exchange", text: text("rules.graph.node.stop_exchange") };
  }
  return { kind: "server", text: text("rules.graph.node.stop_server") };
};

/** The action's stop lines: the native stop of a placing action and the ratchet of a stop action, or neither. */
export function stopLineOf(action: VocabularyAction): StopLine {
  const native = placesOrders(action) ? nativeStopOf(action) : undefined;
  const ratchet = STOP_ACTIONS.has(action.id)
    ? { label: text("rules.graph.node.only_tighten"), line: text("rules.editor.stop.never_loosen") }
    : undefined;
  const carriesNote = native?.kind === "field" || ratchet !== undefined;
  return {
    native,
    ratchet,
    note: carriesNote ? text("rules.editor.notice.native_stop_1") : undefined,
  };
}

/**
 * The action node's scope line (BQ-9, PROPOSED `rules.graph.node.targets`): the vocabulary's sentence for
 * `targets`, verbatim, never an account id or name; undefined when the action serves none for it.
 */
export function targetsSentence(
  action: VocabularyAction,
  targets: ActionTargets = "scope_accounts",
): string | undefined {
  const sentences = action.targets ?? {};
  return Object.hasOwn(sentences, targets)
    ? text("rules.graph.node.targets", { targets: sentences[targets] as string })
    : undefined;
}

/** One served action as an entry: the name and notes the palette and the action picker show, and its lines. */
export interface ActionOption {
  readonly id: string;
  /** The served `display_name`; the id only where the server serves none (P1). */
  readonly label: string;
  /** The served `notes`, the entry's second line. */
  readonly notes: string;
  readonly treatment: ActionTreatment;
  readonly stop: StopLine;
}

/** Every served action as an entry, gated ones included, in the order served. */
export function actionOptions(vocabulary: RuleVocabulary): ActionOption[] {
  return vocabulary.actions.map((action: VocabularyAction) => ({
    id: action.id,
    label: action.display_name ?? action.id,
    notes: action.notes ?? "",
    treatment: actionTreatment(action),
    stop: stopLineOf(action),
  }));
}
