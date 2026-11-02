/**
 * E29-S02 PR3a (#912) the amend's model (`model/amend.ts`): `24` §8.10's classification and the arm
 * (P3-BQ-5), the one-field body (P3-BQ-1), and the reducers that resolve an amend on the venue's word
 * alone (P3-BQ-7), from the goldens' three `change: "amend"` steps and their fault: "Optimistic amend
 * is clearly pending" and "Amend rejection leaves the order untouched".
 */
import { describe, expect, it } from "vitest";
import {
  AMEND_STALE_MS,
  amendBody,
  announcementOf,
  answerOf,
  armToken,
  momentLine,
  needsArm,
  NO_ARM,
  onAnswer,
  onItem,
  onTick,
  overlayOf,
  qtyFloor,
  requestFault,
  riskClass,
  type PendingMutation,
} from "../../../../src/features/positions/orders/model/amend";
import {
  mapOrder,
  type OrderConstants,
  type OrderRowModel,
  type WsOrder,
} from "../../../../src/features/positions/orders/model/orderRow";
import { figure } from "../../../../src/features/positions/orders/view";
import { repoFile } from "../../../lib/ws/support/schemaHarness";
import {
  ADOPTED,
  COND,
  deltaBody,
  directory,
  ENTRY,
  ETH,
  golden,
  NEW,
  snapshotBody,
  STOP,
  TP,
  wsItem,
  type DeltaCase,
} from "./support/orders";

const NONE: OrderConstants = { createdAtMs: null, provenance: null, tradeGroupId: null };

/** A golden snapshot order as a row, its wire fields overridden. */
function row(id: string, wire: Record<string, unknown> = {}, dir = directory()): OrderRowModel {
  const mapped = mapOrder({ ...wsItem(snapshotBody(), id), ...wire } as WsOrder, "ws", dir, NONE);
  if (mapped === null) throw new Error(`no row for ${id}`);
  return mapped;
}
/** A golden step as a snapshot carries it: no `change` key at all, as `ws_topics.py` builds one. */
function asRead(item: WsOrder): WsOrder {
  const read = { ...item };
  delete read.change;
  return read;
}
/** A golden delta's item for `id`. */
const step = (name: DeltaCase, id = ETH): WsOrder => wsItem(deltaBody(name), id);

/** The AC's specimen (D02 §7): Sub-2's ETHUSDT entry, 2,500 → 2,495.00, just pressed. */
function pending(over: Partial<PendingMutation> = {}): PendingMutation {
  return {
    orderId: ETH,
    seq: 1,
    field: "price",
    requested: "2495.00",
    prior: "2500",
    sentAt: 0,
    phase: "pending",
    sawPending: false,
    http: "none",
    httpAt: null,
    said: null,
    held: null,
    refusal: null,
    ...over,
  };
}

/** The policy corpus's instrument steps (`packages/fixtures/golden/policy/corpus.json`). */
function corpusSteps(symbol: string): { qtyStep: string; minOrderQty: string | null } {
  const corpus = JSON.parse(repoFile("packages/fixtures/golden/policy/corpus.json")) as {
    cases: { instrument: { symbol: string; qty_step: string; min_order_qty: string | null } }[];
  };
  const found = corpus.cases.find((c) => c.instrument.symbol === symbol)?.instrument;
  if (found === undefined) throw new Error(`no corpus instrument ${symbol}`);
  return { qtyStep: found.qty_step, minOrderQty: found.min_order_qty };
}

