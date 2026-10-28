// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect } from "storybook/test";
import { describe, it, vi } from "vitest";
import { Kbd } from "../src/components/index.js";
import { kbdExpansion } from "../src/components/Kbd.js";
import * as stories from "../src/components/Kbd.stories.js";
import { mount } from "./theme/mount.js";

const caps = (host: HTMLElement): string[] =>
  [...host.querySelectorAll(".cv-kbd__cap")].map((c) => c.textContent ?? "");

/**
 * The digit-range pattern Kbd used before its linear split (CodeQL js/polynomial-redos), kept here
 * as the oracle for short keys only: on a long run of "." before a line break it backtracks in
 * quadratic time.
 */
const LEGACY_RANGE = /^(.+?)\.\.(.+)$/;
/** What `kbdExpansion` said for one key under the legacy pattern, with no name table. */
const legacyExpansion = (key: string): string => {
  const range = LEGACY_RANGE.exec(key);
  return range?.[1] !== undefined && range[2] !== undefined ? `${range[1]} to ${range[2]}` : key;
};
/** Every string of up to `max` characters over `alphabet`, the empty one included. */
const allKeys = (alphabet: readonly string[], max: number): string[] => {
  const keys = [""];
  let level = [""];
  for (let length = 1; length <= max; length += 1) {
    level = level.flatMap((prefix) => alphabet.map((c) => prefix + c));
    keys.push(...level);
  }
  return keys;
};
/** Runs `work`, counting the String scans (`indexOf`, `includes`) and the RegExp runs it made. */
const counted = (work: () => void): { scans: number; regexRuns: number } => {
  const scans = [vi.spyOn(String.prototype, "indexOf"), vi.spyOn(String.prototype, "includes")];
  const exec = vi.spyOn(RegExp.prototype, "exec");
  try {
    work();
    return {
      scans: scans.reduce((sum, spy) => sum + spy.mock.calls.length, 0),
      regexRuns: exec.mock.calls.length,
    };
  } finally {
    for (const spy of [...scans, exec]) spy.mockRestore();
  }
};

