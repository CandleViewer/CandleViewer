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
  // S4 (SCR-035, the settings dialog).
  "d02.12.r10": {
    strings: [
      "You have the maximum of 8 server-computed indicators. Remove one to add another.",
      "Server-computed indicators are at capacity for this symbol.",
      "Server-computed indicators are at capacity. Try again later.",
      "Retry",
    ],
  },
  "d02.12.r15": { strings: ["EMA 21 · price pane · 5m", "edited", "Used by 2 armed rules"] },
  "d02.12.r16": { strings: ["Inputs", "Style", "Visibility", "Scale", "Alerts"] },
  "d02.12.r18": {
    strings: ["1–5000 bars", "0.1–10, step 0.1", "Source: series available on this chart"],
  },
  /** [0] is form validity (E09-D09 §9.1, no key); [1] is the Style tab's one note (C-b). */
  "indicator.style_pending": {
    strings: ["Fix the highlighted field first.", "Style tokens arrive with E13-D04"],
  },
  "d02.12.r22": { strings: ["This indicator has no parameters."] },
  "d02.12.r23": {
    strings: [
      "Preview: last 200 bars, display-only",
      "Updating…",
      "Preview on Apply — this indicator is computed on the server.",
    ],
  },
  "d02.12.r24": {
    strings: [
      "Reset to catalogue defaults",
      "Reset to my default",
      "Save as default for this indicator",
      "Cancel",
      "Apply",
      "Applying…",
    ],
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
  /** S4: the one safe error for a schema outside the closed subset (BQ-11 rider, Q-12). */
  "indicator.schema_refused": "This indicator's settings can't be shown.",
  /** S4: a re-tune the engine or the server refused, other than at capacity (no deck row). */
  "indicator.apply_refused": "These settings weren't applied.",
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

const r23 = DECK["d02.12.r23"].strings;
const r24 = DECK["d02.12.r24"].strings;

/** SCR-035's words (D02 §12 :467–:476 through the deck; S4). */
export const SETTINGS = {
  edited: DECK["d02.12.r15"].strings[1],
  tabs: { inputs: DECK["d02.12.r16"].strings[0], style: DECK["d02.12.r16"].strings[1] },
  fixFirst: DECK["indicator.style_pending"].strings[0],
  stylePending: DECK["indicator.style_pending"].strings[1],
  noParams: DECK["d02.12.r22"].strings[0],
  previewWindow: r23[0],
  updating: r23[1],
  previewServer: r23[2],
  reset: r24[0],
  cancel: r24[3],
  apply: r24[4],
  atCapacity: DECK["d02.12.r10"].strings[2],
  schemaRefused: PROPOSED["indicator.schema_refused"],
  applyRefused: PROPOSED["indicator.apply_refused"],
} as const;

/**
 * The header "EMA 21 · price pane · 5m" (d02.12.r15) from its parts. "price pane" is the deck's;
 * the sub-pane word is r02's tab word in lower case (a G-row on #423: the deck draws no sub-pane
 * header).
 */
export function settingsTitle(label: string, pane: "price" | "sub", timeframe: string): string {
  return `${label} · ${pane === "price" ? "price pane" : "sub-pane"} · ${timeframe}`;
}

/** The help line under a number field: d02.12.r18's two forms, bound from the schema (D02 D10). */
export function rangeHelp(spec: {
  readonly kind: "integer" | "number";
  readonly minimum: number;
  readonly maximum: number;
  readonly step: number;
}): string {
  const span = `${spec.minimum}–${spec.maximum}`;
  // Every integer parameter of the v1 catalogue counts bars (period, depth, offset): a G-row if one
  // ever does not, since the descriptor carries no unit per parameter.
  return spec.kind === "integer" && spec.step === 1 ? `${span} bars` : `${span}, step ${spec.step}`;
}
