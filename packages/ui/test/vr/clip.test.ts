import { describe, expect, it, vi } from "vitest";
import {
  clipFor,
  isBackdrop,
  opaque,
  reachOf,
  shadowReach,
  stableClip,
  type Clip,
  type ElementPaint,
  type PaintDump,
} from "../../vr/clip.js";

const NONE: readonly [string, string, string] = ["0px", "none", "rgb(0, 0, 0)"];
const CLEAR = "rgba(0, 0, 0, 0)";

/** An element box with Chromium's computed values for "paints nothing", overridden per case. */
const element = (box: ElementPaint["box"], styles: Partial<ElementPaint> = {}): ElementPaint => ({
  box,
  tag: "div",
  background: CLEAR,
  backgroundImage: "none",
  boxShadow: "none",
  outline: ["none", "0px", "0px"],
  borders: [NONE, NONE, NONE, NONE],
  pseudo: false,
  position: "static",
  ownText: false,
  ...styles,
});

const page = (elements: ElementPaint[], text: PaintDump["text"] = []): PaintDump => ({
  page: [1920, 1080],
  viewport: [1920, 1080],
  elements,
  text,
});

describe("what paints", () => {
  it("reads Chromium's transparent colours as no paint", () => {
    expect(
      [CLEAR, "transparent", "rgba(10, 20, 30, 0)", "color(srgb 1 0 0 / 0)", ""].map(opaque),
    ).toEqual([false, false, false, false, false]);
    // A blue channel of 0 is no alpha: black and red paint.
    const painted = [
      "rgb(0, 0, 0)",
      "rgb(255, 0, 0)",
      "rgba(0, 0, 0, 0.5)",
      "color(srgb 1 0 0 / 0.04)",
    ];
    expect(painted.map(opaque)).toEqual([true, true, true, true]);
  });

  it("measures a shadow list by its farthest outer shadow", () => {
    expect(shadowReach("none")).toBe(0);
    expect(shadowReach("rgba(0, 0, 0, 0.8) 0px 16px 48px 0px")).toBe(64);
    expect(
      shadowReach("rgba(0, 0, 0, 0.4) 0px 1px 2px 0px, rgba(0, 0, 0, 0.6) -6px 4px 12px 2px"),
    ).toBe(20);
    expect(shadowReach("rgb(1, 2, 3) 0px 0px 0px 3px inset")).toBe(0);
  });

  it("counts a fill, an image, a border, a shadow, an outline, a pseudo-element or a graphic", () => {
    const box = [0, 0, 10, 10] as const;
    const painted: Partial<ElementPaint>[] = [
      { background: "rgb(1, 2, 3)" },
      { backgroundImage: "linear-gradient(red, blue)" },
      { borders: [NONE, ["1px", "solid", "rgb(1, 2, 3)"], NONE, NONE] },
      { boxShadow: "rgba(0, 0, 0, 0.4) 0px 1px 2px 0px" },
      { outline: ["solid", "2px", "2px"] },
      { pseudo: true },
      { tag: "svg" },
      { tag: "input" },
    ];
    expect(painted.map((styles) => reachOf(element(box, styles)))).toEqual([
      0, 0, 0, 3, 4, 0, 0, 0,
    ]);
  });

  it("does not count a wrapper that only lays out its children", () => {
    const hairline = ["1px", "solid", CLEAR] as const;
    const hiddenBorder = ["2px", "hidden", "rgb(1, 2, 3)"] as const;
    expect(reachOf(element([0, 0, 1920, 40]))).toBeUndefined();
    expect(
      reachOf(element([0, 0, 1920, 40], { borders: [hairline, hiddenBorder, NONE, NONE] })),
    ).toBeUndefined();
  });
});

