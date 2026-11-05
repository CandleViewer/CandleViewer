// E13-S01 (#423) S1: the model's words, by deck key from `docs/design/E13/E13-D06-copy.json`
// (BQ-13). Deck entries are copied verbatim and pinned by a test; the validation templates are
// d02.12.r19's sentences with the descriptor's `title` and bounds bound by name (D02 D11: "the UI
// renders what the schema says and never hard-codes them"). Anything the deck lacks is PROPOSED
// and listed in the PR (G-f), never presented as the deck's.
import type { UnavailableReason } from "./model/availability";
import type { EditableField, ValueRule } from "./model/schema";

export const DECK_VERSION = { pack: "E13-D06", version: "v1", base: "7e23e4667c" } as const;

/** Deck entries the model renders: `strings` verbatim, `reasons` verbatim where the entry has them. */
export const DECK = {
  "d02.12.r19": {
    strings: [
      "Period must be between 1 and 5000.",
      "Standard deviations must be between 0.1 and 10.",
      "Standard deviations must be a multiple of 0.1.",
      "Depth must be between 1 and 5000.",
      "Deviation (%) must be between 0 and 50.",
      "Choose a source available on this chart.",
    ],
  },
  /** The sentences are the deck's; both keys are PROPOSED (see `PROPOSED_KEYS`). */
  "indicator.cap_instances": {
    reasons: {
      "indicator.cap_instances": "This chart has the maximum of 20 indicators.",
      "indicator.cap_subpanes": "This chart has the maximum of 6 sub-panes.",
    },
  },
  "d02.12.r21": {
    strings: ["Unsupported parameter type — this parameter can't be edited here."],
  },
} as const;

/**
 * Reason KEYS that are PROPOSED until ruled (BQ-08 rider, ruling 6652282467; the deck's `key_status`
 * "PROPOSED (D04 §10.2)"), each with its vocabulary owner (G-T2.4): E09-D09 §3.1's registrar. Their
 * sentences are the deck's; no key is registered, so none belongs in `packages/ui`'s `rbacReasons`
 * (that module holds `rbac.*` only).
 */
export const PROPOSED_KEYS = {
  "indicator.cap_instances": "E09-D09 §3.1 registrar",
  "indicator.cap_subpanes": "E09-D09 §3.1 registrar",
  "indicator.locked": "E09-D09 §3.1 registrar",
} as const;

/**
 * PROPOSED sentences, not in the deck (owner: E13-D06; routed on #423, G-f). Each is one sentence,
 * ≤ 60 characters, naming no data.
 */
export const PROPOSED = {
  /** D11 names no sentence for a fraction typed into an integer field. */
  "indicator.param_whole": "{title} must be a whole number.",
  /** D11's select sentence is the source field's; a generic enum has none. */
  "indicator.param_choice": "Choose one of the listed options.",
} as const;

const RANGE = "{title} must be between {min} and {max}.";
const STEP = "{title} must be a multiple of {step}.";

/** Replaces each `{name}` span once; a bound value is never re-read as a template. */
export function bind(template: string, values: Readonly<Record<string, string>>): string {
  return template.replace(/\{(\w+)\}/g, (span, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? (values[name] as string) : span,
  );
}

/**
 * The T2 reason sentence for an entry that cannot be added (G-T2.4), or `null`: the reason slot is
 * still mounted (the `aria-describedby` target) and renders nothing.
 */
export function unavailableText(reason: UnavailableReason): string | null {
  switch (reason) {
    case "no_path":
      // TODO(#423, ruling 6652282467 BQ-02 rider (c)): this reason's key and sentence are PROPOSED,
      // with E09-D09's registrar as the vocabulary owner, and are written in no code until ruled.
      return null;
    case "indicator.cap_instances":
    case "indicator.cap_subpanes":
      return DECK["indicator.cap_instances"].reasons[reason];
  }
}

/** The message under a field for the keyword its value breaks (D02 D11; never the value itself). */
export function validationText(spec: EditableField, rule: ValueRule): string {
  const title = spec.title;
  if (spec.kind === "enum" || spec.kind === "boolean") return PROPOSED["indicator.param_choice"];
  if (rule === "multipleOf") return bind(STEP, { title, step: String(spec.step) });
  if (rule === "type" && spec.kind === "integer") {
    return bind(PROPOSED["indicator.param_whole"], { title });
  }
  return bind(RANGE, { title, min: String(spec.minimum), max: String(spec.maximum) });
}

export const UNSUPPORTED_PARAM = DECK["d02.12.r21"].strings[0];