describe("risk-increasing amends: 24 §8.10's one definition (P3-BQ-5)", () => {
  it("a price or trigger change of an order that is not reduce-only is risk-increasing either way (M9)", () => {
    expect(riskClass(row(ETH), "price", "2495.00")).toBe("increasing");
    expect(riskClass(row(ETH), "price", "2505.00")).toBe("increasing");
    expect(riskClass(row(COND), "trigger_price", "64400.0")).toBe("increasing");
    expect(riskClass(row(COND), "price", null)).toBe("increasing");
  });

  it("a quantity raised is risk-increasing and a cut is none (M7)", () => {
    expect(riskClass(row(ENTRY), "qty", "0.200")).toBe("increasing");
    expect(riskClass(row(ENTRY), "qty", "0.100")).toBe("none");
    expect(riskClass(row(ENTRY), "qty", "0.150")).toBe("none");
  });

  it("any edit of a reduce-only order, and a take-profit's change, is none (M8)", () => {
    expect(riskClass(row(TP), "price", "64850.0")).toBe("none");
    expect(riskClass(row(TP), "qty", "0.300")).toBe("none");
    expect(riskClass(row(STOP), "trigger_price", "63980.0")).toBe("none");
    expect(riskClass(row(ETH, { intent: "take_profit" }), "price", "2495.00")).toBe("none");
  });

  it("a quantity this client cannot read is risk-increasing (fail closed)", () => {
    expect(riskClass(row(ENTRY), "qty", "1e3")).toBe("increasing");
    expect(riskClass(row(ENTRY, { qty: "junk" }), "qty", "0.100")).toBe("increasing");
  });

  it("a live risk-increasing amend needs the arm; demo and testnet never do (M10)", () => {
    expect(needsArm(row(ETH), "price", "2495.00")).toBe(true);
    expect(needsArm(row(ETH, { environment: "demo" }), "price", "2495.00")).toBe(false);
    expect(needsArm(row(ETH, { environment: "testnet" }), "price", "2495.00")).toBe(false);
    expect(needsArm(row(ETH, { environment: "demo" }), "qty", "2.00")).toBe(false);
  });

  it("an environment this client does not know needs the arm, as live (M12)", () => {
    const unknown = row(ETH, { environment: undefined }, new Map());
    expect(unknown.environment).toBeNull();
    expect(needsArm(unknown, "price", "2495.00")).toBe(true);
  });

  it("a cut and a take-profit's change never need it, live or not (C-2.6, R5)", () => {
    expect(needsArm(row(ENTRY), "qty", "0.100")).toBe(false);
    expect(needsArm(row(TP), "price", "64850.0")).toBe(false);
  });

  it("the arm's token: a usable string or none; a source that throws holds none", () => {
    expect(armToken(NO_ARM, ETH)).toBeNull();
    expect(armToken({ token: () => "t-1" }, ETH)).toBe("t-1");
    expect(armToken({ token: () => "" }, ETH)).toBeNull();
    expect(armToken({ token: () => "x".repeat(257) }, ETH)).toBeNull();
    const throwing = {
      token: (): string => {
        throw new Error("port down");
      },
    };
    expect(armToken(throwing, ETH)).toBeNull();
  });
});

describe("the body: one field, never a stop (P3-BQ-1)", () => {
  it("is the golden specimen's, one key, decimal text (M21)", () => {
    expect(amendBody("price", "2495.00")).toEqual(golden("rest_amend_order_request.json"));
    for (const field of ["price", "trigger_price", "qty"] as const) {
      const body = amendBody(field, "1.5");
      expect(Object.keys(body ?? {})).toEqual([field]);
      expect(body).not.toHaveProperty("stop_loss");
      expect(body).not.toHaveProperty("take_profit");
    }
  });

  it.each(["0", "-1", "1e3", "", "2,495.00", " 2495"])("refuses %j: no body", (text) => {
    expect(amendBody("price", text)).toBeNull();
  });

  it("names why a request is not sendable: absent, invalid, unchanged, not above the fill", () => {
    expect(requestFault(row(STOP), "price", "63000.0")).toBe("absent"); // a market order: no price
    expect(requestFault(row(ETH), "trigger_price", "2490.00")).toBe("absent");
    expect(requestFault(row(ETH), "price", "abc")).toBe("invalid");
    expect(requestFault(row(ETH), "price", "2500.00")).toBe("unchanged");
    expect(requestFault(row(ENTRY), "qty", "0.050")).toBe("not_above_filled");
    expect(requestFault(row(ENTRY), "qty", "0.051")).toBeNull();
    expect(requestFault(row(ETH), "price", "2495.00")).toBeNull();
  });

  it("the quantity floor is one lot above the fill, at least the instrument's minimum (D01:399)", () => {
    expect(qtyFloor(row(ENTRY), corpusSteps("BTCUSDT"))).toBe("0.051");
    expect(qtyFloor(row(ETH), corpusSteps("ETHUSDT"))).toBe("0.01");
    expect(qtyFloor(row(ENTRY), { qtyStep: "0.001", minOrderQty: "0.1" })).toBe("0.1");
  });
});