describe("the capture area", () => {
  it("clips a small component to what it paints plus a 4 px edge, not to the page", () => {
    const wrapper = element([16, 16, 1904, 48]);
    const button = element([16, 16, 116.5, 48], { background: "rgb(1, 2, 3)" });
    expect(clipFor(page([wrapper, button], [[30, 24, 90.2, 40]]))).toEqual({
      x: 12,
      y: 12,
      width: 109,
      height: 40,
    });
  });

  it("grows each box by its own shadow or focus ring, and unions text, portals and boxes", () => {
    const dialog = element([600, 300, 1100, 600], {
      boxShadow: "rgba(0, 0, 0, 0.8) 0px 16px 48px 0px",
    });
    const focused = element([20, 20, 120, 52], { outline: ["solid", "2px", "2px"] });
    // The dialog's shadow reaches 64 px (16 offset + 48 blur), the ring 4 px (2 wide, 2 out).
    expect(clipFor(page([dialog, focused]))).toEqual({
      x: 12,
      y: 12,
      width: 1168 - 12,
      height: 668 - 12,
    });
    expect(clipFor(page([dialog, focused], [[1500, 900, 1600, 920]]))).toEqual({
      x: 12,
      y: 12,
      width: 1604 - 12,
      height: 924 - 12,
    });
  });

  it("changes size when a component's padding does, which fails whatever the tolerance", () => {
    const at = (right: number) =>
      clipFor(page([element([16, 16, right, 48], { background: "rgb(1, 2, 3)" })]));
    expect(at(118).width - at(116).width).toBe(2);
  });

  it("puts an edge within 0.01 px of a whole pixel on it, so float noise never moves a clip by one", () => {
    const at = (right: number, bottom: number) =>
      clipFor(page([element([16, 16, right, bottom], { background: "rgb(1, 2, 3)" })]));
    expect(at(116.004, 48.004)).toEqual({ x: 12, y: 12, width: 108, height: 40 });
    expect(at(115.996, 47.996)).toEqual(at(116.004, 48.004));
    expect(at(116.5, 48)).toEqual({ x: 12, y: 12, width: 109, height: 40 }); // a real half pixel counts
    const left = (x: number) =>
      clipFor(page([element([x, 16, 116, 48], { background: "rgb(1, 2, 3)" })]));
    expect(left(15.996)).toEqual(left(16.004));
  });

  it("stays inside the page and falls back to the whole page when nothing paints", () => {
    const overlay = element([-10, -10, 2000, 1200], { background: "rgba(0, 0, 0, 0.5)" });
    expect(clipFor(page([overlay]))).toEqual({ x: 0, y: 0, width: 1920, height: 1080 });
    expect(
      clipFor(page([element([16, 16, 1904, 48]), element([5, 5, 5, 40], { tag: "svg" })])),
    ).toEqual({
      x: 0,
      y: 0,
      width: 1920,
      height: 1080,
    });
  });
});

describe("an overlay's backdrop", () => {
  const VIEWPORT = [1920, 1080] as const;
  /** A modal's scrim: out of flow over the whole viewport, a flat fill (`palette.black` at `opacity.scrim`). */
  const scrim = (styles: Partial<ElementPaint> = {}): ElementPaint =>
    element([0, 0, 1920, 1080], { position: "absolute", background: "rgb(0, 0, 0)", ...styles });
  const dialog = element([710, 390, 1210, 690], {
    background: "rgb(30, 30, 30)",
    boxShadow: "rgba(0, 0, 0, 0.8) 0px 16px 48px 0px",
  });

  it("is a flat fill over the whole viewport, out of flow, with no text, edge or shadow of its own", () => {
    expect(isBackdrop(scrim(), VIEWPORT)).toBe(true);
    expect(isBackdrop(scrim({ position: "fixed" }), VIEWPORT)).toBe(true);
    expect(
      isBackdrop(
        element([-8, -8, 1940, 1100], { position: "fixed", background: "rgb(0, 0, 0)" }),
        VIEWPORT,
      ),
    ).toBe(true);
  });

  it("is not a box that draws more, sits in the flow or leaves part of the viewport uncovered", () => {
    const kept: ElementPaint[] = [
      scrim({ ownText: true }),
      scrim({ boxShadow: "rgba(0, 0, 0, 0.4) 0px 1px 2px 0px" }),
      scrim({ borders: [NONE, ["1px", "solid", "rgb(1, 2, 3)"], NONE, NONE] }),
      scrim({ outline: ["solid", "2px", "0px"] }),
      scrim({ backgroundImage: "linear-gradient(red, blue)" }),
      scrim({ pseudo: true }),
      scrim({ tag: "canvas" }),
      scrim({ position: "static" }),
      scrim({ box: [0, 48, 1920, 1080] }), // a drawer's scrim below a TopBar left unscrimmed
      scrim({ background: CLEAR }),
    ];
    expect(kept.map((each) => isBackdrop(each, VIEWPORT))).toEqual(kept.map(() => false));
  });

  it("is left out of the capture, so a dialog is captured as itself, its shadow and the 4 px edge", () => {
    // The dialog's shadow reaches 64 px: the scrim it falls on is in the capture, so a scrim change still shows.
    expect(clipFor(page([scrim(), dialog]))).toEqual({ x: 642, y: 322, width: 636, height: 436 });
    expect(clipFor(page([scrim({ position: "static" }), dialog]))).toEqual({
      x: 0,
      y: 0,
      width: 1920,
      height: 1080,
    });
  });
});

describe("a capture area that holds still", () => {
  const box = (width: number): Clip => ({ x: 0, y: 0, width, height: 10 });
  /** Measures that return the given boxes in turn. */
  const measures = (...boxes: Clip[]) => {
    let next = 0;
    return async (): Promise<Clip> => boxes[Math.min(next++, boxes.length - 1)] ?? box(0);
  };

  it("is taken once two measures, two frames apart, agree", async () => {
    const frames = vi.fn(async () => undefined);
    await expect(stableClip(measures(box(10), box(12), box(12)), frames, 3)).resolves.toEqual({
      clip: box(12),
      moving: [],
    });
    expect(frames).toHaveBeenCalledTimes(2);
  });

  it("names every box of an area still moving after the last measure", async () => {
    const moving = measures(box(10), box(11), box(12));
    await expect(stableClip(moving, async () => undefined, 3)).resolves.toEqual({
      clip: box(12),
      moving: [box(10), box(11), box(12)],
    });
  });
});
