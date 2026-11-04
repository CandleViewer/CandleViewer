import { describe, expect, it } from "vitest";
import {
  actionOptions,
  actionTreatment,
  placesOrders,
  stopLineOf,
  targetsSentence,
  type ActionTargets,
  type StopLine,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/actions.js";
import type {
  RuleVocabulary,
  VocabularyAction,
} from "../../../../src/features/rule-builder-graph/model/vocabulary/types.js";
import { extended, served, type Persona } from "./fixtures.js";

const PERSONAS: readonly Persona[] = ["owner", "manager", "no-orders-write", "unrecorded-solusdt"];
/** The six actions the catalogue marks `places_orders`, in the order served. */
const PLACING = [
  "place_order",
  "scale_in",
  "reverse_position",
  "arm_chase_limit",
  "start_iceberg_slice",
  "start_twap",
];
/** The frozen lines, byte for byte (E37-D05 §9 FZ-6 … FZ-8; E36-D05 FS-1, FS-3). */
const FZ6 = "only tighten";
const FZ7 = "Stop: the position's native stop, held by Bybit (exchange).";
const FZ8 = "Stop: attached by the server (native SL).";
const FS1 = "Every position keeps a native stop — you can move it, not delete it.";
const FS3 = "Rules never loosen a stop.";
const PLACE_ORDERS = "Your role can't place orders.";
const ARM_LIVE = "Only the owner can arm rules against live.";

const actionOf = (vocabulary: RuleVocabulary, id: string): VocabularyAction => {
  const action = vocabulary.actions.find((a) => a.id === id);
  if (action === undefined) throw new Error(`${id} is not served`);
  return action;
};

/** `action` as a server that does not serve `places_orders` sends it. */
const withoutFlag = (action: VocabularyAction): VocabularyAction => {
  const copy = { ...action };
  Reflect.deleteProperty(copy, "places_orders");
  return copy;
};

/** A stop line in words: the native stop, then the ratchet, then the note. */
const said = ({ native, ratchet, note }: StopLine): string[] => [
  ...(native === undefined
    ? []
    : [native.kind === "field" ? `field ${native.param}` : native.text]),
  ...(ratchet === undefined ? [] : [ratchet.label, ratchet.line]),
  ...(note === undefined ? [] : [note]),
];

describe("action entries over the server-written vocabulary (E37-S02)", () => {
  it("Gherkin 'The whole vocabulary is reachable on canvas': every served action is an entry with its display name and notes; a new one shows with no client change", () => {
    const vocabulary = served("manager");
    const options = actionOptions(vocabulary);
    expect(options).toHaveLength(24);
    expect(options.map((o) => o.id)).toEqual(vocabulary.actions.map((a) => a.id));
    vocabulary.actions.forEach((a, i) =>
      expect(options[i], a.id).toMatchObject({ label: a.display_name, notes: a.notes }),
    );
    expect(options.map((o) => o.id)).not.toContain("widen_stop"); // retired, never served (BQ-4)
    expect(actionOptions(extended()).at(-1)).toEqual({
      id: "zz_new_action",
      label: "New action",
      notes: "An action no client table names",
      treatment: {
        availability: "available",
        tag: undefined,
        reasonKey: undefined,
        reason: undefined,
        details: undefined,
        destructive: undefined,
      },
      stop: { native: undefined, ratchet: undefined, note: undefined },
    });
    // Served with no display name or notes, it still shows: by its id (P1).
    const bare = { ...actionOf(vocabulary, "halt_new_orders"), id: "zz_bare" };
    Reflect.deleteProperty(bare, "display_name");
    Reflect.deleteProperty(bare, "notes");
    expect(actionOptions({ ...vocabulary, actions: [bare] })[0]).toMatchObject({
      id: "zz_bare",
      label: "zz_bare",
      notes: "",
    });
  });

  it("Gherkin 'A forbidden action is not silently offered (security edge)': served without orders:write, the six order-placing actions stay pickable in simulate framing with the restriction in the details only, and every other gated action is T2 with its E09-D09 reason", () => {
    const options = actionOptions(served("no-orders-write"));
    const framed = options.filter((o) => o.treatment.availability === "simulate");
    expect(framed.map((o) => o.id)).toEqual(PLACING);
    for (const o of framed) {
      expect(o.treatment, o.id).toEqual({
        availability: "simulate",
        tag: "simulate only",
        reasonKey: undefined,
        reason: undefined,
        details: "Requires orders:write on at least one account; available in simulate mode only.",
        destructive: "places orders",
      });
    }
    const gated = options.filter((o) => o.treatment.availability === "gated");
    expect(gated.map((o) => [o.id, o.treatment.reasonKey, o.treatment.reason])).toEqual([
      ["modify_stop_loss", "rbac.permission.place_orders", PLACE_ORDERS],
      ["modify_take_profit", "rbac.permission.place_orders", PLACE_ORDERS],
      ["move_to_breakeven", "rbac.permission.place_orders", PLACE_ORDERS],
      ["scale_out", "rbac.permission.place_orders", PLACE_ORDERS],
      ["flatten_position", "rbac.permission.place_orders", PLACE_ORDERS],
      ["flatten_all_positions", "rbac.permission.place_orders", PLACE_ORDERS],
      ["cancel_order", "rbac.permission.place_orders", PLACE_ORDERS],
      ["cancel_all_orders", "rbac.permission.place_orders", PLACE_ORDERS],
      ["resume_new_orders", "rbac.owner_only.arm_live", ARM_LIVE],
      ["reduce_leverage", "rbac.permission.place_orders", PLACE_ORDERS],
      ["tighten_stop", "rbac.permission.place_orders", PLACE_ORDERS],
    ]);
    // The served restriction names permission ids: the details carry it, the reason never does (P10).
    for (const o of gated) {
      expect(o.treatment.details, o.id).toMatch(/^Requires (orders:write|rules:arm_live)\.$/);
      expect(o.treatment.reason, o.id).not.toMatch(/Requires|orders:write|rules:arm_live/);
    }
    expect(
      options.filter((o) => o.treatment.availability === "available").map((o) => o.id),
    ).toEqual([
      "halt_new_orders",
      "send_notification",
      "log_journal_tag",
      "set_variable",
      "emit_signal",
      "pause_rule",
      "enable_rule",
    ]);
  });

  it("the seeded Manager (orders:write, no rules:arm_live) is served every order-placing action available and only resume_new_orders T2 (the AC's simulate framing for it is E36's open input O-1); the Owner every action", () => {
    const manager = actionOptions(served("manager")).filter(
      (o) => o.treatment.availability !== "available",
    );
    expect(manager.map((o) => [o.id, o.treatment])).toEqual([
      [
        "resume_new_orders",
        {
          availability: "gated",
          tag: undefined,
          reasonKey: "rbac.owner_only.arm_live",
          reason: ARM_LIVE,
          details: "Requires rules:arm_live.",
          destructive: undefined,
        },
      ],
    ]);
    const owner = actionOptions(served("owner"));
    expect(owner).toHaveLength(24);
    expect(owner.filter((o) => o.treatment.availability !== "available")).toEqual([]);
  });

  it("every T2 entry the four personas are served carries a keyed reason: none is disabled without a reason line (E09-D09 §2.1, §3.1)", () => {
    const reasons = PERSONAS.flatMap((persona) =>
      actionOptions(served(persona))
        .filter((o) => o.treatment.availability === "gated")
        .map((o) => o.treatment.reasonKey),
    );
    expect(reasons).toHaveLength(13);
    expect(reasons).not.toContain(undefined);
  });

  it("reads only the served flags, with no permission arithmetic: an action needing both permissions reads the owner-only reason, one no reason is keyed for has none, and a step-up never gates", () => {
    const resume = actionOf(served("manager"), "resume_new_orders");
    const both = { ...resume, required_permissions: ["orders:write", "rules:arm_live"] };
    expect(actionTreatment(both).reason).toBe(ARM_LIVE);
    const unkeyed = {
      ...resume,
      required_permissions: ["zz:new_permission"],
      restriction: "Requires zz:new_permission.",
    };
    expect(actionTreatment(unkeyed)).toMatchObject({
      availability: "gated",
      reasonKey: undefined,
      reason: undefined,
      details: "Requires zz:new_permission.",
    });
    // What the server serves decides: a required permission never gates an available action, nor does a step-up.
    const halt = actionOf(served("manager"), "halt_new_orders");
    const held = { ...halt, required_permissions: ["rules:arm_live"], requires_step_up: true };
    expect(actionTreatment(held).availability).toBe("available");
    expect(actionTreatment({ ...halt, available: false }).availability).toBe("gated");
    expect(actionTreatment({ ...halt, simulate_only: true }).availability).toBe("simulate");
    // Served without `available`, an action reads as `22`'s default, `true`: no reason the session does not have.
    const unflagged = { ...actionOf(served("owner"), "place_order") };
    Reflect.deleteProperty(unflagged, "available");
    expect(actionTreatment(unflagged)).toMatchObject({
      availability: "available",
      reason: undefined,
    });
  });

  it("names the destructive class: 'places orders' on the six order-placing actions, 'flattens' on the two flatten actions, no word elsewhere", () => {
    const words = actionOptions(served("owner")).flatMap((o) =>
      o.treatment.destructive === undefined ? [] : [[o.id, o.treatment.destructive]],
    );
    expect(Object.fromEntries(words)).toEqual({
      place_order: "places orders",
      scale_in: "places orders",
      flatten_position: "flattens",
      flatten_all_positions: "flattens",
      reverse_position: "places orders",
      arm_chase_limit: "places orders",
      start_iceberg_slice: "places orders",
      start_twap: "places orders",
    });
  });
});

describe("the native stop on every order-placing action (C-2.6; E37-D02 A1)", () => {
  it("every action that can open or add to a position shows its native stop, for every action each persona serves; no other action claims one", () => {
    for (const persona of PERSONAS) {
      for (const action of served(persona).actions) {
        const { native } = stopLineOf(action);
        expect(native !== undefined, `${persona} ${action.id}`).toBe(placesOrders(action));
        expect(placesOrders(action), `${persona} ${action.id}`).toBe(PLACING.includes(action.id));
      }
    }
  });

  it("draws place_order's stop_loss field, FZ-7 on scale_in, FZ-8 on the other four, and FZ-6 with FS-3 on the stop actions, each byte for byte, sl.note under the field and the stop rows", () => {
    const lines = Object.fromEntries(
      served("owner").actions.flatMap((a) => {
        const words = said(stopLineOf(a));
        return words.length === 0 ? [] : [[a.id, words]];
      }),
    );
    expect(lines).toEqual({
      place_order: ["field stop_loss", FS1],
      modify_stop_loss: [FZ6, FS3, FS1],
      move_to_breakeven: [FZ6, FS3, FS1],
      scale_in: [FZ7],
      reverse_position: [FZ8],
      tighten_stop: [FZ6, FS3, FS1],
      arm_chase_limit: [FZ8],
      start_iceberg_slice: [FZ8],
      start_twap: [FZ8],
    });
    // The field follows a served stop_loss, never the id: scale_in serving one (its carrier, D02-G16) draws it.
    const scaleIn = actionOf(served("owner"), "scale_in");
    const carrier = {
      ...scaleIn,
      params_schema: { type: "object", properties: { qty: {}, stop_loss: { type: "object" } } },
    };
    expect(said(stopLineOf(carrier))).toEqual(["field stop_loss", FS1]);
  });

  it("an action served without places_orders reads as placing orders, with the word and its native stop line, as with true; only false drops them (22's absent-value rule, #5803 R2S-02)", () => {
    for (const action of served("owner").actions) {
      const absent = withoutFlag(action);
      expect(Object.hasOwn(absent, "places_orders"), action.id).toBe(false);
      const asTrue = { ...action, places_orders: true };
      const asFalse = { ...action, places_orders: false };
      expect(placesOrders(absent), action.id).toBe(true);
      expect(actionTreatment(absent), action.id).toEqual(actionTreatment(asTrue));
      expect(actionTreatment(absent).destructive, action.id).toBe("places orders");
      expect(stopLineOf(absent), action.id).toEqual(stopLineOf(asTrue));
      expect(stopLineOf(absent).native, action.id).toBeDefined();
      expect(stopLineOf(asFalse).native, action.id).toBeUndefined();
    }
    // A served false drops the "places orders" word: only the two flatten actions keep a word, their own.
    const owner = served("owner");
    expect(
      owner.actions
        .map((a) => [a.id, actionTreatment({ ...a, places_orders: false }).destructive])
        .filter(([, word]) => word !== undefined),
    ).toEqual([
      ["flatten_position", "flattens"],
      ["flatten_all_positions", "flattens"],
    ]);
    // A served action that places orders and lost the flag keeps its own stop: the field, or FZ-7.
    expect(said(stopLineOf(withoutFlag(actionOf(owner, "place_order"))))).toEqual([
      "field stop_loss",
      FS1,
    ]);
    expect(said(stopLineOf(withoutFlag(actionOf(owner, "scale_in"))))).toEqual([FZ7]);
  });
});

describe("the action node's scope line (BQ-9, PROPOSED)", () => {
  it("is the vocabulary's targets sentence for the action's value, verbatim, the rule scope's by default; none when the action serves none", () => {
    const vocabulary = served("manager");
    const values: readonly ActionTargets[] = [
      "scope_accounts",
      "originating_account",
      "all_accounts",
    ];
    const flatten = actionOf(vocabulary, "flatten_all_positions");
    expect([targetsSentence(flatten), ...values.map((v) => targetsSentence(flatten, v))]).toEqual([
      "every account in the rule scope",
      "every account in the rule scope",
      "the account whose event fired the rule",
      "every account the author can trade",
    ]);
    for (const action of vocabulary.actions) {
      for (const value of values) {
        expect(targetsSentence(action, value), `${action.id} ${value}`).toBe(
          action.targets?.[value],
        );
      }
    }
    const silent = { ...flatten };
    Reflect.deleteProperty(silent, "targets");
    expect([targetsSentence(silent), targetsSentence({ ...flatten, targets: {} })]).toEqual([
      undefined,
      undefined,
    ]);
    // A map that serves some values but not the one asked for has no sentence, never the rule scope's in its place.
    const partial = { ...flatten, targets: { scope_accounts: "every account in the rule scope" } };
    expect(targetsSentence(partial, "all_accounts")).toBeUndefined();
  });
});
