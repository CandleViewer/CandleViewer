import { describe, expect, it } from "vitest";
import {
  EMPTY_DOC,
  HISTORY_LIMIT,
  invert,
  reduce,
  type SymbolDoc,
} from "../../../src/features/drawings/store/history.js";
import { asHandle, type Command } from "../../../src/features/drawings/store/types.js";
import { counter, input } from "./fixtures.js";

const h = asHandle;

function created(mint = counter()): { doc: SymbolDoc; mint: () => string } {
  const step = reduce(
    EMPTY_DOC,
    { type: "do", command: { kind: "create", handle: h("a"), input: input() } },
    mint,
  );
  return { doc: step.doc, mint };
}

describe("drawing history reducer", () => {
  it("create records one entry and emits a create under a minted id", () => {
    const step = reduce(
      EMPTY_DOC,
      { type: "do", command: { kind: "create", handle: h("a"), input: input() } },
      counter(),
    );
    expect(step.mutations).toEqual([{ op: "create", id: "id-1", input: input() }]);
    expect(step.doc.undo).toHaveLength(1);
    expect(step.doc.drawings.get(h("a"))).toMatchObject({ id: "id-1", token: null, base: null });
  });

  it("undo of a delete re-creates identical content under a NEW id; redo deletes it again", () => {
    const { doc, mint } = created();
    const before = doc.drawings.get(h("a"));
    const del = reduce(
      doc,
      { type: "do", command: { kind: "delete", handle: h("a"), input: input() } },
      mint,
    );
    expect(del.mutations).toEqual([{ op: "delete", id: "id-1" }]);
    const undone = reduce(del.doc, { type: "undo" }, mint);
    const back = undone.doc.drawings.get(h("a"));
    expect(back?.id).toBe("id-2");
    expect(back?.input).toEqual(before?.input);
    expect(undone.mutations).toEqual([{ op: "create", id: "id-2", input: input() }]);
    const redone = reduce(undone.doc, { type: "redo" }, mint);
    expect(redone.mutations).toEqual([{ op: "delete", id: "id-2" }]);
    expect(redone.doc.drawings.has(h("a"))).toBe(false);
  });

  it("redo of an undone create re-creates under a NEW id each time", () => {
    const { doc, mint } = created();
    const undone = reduce(doc, { type: "undo" }, mint);
    expect(undone.mutations).toEqual([{ op: "delete", id: "id-1" }]);
    const redone = reduce(undone.doc, { type: "redo" }, mint);
    expect(redone.mutations).toEqual([{ op: "create", id: "id-2", input: input() }]);
    const again = reduce(reduce(redone.doc, { type: "undo" }, mint).doc, { type: "redo" }, mint);
    expect(again.doc.drawings.get(h("a"))?.id).toBe("id-3");
  });

  it("a new command clears redo", () => {
    const { doc, mint } = created();
    const undone = reduce(doc, { type: "undo" }, mint);
    expect(undone.doc.redo).toHaveLength(1);
    const again = reduce(
      undone.doc,
      { type: "do", command: { kind: "create", handle: h("b"), input: input() } },
      mint,
    );
    expect(again.doc.redo).toEqual([]);
  });

  it("history is bounded at 100: 150 commands keep the newest 100", () => {
    let doc = created().doc;
    const mint = counter("m");
    for (let i = 0; i < 150; i += 1) {
      const rec = doc.drawings.get(h("a"));
      if (rec === undefined) throw new Error("missing");
      const after = input("BTCUSDT", { z_index: i + 1 });
      doc = reduce(
        doc,
        { type: "do", command: { kind: "update", handle: h("a"), before: rec.input, after } },
        mint,
      ).doc;
    }
    expect(doc.undo).toHaveLength(HISTORY_LIMIT);
    const last = doc.undo.at(-1);
    expect(last?.kind === "update" && last.after.z_index).toBe(150);
    const first = doc.undo[0];
    expect(first?.kind === "update" && first.after.z_index).toBe(51);
    // Redo onto a full history also stays bounded.
    const undone = reduce(doc, { type: "undo" }, mint);
    expect(reduce(undone.doc, { type: "redo" }, mint).doc.undo).toHaveLength(HISTORY_LIMIT);
  });

  it("undo and redo on empty stacks change nothing", () => {
    expect(reduce(EMPTY_DOC, { type: "undo" }, counter()).doc).toBe(EMPTY_DOC);
    expect(reduce(EMPTY_DOC, { type: "redo" }, counter()).doc).toBe(EMPTY_DOC);
  });

  it("an undo whose target is gone is dropped and reported, never resurrected", () => {
    const { doc, mint } = created();
    const rec = doc.drawings.get(h("a"));
    if (rec === undefined) throw new Error("missing");
    const moved = reduce(
      doc,
      {
        type: "do",
        command: {
          kind: "update",
          handle: h("a"),
          before: rec.input,
          after: input("BTCUSDT", { z_index: 3 }),
        },
      },
      mint,
    ).doc;
    const gone: SymbolDoc = { ...moved, drawings: new Map() };
    const step = reduce(gone, { type: "undo" }, mint);
    expect(step.unavailable).toBe(true);
    expect(step.mutations).toEqual([]);
    expect(step.doc.undo).toHaveLength(1);
    expect(step.doc.drawings.size).toBe(0);
    // Same for redo.
    const redoGone: SymbolDoc = { drawings: new Map(), undo: [], redo: moved.undo };
    const r = reduce(redoGone, { type: "redo" }, mint);
    expect(r.unavailable).toBe(true);
    expect(r.doc.redo).toHaveLength(1);
  });

  it("a do on a missing target or a taken handle is refused without a history entry", () => {
    const { doc, mint } = created();
    const step = reduce(
      doc,
      { type: "do", command: { kind: "create", handle: h("a"), input: input() } },
      mint,
    );
    expect(step.unavailable).toBe(true);
    expect(step.doc).toBe(doc);
  });

  it("a batch is one entry, applies atomically and inverts in reverse order", () => {
    const { doc, mint } = created();
    const batch: Command = {
      kind: "batch",
      commands: [
        { kind: "create", handle: h("b"), input: input("BTCUSDT", { z_index: 1 }) },
        { kind: "delete", handle: h("a"), input: input() },
      ],
    };
    const step = reduce(doc, { type: "do", command: batch }, mint);
    expect(step.doc.undo).toHaveLength(2);
    expect([...step.doc.drawings.keys()]).toEqual([h("b")]);
    const undone = reduce(step.doc, { type: "undo" }, mint);
    expect(undone.mutations.map((m) => m.op)).toEqual(["create", "delete"]);
    expect([...undone.doc.drawings.keys()].sort()).toEqual([h("a")]);
  });

  it("untouched records keep their reference (structural sharing)", () => {
    const mint = counter();
    let doc = EMPTY_DOC;
    for (const k of ["a", "b"]) {
      doc = reduce(
        doc,
        { type: "do", command: { kind: "create", handle: h(k), input: input() } },
        mint,
      ).doc;
    }
    const b = doc.drawings.get(h("b"));
    const next = reduce(
      doc,
      { type: "do", command: { kind: "delete", handle: h("a"), input: input() } },
      mint,
    ).doc;
    expect(next.drawings.get(h("b"))).toBe(b);
  });

  it("invert is an involution on every command kind", () => {
    const cases: Command[] = [
      { kind: "create", handle: h("a"), input: input() },
      { kind: "delete", handle: h("a"), input: input() },
      {
        kind: "update",
        handle: h("a"),
        before: input(),
        after: input("BTCUSDT", { locked: true }),
      },
      {
        kind: "batch",
        commands: [
          { kind: "create", handle: h("a"), input: input() },
          { kind: "delete", handle: h("b"), input: input() },
        ],
      },
    ];
    for (const c of cases) expect(invert(invert(c))).toEqual(c);
  });

  it("seeded random sequences: undoing everything restores the content, redoing restores the end", () => {
    // mulberry32 (exact 32-bit integer maths); rejection sampling keeps `% n` unbiased.
    let seed = 7;
    const next32 = (): number => {
      seed = (seed + 0x6d2b79f5) | 0;
      let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return (x ^ (x >>> 14)) >>> 0;
    };
    const rnd = (n: number): number => {
      const limit = Math.floor(4_294_967_296 / n) * n;
      for (;;) {
        const v = next32();
        if (v < limit) return v % n;
      }
    };
    const mint = counter("s");
    const content = (d: SymbolDoc): string =>
      JSON.stringify([...d.drawings.entries()].map(([k, v]) => [k, v.input]).sort());
    for (let round = 0; round < 20; round += 1) {
      let doc = EMPTY_DOC;
      const steps = 5 + rnd(30);
      for (let i = 0; i < steps; i += 1) {
        const handles = [...doc.drawings.keys()];
        const pick = handles[rnd(Math.max(handles.length, 1))];
        const kind = pick === undefined ? 0 : rnd(3);
        let command: Command;
        if (kind === 0 || pick === undefined) {
          command = {
            kind: "create",
            handle: h(`r${round}-${i}`),
            input: input("BTCUSDT", { z_index: i }),
          };
        } else {
          const rec = doc.drawings.get(pick);
          if (rec === undefined) throw new Error("missing");
          command =
            kind === 1
              ? {
                  kind: "update",
                  handle: pick,
                  before: rec.input,
                  after: input("BTCUSDT", { z_index: 1000 + i }),
                }
              : { kind: "delete", handle: pick, input: rec.input };
        }
        doc = reduce(doc, { type: "do", command }, mint).doc;
      }
      const end = content(doc);
      let back = doc;
      while (back.undo.length > 0) back = reduce(back, { type: "undo" }, mint).doc;
      expect(back.drawings.size).toBe(0);
      while (back.redo.length > 0) back = reduce(back, { type: "redo" }, mint).doc;
      expect(content(back)).toBe(end);
    }
  });
});