describe("Kbd (CMP-022)", () => {
  it("renders one kbd cap per key inside an outer kbd, caps hidden, read once", async () => {
    const host = await mount(<Kbd keys={["Ctrl", "Shift", "K"]} />);
    const outer = host.querySelector("kbd.cv-kbd");
    expect(outer?.getAttribute("data-cmp")).toBe("CMP-022");
    expect(caps(host)).toEqual(["Ctrl", "Shift", "K"]);
    expect(outer?.querySelectorAll("kbd.cv-kbd__cap")).toHaveLength(3);
    expect(host.querySelector(".cv-kbd__caps")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent(
      /^Control plus Shift plus K$/,
    );
    expect(outer?.textContent).not.toContain("+");
    expect(outer).not.toHaveAttribute("tabindex");
  });

  it.each([[[]], [[""]], [["  ", ""]]])("renders nothing when unbound (%j)", async (keys) => {
    const host = await mount(<Kbd keys={keys} />);
    expect(host).toBeEmptyDOMElement();
  });

  it("renders a digit range as two caps with an en dash", async () => {
    const host = await mount(<Kbd keys={["Alt", "1..9"]} />);
    expect(caps(host)).toEqual(["Alt", "1", "9"]);
    expect(host.querySelector(".cv-kbd__range .cv-kbd__word")).toHaveTextContent(/^–$/);
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent(/^Alt plus 1 to 9$/);
  });

  it.each([
    [["Ctrl", "click"], "click", "Control plus click"],
    [["Shift", "wheel"], "wheel", "Shift plus wheel"],
    [["Space", "drag"], "drag", "Space plus drag"],
  ])("renders the pointer chord %j as caps plus the word as text", async (keys, word, spoken) => {
    const host = await mount(<Kbd keys={keys} />);
    expect(caps(host)).toEqual([keys[0]]);
    expect(host.querySelector(".cv-kbd__word")).toHaveTextContent(word);
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent(spoken);
  });

  it("takes the keymap's name table over the catalogue's words", () => {
    expect(kbdExpansion(["Ctrl", "Del"], { Del: "Delete" })).toBe("Control plus Delete");
    expect(kbdExpansion(["Ctrl", "K"], { Ctrl: "Command" })).toBe("Command plus K");
  });

  it("reads inherited member names as written, never as the prototype's members", () => {
    expect(kbdExpansion(["constructor", "toString", "__proto__"])).toBe(
      "constructor plus toString plus __proto__",
    );
    expect(kbdExpansion(["Ctrl", "hasOwnProperty"], {})).toBe("Control plus hasOwnProperty");
  });

  it("can be hidden whole inside a menu item, which carries aria-keyshortcuts", async () => {
    const host = await mount(<Kbd keys={["Ctrl", "S"]} aria-hidden="true" />);
    expect(host.querySelector(".cv-kbd")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Kbd's digit-range split (linear time)", () => {
  it.each([
    ["1..9", "1 to 9"],
    ["F1..F12", "F1 to F12"],
    ["1...9", "1 to .9"],
    ["a....b", "a to ..b"],
    ["1..2..3", "1 to 2..3"],
    ["Ctrl..Shift", "Control to Shift"],
    ["..9", "..9"],
    ["1..", "1.."],
    ["...", "..."],
    ["..", ".."],
    ["1..9\n", "1..9\n"],
    ["1\r..9", "1\r..9"],
    ["1..\u20289", "1..\u20289"],
    ["\u20291..9", "\u20291..9"],
  ])("reads %j as %j", (key, said) => {
    expect(kbdExpansion([key])).toBe(said);
  });

  it("splits every key of up to 6 characters over '.', '1', space, LF and PS as the legacy pattern did", () => {
    const keys = allKeys([".", "1", " ", "\n", "\u2029"], 6);
    expect(keys).toHaveLength(19_531);
    expect(keys.filter((key) => kbdExpansion([key]) !== legacyExpansion(key))).toEqual([]);
  });

  it("renders a range found past a leading dot as two caps", async () => {
    const host = await mount(<Kbd keys={[".a..b"]} />);
    expect(caps(host)).toEqual([".a", "b"]);
  });

  // The legacy pattern's worst cases are a long run of "." (each one a ".." for the lazy group to
  // try) ahead of a character "." does not match, a line break: ~9 s each at 50,000 characters on
  // the dev VPS. The split runs no RegExp and makes the same few scans at 6 characters as at 50,000.
  // The time ceiling is generous on purpose: a backstop against any quadratic rewrite, not a budget.
  const LENGTH = 50_000;
  it.each([
    ["dots then LF", (n: number) => ".".repeat(n) + "\n", (key: string) => key],
    ["a digit, dots then LS", (n: number) => "1" + ".".repeat(n) + "\u2028", (key: string) => key],
    ["'..' pairs then CR", (n: number) => "a" + "..".repeat(n / 2) + "\r", (key: string) => key],
    [
      "a digit then dots (a range)",
      (n: number) => "1" + ".".repeat(n),
      (key: string) => `1 to ${key.slice(3)}`,
    ],
  ])("reads a 50,000-character key of %s in linear time", (_shape, make, expected) => {
    const short = counted(() => kbdExpansion([make(6)]));
    const key = make(LENGTH);
    let said = "";
    const started = performance.now();
    const long = counted(() => {
      said = kbdExpansion([key]);
    });
    const elapsed = performance.now() - started;
    expect(long.regexRuns).toBe(0);
    expect(long.scans).toBe(short.scans);
    expect(elapsed).toBeLessThan(1_000);
    expect(said).toBe(expected(key));
  });
});

describe("Kbd stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-kbd") === null).toBe(name === "Unbound");
  });
});