describe("Optimistic amend is clearly pending (P3-BQ-7)", () => {
  it("the request frame keeps it Amending, and counts the frames after it (M1)", () => {
    const { next, resolution } = onItem(pending(), step("amend_request"), "delta");
    expect(resolution).toBeNull();
    expect(next).toMatchObject({ phase: "pending", sawPending: true });
  });

  it("the venue's amend step with the requested value confirms it, and the entry leaves", () => {
    const after = onItem(pending({ sawPending: true }), step("amend_accepted"), "delta");
    expect(after).toEqual({ next: null, resolution: "confirmed" });
  });

  it("a 202 keeps it Amending: the frame confirms, never the answer (M2)", () => {
    const { next, resolution } = onAnswer(
      pending({ sawPending: true }),
      { kind: "accepted", lifecycle: "submitted" },
      2_000,
    );
    expect(resolution).toBeNull();
    expect(next).toMatchObject({ phase: "pending", http: "accepted", httpAt: 2_000 });
  });

  it("an accept frame before the request frame and the answer is held, then judged at the answer (M4)", () => {
    const early = onItem(pending(), step("amend_accepted"), "delta");
    expect(early.resolution).toBeNull();
    expect(early.next).toMatchObject({ phase: "pending", held: { via: "delta" } });
    const answered = onAnswer(
      early.next as PendingMutation,
      { kind: "accepted", lifecycle: null },
      9,
    );
    expect(answered).toEqual({ next: null, resolution: "confirmed" });
  });

  it("a step that is not the amend's answer leaves it Amending", () => {
    const counted = pending({ sawPending: true });
    expect(onItem(counted, step("acked", NEW), "delta")).toEqual({
      next: counted,
      resolution: null,
    });
  });

  it("the cell keeps the confirmed value while Amending, never the requested one (M5)", () => {
    expect(overlayOf(row(ETH), pending(), figure)).toEqual({
      value: "2,500",
      line: "Amending → 2,495 · 2,500 still live",
    });
  });

  it("confirmed is said politely once in the deck's words (RT-14); a trigger's and a quantity's are PROPOSED", () => {
    expect(announcementOf(pending(), "confirmed", figure)).toEqual({
      politeness: "polite",
      text: "Amend confirmed: price 2,495.",
    });
    const trigger = pending({ field: "trigger_price", requested: "64400.0", prior: "64500" });
    expect(announcementOf(trigger, "confirmed", figure)?.text).toBe(
      "Amend confirmed: trigger 64,400.",
    );
    const qty = pending({ field: "qty", requested: "0.100", prior: "0.15" });
    expect(announcementOf(qty, "confirmed", figure)?.text).toBe("Amend confirmed: quantity 0.1.");
  });
});

describe("Amend rejection leaves the order untouched", () => {
  it("the venue's amend step with the prior value rejects it (M3)", () => {
    const { next, resolution } = onItem(
      pending({ sawPending: true }),
      step("amend_rejected"),
      "delta",
    );
    expect(resolution).toBe("rejected");
    expect(next?.phase).toBe("rejected");
    expect(momentLine(next as PendingMutation, figure)).toBe(
      "Amend rejected — your order is unchanged",
    );
  });

  it("is said assertively in the deck's words, with no exchange text (RT-06)", () => {
    expect(announcementOf(pending(), "rejected", figure)).toEqual({
      politeness: "assertive",
      text: "Amend rejected. Your order is unchanged: the price is still 2,500.",
    });
    const qty = pending({ field: "qty", requested: "0.200", prior: "0.15" });
    expect(announcementOf(qty, "rejected", figure)?.text).toBe(
      "Amend rejected. Your order is unchanged: the quantity is still 0.15.",
    );
  });

  it("a 502 rejects it; a 502 after the rejection frame re-affirms it, one moment", () => {
    expect(onAnswer(pending(), { kind: "exchange_refused" }, 5).next?.phase).toBe("rejected");
    const rejected = onItem(pending({ sawPending: true }), step("amend_rejected"), "delta").next;
    const again = onAnswer(rejected as PendingMutation, { kind: "exchange_refused" }, 5);
    expect(again.resolution).toBe("rejected");
    expect(again.next?.phase).toBe("rejected");
  });

  it("a refusal is not sent, with its kind: the arm's in E30-D02's words, the rest PROPOSED", () => {
    const armed = onAnswer(pending(), { kind: "arm_refused" }, 5).next as PendingMutation;
    expect(armed).toMatchObject({ phase: "not_sent", refusal: "arm_refused", http: "refused" });
    expect(momentLine(armed, figure)).toBe("One-click trading is locked");
    const conflict = onAnswer(pending(), { kind: "conflict" }, 5).next as PendingMutation;
    expect(momentLine(conflict, figure)).toBe("Amend not sent — your order is unchanged");
    expect(announcementOf(conflict, "not_sent", figure)).toBeNull();
  });

  it("a refusal never overrules a frame that settled it, and only one answer counts", () => {
    const rejected = onItem(pending({ sawPending: true }), step("amend_rejected"), "delta").next;
    const refused = onAnswer(rejected as PendingMutation, { kind: "conflict" }, 5);
    expect(refused).toMatchObject({ resolution: null, next: { phase: "rejected" } });
    const answered = pending({ http: "accepted" });
    expect(onAnswer(answered, { kind: "exchange_refused" }, 5).next).toBe(answered);
  });

  it("a later amend step with the requested value confirms a rejected one: the frame is the truth", () => {
    const rejected = onAnswer(pending(), { kind: "exchange_refused" }, 5).next as PendingMutation;
    expect(onItem(rejected, step("amend_accepted"), "delta").resolution).toBe("confirmed");
  });
});

