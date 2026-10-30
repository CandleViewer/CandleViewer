/** E08-D05 §8's shared key API (`keys.ts`, C2 owns it for SCR-102 and SCR-041): the chords that close and go on. */
import type { KeyboardEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { globalChord, stopKeys } from "../../../src/features/symbol-search/keys";
import { getBindings, resetBindings, setBindings } from "../../../src/keymap/profile";

type Mods = Partial<Record<"ctrlKey" | "altKey" | "shiftKey" | "metaKey", boolean>>;
/** A keydown as a surface's React root sees it. */
const press = (key: string, mods: Mods = {}) => {
  const stopPropagation = vi.fn();
  const base = { key, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false };
  const event = { ...base, ...mods, stopPropagation } as unknown as KeyboardEvent;
  return { event, stopPropagation };
};

afterEach(() => {
  resetBindings();
});

describe("globalChord", () => {
  it.each<[string, string, Mods, boolean]>([
    ["Ctrl+K", "k", { ctrlKey: true }, true],
    ["Cmd+K, read as Ctrl", "k", { metaKey: true }, true],
    ["Ctrl+/", "/", { ctrlKey: true }, true],
    ["Ctrl+Shift+A", "A", { ctrlKey: true, shiftKey: true }, true],
    ["F11", "F11", {}, true],
    ["Alt+3, which a range binding never equals", "3", { altKey: true }, false],
    ["an unbound Ctrl chord", "q", { ctrlKey: true }, false],
    ["a typed key", "b", {}, false],
  ])("%s: %#", (_name, key, mods, chord) => {
    expect(globalChord(press(key, mods).event)).toBe(chord);
  });

  it("a Global command rebound to a printable key is no chord: `/` stays in the field (A-D05-2)", () => {
    setBindings(new Map([...getBindings(), ["global.cheatsheet", "/"]]));
    const chords = [press("/"), press("/", { ctrlKey: true })].map(({ event }) =>
      globalChord(event),
    );
    expect(chords).toEqual([false, false]);
  });
});

describe("stopKeys", () => {
  it("a Global chord closes the surface and goes on to the window keymap; any other key stops at the root", () => {
    const close = vi.fn();
    const [chord, typed] = [press("k", { ctrlKey: true }), press("f")];
    stopKeys(chord.event, close);
    stopKeys(typed.event, close);
    const stopped = [chord, typed].map(({ stopPropagation }) => stopPropagation.mock.calls.length);
    expect([close.mock.calls.length, stopped]).toEqual([1, [0, 1]]);
  });
});
