import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  createDrawingStore,
  usePaneDrawings,
  useSaveStatus,
} from "../../../src/features/drawings/store/drawingStore.js";
import { asHandle } from "../../../src/features/drawings/store/types.js";
import { uuidv7 } from "../../../src/features/drawings/store/uuidv7.js";
import { counter, input, row } from "./fixtures.js";

const LAYOUT = "0193f2bb-0000-7000-8000-00000000000a";

describe("drawing store", () => {
  it("panes see their layout's drawings plus symbol-wide ones, by z_index, as a stable array", () => {
    const s = createDrawingStore({ mintId: counter() });
    s.create(input("BTCUSDT", { z_index: 5 }));
    s.create(input("BTCUSDT", { z_index: 1, layout_id: LAYOUT }));
    s.create(input("BTCUSDT", { layout_id: "other" }));
    const pane = s.selectPane("BTCUSDT", LAYOUT);
    expect(pane.map((d) => d.input.z_index)).toEqual([1, 5]);
    expect(s.selectPane("BTCUSDT", LAYOUT)).toBe(pane);
    expect(s.selectPane("BTCUSDT", null)).toHaveLength(1);
    expect(s.selectPane("ETHUSDT", null)).toEqual([]);
    s.create(input("ETHUSDT"));
    expect(s.selectPane("BTCUSDT", LAYOUT)).toBe(pane);
  });

  it("keeps independent undo stacks per symbol", () => {
    const s = createDrawingStore({ mintId: counter() });
    s.create(input("BTCUSDT"));
    s.create(input("ETHUSDT"));
    s.undo("ETHUSDT");
    expect(s.selectPane("ETHUSDT", null)).toEqual([]);
    expect(s.selectPane("BTCUSDT", null)).toHaveLength(1);
    s.redo("ETHUSDT");
    expect(s.selectPane("ETHUSDT", null)).toHaveLength(1);
  });

  it("update, updateMany and remove emit mutations; a no-op patch records nothing", () => {
    const s = createDrawingStore({ mintId: counter() });
    const seen = vi.fn();
    const off = s.onMutations(seen);
    const a = s.create(input());
    const b = s.create(input());
    s.update("BTCUSDT", a, { locked: false });
    expect(s.getSymbol("BTCUSDT").doc.undo).toHaveLength(2);
    s.update("BTCUSDT", a, { locked: true });
    s.update("BTCUSDT", asHandle("nope"), { locked: true });
    s.updateMany(
      "BTCUSDT",
      new Map([
        [a, { z_index: 2 }],
        [b, { z_index: 3 }],
      ]),
    );
    s.updateMany("BTCUSDT", new Map([[asHandle("nope"), { z_index: 2 }]]));
    expect(s.getSymbol("BTCUSDT").doc.undo).toHaveLength(4);
    s.remove("BTCUSDT", [asHandle("nope")]);
    s.remove("BTCUSDT", [a]);
    s.remove("BTCUSDT", [b]);
    expect(seen.mock.calls.map(([, m]) => m.map((x: { op: string }) => x.op))).toEqual([
      ["create"],
      ["create"],
      ["update"],
      ["update", "update"],
      ["delete"],
      ["delete"],
    ]);
    off();
    s.create(input());
    expect(seen).toHaveBeenCalledTimes(6);
  });

  it("removing several handles is one undo that re-creates them all under new ids", () => {
    const s = createDrawingStore({ mintId: counter() });
    const a = s.create(input());
    const b = s.create(input());
    s.remove("BTCUSDT", [a, b]);
    expect(s.selectPane("BTCUSDT", null)).toEqual([]);
    s.undo("BTCUSDT");
    const ids = s.selectPane("BTCUSDT", null).map((d) => d.id);
    expect(ids).toHaveLength(2);
    expect(ids).not.toContain("id-2");
    expect(ids).not.toContain("id-4");
  });

  it("an unavailable undo is reported once as a notice; notice listeners tear down", () => {
    const s = createDrawingStore({ mintId: counter() });
    const notices = vi.fn();
    const off = s.onNotice(notices);
    const a = s.create(input());
    s.update("BTCUSDT", a, { z_index: 9 });
    s.removeId("BTCUSDT", "id-2");
    s.undo("BTCUSDT");
    expect(notices).toHaveBeenCalledWith({ kind: "undo_unavailable", symbol: "BTCUSDT" });
    off();
    s.undo("BTCUSDT");
    expect(notices).toHaveBeenCalledTimes(1);
  });

  it("confirm keeps the token byte-exact and adopts content only when asked", () => {
    const s = createDrawingStore({ mintId: counter() });
    s.create(input());
    const token = "2026-09-13T12:00:00.100000Z";
    s.confirm(row("id-2", input("BTCUSDT", { label: "srv" }), token), false);
    expect(s.tokenOf("id-2")).toBe(token);
    expect(s.selectPane("BTCUSDT", null)[0]?.input.label).toBeNull();
    s.confirm(row("id-2", input("BTCUSDT", { label: "srv" }), token), true);
    expect(s.selectPane("BTCUSDT", null)[0]).toMatchObject({ token, input: { label: "srv" } });
    s.confirm(row("unknown", input()), true);
    expect(s.tokenOf("unknown")).not.toBeNull();
    s.confirmDeleted("unknown");
    expect(s.tokenOf("unknown")).toBeNull();
  });

  it("adopt tags the server version; removeId and remint act by id", () => {
    const s = createDrawingStore({ mintId: counter() });
    s.create(input());
    s.adopt(row("id-2", input("BTCUSDT", { z_index: 4 })));
    expect(s.selectPane("BTCUSDT", null)[0]).toMatchObject({
      tag: "conflict",
      input: { z_index: 4 },
    });
    s.adopt(row("fresh", input()));
    expect(s.selectPane("BTCUSDT", null)).toHaveLength(2);
    s.remint("BTCUSDT", "id-2", "id-9");
    expect(s.selectPane("BTCUSDT", null).map((d) => d.id)).toContain("id-9");
    s.remint("BTCUSDT", "missing", "x");
    s.removeId("BTCUSDT", "id-9");
    s.removeId("BTCUSDT", "missing");
    expect(s.selectPane("BTCUSDT", null).map((d) => d.id)).toEqual(["fresh"]);
  });

  it("hydrate takes server truth except for busy ids and unconfirmed creates", () => {
    const s = createDrawingStore({ mintId: counter() });
    s.hydrate("BTCUSDT", [row("s1", input()), row("s2", input()), row("s3", input())], () => false);
    const keep = s.selectPane("BTCUSDT", null).find((d) => d.id === "s3");
    s.create(input("BTCUSDT", { z_index: 7 }));
    s.update("BTCUSDT", asHandle("s1"), { label: "mine" });
    const s3 = row("s3", input(), keep?.token ?? "");
    s.hydrate(
      "BTCUSDT",
      [row("s1", input("BTCUSDT", { label: "theirs" })), s3, row("s4", input())],
      (id) => id === "s1",
    );
    const byId = new Map(s.selectPane("BTCUSDT", null).map((d) => [d.id, d]));
    expect(byId.get("s1")?.input.label).toBe("mine");
    expect(byId.has("s2")).toBe(false);
    expect(s.tokenOf("s2")).toBeNull();
    expect(byId.get("s3")).toBe(keep);
    expect(byId.has("s4")).toBe(true);
    expect(byId.has("id-2")).toBe(true);
  });

  it("hydrate never reverts a record to an older server version (a list answered before a commit)", () => {
    const s = createDrawingStore({ mintId: counter() });
    s.create(input());
    const newer = "2026-09-13T12:00:00.000200Z";
    s.confirm(row("id-2", input("BTCUSDT", { label: "dragged" }), newer), true);
    const stale = row("id-2", input("BTCUSDT", { label: "before" }), "2026-09-13T12:00:00.000100Z");
    s.hydrate("BTCUSDT", [stale], () => false);
    expect(s.selectPane("BTCUSDT", null)).toEqual([
      expect.objectContaining({
        token: newer,
        input: expect.objectContaining({ label: "dragged" }),
      }),
    ]);
    expect(s.tokenOf("id-2")).toBe(newer);
    const later = row("id-2", input("BTCUSDT", { label: "srv" }), "2026-09-13T12:00:00.000300Z");
    s.hydrate("BTCUSDT", [later], () => false);
    expect(s.selectPane("BTCUSDT", null)[0]?.input.label).toBe("srv");
  });

  it("adopt over a refused delete re-uses the handle history knows, so undo cannot duplicate", () => {
    const s = createDrawingStore({ mintId: counter() });
    const h = s.create(input());
    s.confirm(row("id-2", input()), true);
    s.remove("BTCUSDT", [h]);
    s.adopt(row("id-2", input("BTCUSDT", { label: "theirs" })));
    expect(s.getSymbol("BTCUSDT").doc.drawings.get(h)?.id).toBe("id-2");
    s.undo("BTCUSDT");
    expect(s.selectPane("BTCUSDT", null).map((d) => d.id)).toEqual(["id-2"]);
  });

  it("adopt keeps both objects when an undo already re-created the deleted handle", () => {
    const s = createDrawingStore({ mintId: counter() });
    const h = s.create(input());
    s.confirm(row("id-2", input()), true);
    s.remove("BTCUSDT", [h]);
    s.undo("BTCUSDT");
    s.adopt(row("id-2", input("BTCUSDT", { label: "theirs" })));
    expect(s.selectPane("BTCUSDT", null)).toHaveLength(2);
  });

  it("setStatus notifies only on change", () => {
    const s = createDrawingStore();
    const l = vi.fn();
    const off = s.subscribe(l);
    s.setStatus("BTCUSDT", { kind: "saved" });
    expect(l).not.toHaveBeenCalled();
    s.setStatus("BTCUSDT", { kind: "unsaved", retryable: true });
    s.setStatus("BTCUSDT", { kind: "unsaved", retryable: true });
    s.setStatus("BTCUSDT", { kind: "unsaved", retryable: false });
    expect(l).toHaveBeenCalledTimes(2);
    off();
    s.setStatus("BTCUSDT", { kind: "pending" });
    expect(l).toHaveBeenCalledTimes(2);
  });

  it("hooks re-render on change and unsubscribe on unmount", () => {
    const base = createDrawingStore({ mintId: counter() });
    let active = 0;
    const s = {
      ...base,
      subscribe: (listener: () => void) => {
        active += 1;
        const off = base.subscribe(listener);
        return () => {
          active -= 1;
          off();
        };
      },
    };
    const pane = renderHook(() => usePaneDrawings(s, "BTCUSDT", null));
    const status = renderHook(() => useSaveStatus(s, "BTCUSDT"));
    expect(pane.result.current).toEqual([]);
    act(() => {
      s.create(input());
      s.setStatus("BTCUSDT", { kind: "pending" });
    });
    expect(pane.result.current).toHaveLength(1);
    expect(status.result.current).toEqual({ kind: "pending" });
    expect(active).toBe(2);
    pane.unmount();
    status.unmount();
    expect(active).toBe(0);
  });
});

describe("uuidv7", () => {
  it("encodes the ms timestamp, version 7 and variant 10", () => {
    const id = uuidv7(0x0193f2bb1234, (b) => b.fill(0xff));
    expect(id).toMatch(/^0193f2bb-1234-7fff-bfff-ffffffffffff$/);
    expect(uuidv7()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });
});