describe("Unknown, reconciliation and the stale bound (D01 D4 × Unknown)", () => {
  const reconciled = (name: "amend_accepted" | "amend_rejected"): WsOrder => ({
    ...step(name),
    change: "reconcile",
    updated_at_ms: step(name).updated_at_ms + 4_000,
  });

  it("the order going unknown reads Unknown — checking with the prior value", () => {
    const { next, resolution } = onItem(
      pending({ sawPending: true }),
      step("amend_unknown"),
      "delta",
    );
    expect(resolution).toBe("unconfirmed");
    expect(momentLine(next as PendingMutation, figure)).toBe(
      "Unknown — checking · 2,500 may still be live",
    );
  });

  it("a 202 that says unknown, and no answer, read Unconfirmed", () => {
    expect(answerOf({ kind: "accepted", lifecycle: "unknown" })).toBe("unknown");
    expect(onAnswer(pending(), { kind: "accepted", lifecycle: "unknown" }, 5).resolution).toBe(
      "unconfirmed",
    );
    expect(onAnswer(pending(), { kind: "unavailable" }, 5).next?.phase).toBe("unconfirmed");
  });

  it("reconciliation finding the requested value confirms it in D01:228's words", () => {
    const unknown = pending({ phase: "unconfirmed", sawPending: true });
    const after = onItem(unknown, reconciled("amend_accepted"), "delta");
    expect(after).toEqual({ next: null, resolution: "reconciled" });
    expect(announcementOf(unknown, "reconciled", figure)).toEqual({
      politeness: "polite",
      text: "Amend confirmed by reconciliation.",
    });
  });

  it("finding the prior value is not applied, in D01:229's words, said assertively once", () => {
    const unknown = pending({ phase: "unconfirmed", sawPending: true });
    const { next, resolution } = onItem(unknown, reconciled("amend_rejected"), "delta");
    expect(resolution).toBe("not_applied");
    expect(momentLine(next as PendingMutation, figure)).toBe("Amend not applied — still 2,500.");
    expect(announcementOf(unknown, "not_applied", figure)?.politeness).toBe("assertive");
  });

  it("a read never rejects a pending amend, nor one whose 202 took it", () => {
    const counted = pending({ sawPending: true });
    const read = wsItem(snapshotBody(), ETH);
    expect(onItem(counted, read, "snap")).toEqual({ next: counted, resolution: null });
    const taken = pending({ phase: "unconfirmed", http: "accepted" });
    expect(onItem(taken, read, "snap").resolution).toBeNull();
  });

  it("a snapshot showing the requested value confirms only once the 202 took it (a missed accept frame)", () => {
    const counted = pending({ sawPending: true });
    const read = asRead(step("amend_accepted"));
    expect(read).not.toHaveProperty("change");
    const early = onItem(counted, read, "snap");
    expect(early.resolution).toBeNull();
    expect(early.next?.held?.via).toBe("snap");
    const answered = onAnswer(
      early.next as PendingMutation,
      { kind: "accepted", lifecycle: null },
      9,
    );
    expect(answered).toEqual({ next: null, resolution: "confirmed" });
  });

  it("the stale bound reads Unconfirmed, never confirmed, from the press or the answer (M6)", () => {
    expect(onTick(pending(), AMEND_STALE_MS - 1).resolution).toBeNull();
    expect(onTick(pending(), AMEND_STALE_MS)).toMatchObject({
      resolution: "unconfirmed",
      next: { phase: "unconfirmed" },
    });
    const answered = pending({ http: "accepted", httpAt: 10_000 });
    expect(onTick(answered, 10_000 + AMEND_STALE_MS - 1).resolution).toBeNull();
    expect(onTick(answered, 10_000 + AMEND_STALE_MS).resolution).toBe("unconfirmed");
  });

  it("an ended, held or adopted order, or a third value, ends the overlay unsaid", () => {
    const counted = pending({ sawPending: true });
    expect(onItem(counted, step("cancel_lost_race", TP), "delta")).toEqual({
      next: null,
      resolution: "dropped",
    });
    expect(onItem(counted, step("held", COND), "delta").resolution).toBe("dropped");
    expect(onItem(counted, step("untracked_adopted", ADOPTED), "delta").resolution).toBe("dropped");
    const third = pending({ sawPending: true, requested: "2490.00" });
    expect(onItem(third, step("amend_accepted"), "delta").resolution).toBe("dropped");
    expect(announcementOf(counted, "dropped", figure)).toBeNull();
  });

  it("nothing sent: the line holds while the order keeps its prior value, and ends when it moves", () => {
    const refused = onAnswer(pending(), { kind: "conflict" }, 5).next as PendingMutation;
    expect(onItem(refused, step("amend_rejected"), "delta").next).toBe(refused);
    expect(onItem(refused, step("amend_accepted"), "delta").resolution).toBe("dropped");
  });
});
