// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState } from "react";
import type { JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import { Slider } from "../src/components/index.js";
import { visibleMarks, type SliderProps } from "../src/components/Slider.js";
import * as stories from "../src/components/Slider.stories.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
type Base = Partial<Omit<SliderProps, "aria-label" | "aria-labelledby">>;

/** Controlled host, like a form: the slider shows what the parent holds. */
function Host({ onChange, ...rest }: Base & { onChange?: (v: number) => void }): JSX.Element {
  const [value, setValue] = useState(rest.value ?? 40);
  return (
    <Slider
      min={0}
      max={100}
      step={5}
      aria-label="Leverage"
      {...rest}
      value={value}
      onChange={(v) => {
        setValue(v);
        onChange?.(v);
      }}
    />
  );
}

const slider = (host: HTMLElement): HTMLElement => within(host).getByRole("slider");
const rail = (host: HTMLElement): HTMLElement =>
  host.querySelector<HTMLElement>(".cv-slider__rail") as HTMLElement;
const now = (host: HTMLElement): string | null => slider(host).getAttribute("aria-valuenow");

const capture = vi.fn();
/** jsdom has no layout and no pointer capture: a 200 px rail at x = 100, and a spy for the capture. */
function stubLayout(): void {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 100,
    width: 200,
    right: 300,
    top: 0,
    bottom: 24,
    height: 24,
    x: 100,
    y: 0,
    toJSON: () => ({}),
  });
  Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
    configurable: true,
    value: capture,
  });
}
/** jsdom has no PointerEvent: a MouseEvent of the pointer type carries button and clientX, plus the id. */
function pointer(
  type: string,
  target: HTMLElement,
  init: { pointerId?: number; button?: number; clientX?: number } = {},
): boolean {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    button: init.button ?? 0,
    clientX: init.clientX ?? 0,
  });
  Object.defineProperty(event, "pointerId", { value: init.pointerId ?? 1 });
  let result = true;
  act(() => {
    result = target.dispatchEvent(event);
  });
  return result;
}
/** A cancelable keydown inside `act`, so a controlled parent re-renders before the assertion. */
const key = (target: HTMLElement, init: KeyboardEventInit): boolean => {
  let result = true;
  act(() => {
    result = target.dispatchEvent(
      new KeyboardEvent("keydown", { ...init, bubbles: true, cancelable: true }),
    );
  });
  return result;
};

afterEach(() => {
  vi.restoreAllMocks();
  capture.mockClear();
});

describe("Slider (CMP-010) semantics", () => {
  it("is a role=slider thumb with value, range, text and orientation", async () => {
    const host = await mount(<Host suffix="%" />);
    const s = slider(host);
    expect(s).toHaveAttribute("aria-valuenow", "40");
    expect(s).toHaveAttribute("aria-valuemin", "0");
    expect(s).toHaveAttribute("aria-valuemax", "100");
    expect(s).toHaveAttribute("aria-valuetext", "40 %");
    expect(s).toHaveAttribute("aria-orientation", "horizontal");
    expect(s).toHaveAccessibleName("Leverage");
    expect(s).toHaveAttribute("tabindex", "0");
    expect(s).not.toHaveAttribute("aria-disabled");
    expect(host.querySelector<HTMLElement>(".cv-slider")?.dataset["cmp"]).toBe("CMP-010");
  });

  it("is named by aria-labelledby, and the name is required by the type", async () => {
    const host = await mount(
      <>
        <span id="lbl">Risk</span>
        <Slider value={1} min={0} max={2} step={1} onChange={fn()} aria-labelledby="lbl" />
      </>,
    );
    expect(slider(host)).toHaveAccessibleName("Risk");
    // @ts-expect-error a slider with no accessible name must not compile
    const nameless = <Slider value={1} min={0} max={2} step={1} onChange={fn()} />;
    expect(nameless).toBeTruthy();
  });

  it("derives decimals from the step and min, or takes an explicit precision", async () => {
    const a = await mount(<Host value={0.3} min={0} max={1} step={0.1} />);
    expect(slider(a)).toHaveAttribute("aria-valuetext", "0.3");
    const b = await mount(<Host value={2} min={0} max={10} step={1} precision={2} />);
    expect(within(b).getByRole("slider")).toHaveAttribute("aria-valuetext", "2.00");
    const c = await mount(<Host value={0} min={0} max={1e-7} step={1e-7} />);
    expect(within(c).getByRole("slider")).toHaveAttribute("aria-valuetext", "0.0000000");
  });

  it("clamps an out-of-range value for the thumb, the attributes and the fill", async () => {
    const host = await mount(<Host value={150} />);
    expect(now(host)).toBe("100");
    const lo = await mount(<Host value={-3} />);
    expect(within(lo).getByRole("slider")).toHaveAttribute("aria-valuenow", "0");
  });

  it("a degenerate range puts the thumb at the start", async () => {
    const host = await mount(<Host value={5} min={5} max={5} step={1} marks={[5]} />);
    expect(slider(host).style.getPropertyValue("--cv-slider-pos")).toBe("0");
  });

  it("merges a caller's aria-describedby with the reason", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <Host aria-describedby="help" disabledReason={REASON} />
      </>,
    );
    expect(slider(host)).toHaveAccessibleDescription(`Help ${REASON}`);
  });
});

describe("Slider keyboard", () => {
  it.each([
    ["{ArrowRight}", "45"],
    ["{ArrowUp}", "45"],
    ["{ArrowLeft}", "35"],
    ["{ArrowDown}", "35"],
    ["{PageUp}", "90"],
    ["{PageDown}", "0"],
    ["{Home}", "0"],
    ["{End}", "100"],
  ])("%s -> %s", async (keys, expected) => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard(keys);
    expect(now(host)).toBe(expected);
    expect(slider(host)).toHaveAttribute("aria-valuetext", expected);
    expect(onChange).toHaveBeenCalledWith(Number(expected));
  });

  it("steps exactly on decimals and clamps at the bounds without a call", async () => {
    const onChange = fn();
    const host = await mount(<Host value={0.1} min={0} max={0.3} step={0.1} onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(now(host)).toBe("0.3");
    expect(onChange.mock.calls).toEqual([[0.2], [0.3]]);
    await userEvent.keyboard("{ArrowRight}{End}");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("an out-of-range value is pulled in by the first key", async () => {
    const onChange = fn();
    await mount(<Host value={150} onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    expect(onChange).toHaveBeenCalledWith(100);
  });

  it("handled keys are prevented; other keys and modifier chords are left alone", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    const s = slider(host);
    expect(key(s, { key: "ArrowRight" })).toBe(false);
    expect(key(s, { key: "a" })).toBe(true);
    for (const chord of ["altKey", "ctrlKey", "metaKey"]) {
      expect(key(s, { key: "ArrowRight", [chord]: true })).toBe(true);
    }
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(now(host)).toBe("45");
  });

  it("a parent that refuses the change keeps the attributes and the visuals in step", async () => {
    const onChange = fn();
    const host = await mount(
      <Slider value={40} min={0} max={100} step={5} aria-label="L" onChange={onChange} />,
    );
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith(45);
    expect(now(host)).toBe("40");
    expect(slider(host).style.getPropertyValue("--cv-slider-pos")).toBe("0.4");
  });
});

describe("Slider pointer", () => {
  it("pointer-down on the rail jumps, focuses the thumb and captures the pointer", async () => {
    stubLayout();
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    pointer("pointerdown", rail(host), { pointerId: 7, button: 0, clientX: 220 });
    expect(now(host)).toBe("60");
    expect(slider(host)).toHaveFocus();
    expect(capture).toHaveBeenCalledWith(7);
  });

  it("drags, snaps to the step, clamps past either end and stops on release", async () => {
    stubLayout();
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    const r = rail(host);
    pointer("pointerdown", r, { pointerId: 1, button: 0, clientX: 100 });
    expect(now(host)).toBe("0");
    pointer("pointermove", r, { pointerId: 1, clientX: 163 });
    expect(now(host)).toBe("30");
    pointer("pointermove", r, { pointerId: 1, clientX: 900 });
    expect(now(host)).toBe("100");
    pointer("pointermove", r, { pointerId: 1, clientX: -50 });
    expect(now(host)).toBe("0");
    const calls = onChange.mock.calls.length;
    pointer("pointermove", r, { pointerId: 1, clientX: -60 });
    expect(onChange).toHaveBeenCalledTimes(calls);
    pointer("pointerup", r, { pointerId: 1 });
    pointer("pointermove", r, { pointerId: 1, clientX: 250 });
    expect(now(host)).toBe("0");
  });

  it.each(["pointercancel", "lostpointercapture"] as const)("%s ends the drag", async (kind) => {
    stubLayout();
    const host = await mount(<Host />);
    pointer("pointerdown", rail(host), { pointerId: 1, button: 0, clientX: 150 });
    pointer(kind, rail(host), { pointerId: 1 });
    pointer("pointermove", rail(host), { pointerId: 1, clientX: 250 });
    expect(now(host)).toBe("25");
  });

  it("reads the rect at pointer-down only, never while rendering or moving", async () => {
    stubLayout();
    const rect = vi.mocked(HTMLElement.prototype.getBoundingClientRect);
    const host = await mount(<Host />);
    expect(rect).not.toHaveBeenCalled();
    pointer("pointerdown", rail(host), { pointerId: 1, button: 0, clientX: 150 });
    pointer("pointermove", rail(host), { pointerId: 1, clientX: 200 });
    pointer("pointermove", rail(host), { pointerId: 1, clientX: 250 });
    expect(rect).toHaveBeenCalledTimes(1);
  });

  it("a zero-width rail does not divide by zero", async () => {
    stubLayout();
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockReturnValue(
      new DOMRect(100, 0, 0, 24),
    );
    const host = await mount(<Host />);
    pointer("pointerdown", rail(host), { pointerId: 1, button: 0, clientX: 150 });
    expect(now(host)).toBe("0");
  });

  it("ignores a secondary button, and a move with no drag changes nothing", async () => {
    stubLayout();
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    pointer("pointerdown", rail(host), { pointerId: 1, button: 2, clientX: 250 });
    pointer("pointermove", rail(host), { pointerId: 1, clientX: 250 });
    expect(onChange).not.toHaveBeenCalled();
    expect(capture).not.toHaveBeenCalled();
  });
});

describe.each([
  ["disabled with a reason", { disabledReason: REASON }, true],
  ["plain disabled", { disabled: true }, false],
] as const)("Slider %s", (_label, props, gated) => {
  it("changes nothing on any key or pointer action, and keeps the attributes true", async () => {
    stubLayout();
    const onChange = fn();
    const host = await mount(<Host {...props} onChange={onChange} marks={[0, 100]} />);
    const s = slider(host);
    expect(s).toHaveAttribute("aria-disabled", "true");
    for (const k of ["ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "PageUp", "End", "Home"]) {
      expect(key(s, { key: k })).toBe(false);
    }
    expect(pointer("pointerdown", rail(host), { pointerId: 1, button: 0, clientX: 250 })).toBe(
      false,
    );
    pointer("pointermove", rail(host), { pointerId: 1, clientX: 280 });
    expect(onChange).not.toHaveBeenCalled();
    expect(capture).not.toHaveBeenCalled();
    expect(now(host)).toBe("40");
    expect(s).toHaveAttribute("aria-valuetext", "40");
    expect(key(s, { key: "End", ctrlKey: true })).toBe(true);
  });

  it(
    gated ? "stays focusable, with the reason and a trailing lock" : "leaves the Tab order",
    async () => {
      const host = await mount(<Host {...props} />);
      await userEvent.tab();
      if (gated) {
        expect(slider(host)).toHaveFocus();
        expect(slider(host)).toHaveAccessibleDescription(REASON);
        expect(slider(host)).toHaveAttribute("tabindex", "0");
        const body = host.querySelector(".cv-slider__body") as HTMLElement;
        expect(body.nextElementSibling).toHaveClass("cv-slider__glyph");
        expect(host.querySelector(".cv-slider__glyph svg")).toHaveAttribute("aria-hidden", "true");
      } else {
        expect(slider(host)).not.toHaveFocus();
        expect(slider(host)).not.toHaveAttribute("tabindex");
        expect(host.querySelector(".cv-slider__glyph")).toBeNull();
        expect(host.querySelector(".cv-visually-hidden")).toBeNull();
      }
    },
  );

  it("clicking the rail focuses a gated thumb only", async () => {
    const host = await mount(<Host {...props} />);
    pointer("pointerdown", rail(host), { pointerId: 1, button: 0, clientX: 250 });
    if (gated) expect(slider(host)).toHaveFocus();
    else expect(slider(host)).not.toHaveFocus();
  });
});

describe("Slider marks and density", () => {
  const count = (host: HTMLElement): number => host.querySelectorAll(".cv-slider__mark").length;

  it("renders numeric labels, aria-hidden, none without marks", async () => {
    const host = await mount(<Host marks={[0, 50, 100]} />);
    expect([...host.querySelectorAll(".cv-slider__mark")].map((m) => m.textContent)).toEqual([
      "0",
      "50",
      "100",
    ]);
    expect(host.querySelector(".cv-slider__marks")).toHaveAttribute("aria-hidden", "true");
    expect(within(host).queryByText("50")).not.toBeNull();
    expect(count(await mount(<Host />))).toBe(0);
    expect(count(await mount(<Host marks={[]} />))).toBe(0);
  });

  it("drops marks outside the range and duplicates", () => {
    expect(visibleMarks([100, 50, 50, -5, 200, 0], 0, 100, 0)).toEqual([0, 50, 100]);
    expect(visibleMarks([500], 0, 100, 0)).toEqual([]);
    expect(visibleMarks([50], 0, 100, 0)).toEqual([50]);
  });

  it("collapses colliding marks to min and max, by count", () => {
    const dense = Array.from({ length: 11 }, (_, i) => i * 10);
    expect(visibleMarks(dense, 0, 100, 0)).toEqual([0, 100]);
    expect(visibleMarks([0, 25, 50, 75, 100], 0, 100, 0)).toHaveLength(5);
    // Longer labels need more room: 4-digit labels at 12.5 % gaps collide.
    expect(visibleMarks([0, 1250, 2500], 0, 10000, 0)).toEqual([0]);
    expect(visibleMarks([0, 5000, 10000], 0, 10000, 0)).toHaveLength(3);
    // The same 12.5 % gaps fit 1-digit labels.
    expect(visibleMarks([0, 1, 2, 3, 4, 5, 6, 7, 8], 0, 8, 0)).toHaveLength(9);
  });

  it("collapses crowded marks in the rendered tree", async () => {
    const dense = Array.from({ length: 11 }, (_, i) => i * 10);
    expect(count(await mount(<Host marks={dense} />))).toBe(2);
  });

  it("emits the density attribute", async () => {
    const host = await mount(<Host density="compact" />);
    expect(host.querySelector<HTMLElement>(".cv-slider")?.dataset["density"]).toBe("compact");
  });
});

describe("Slider stories", () => {
  const composed = composeStories(stories);
  it.each(Object.entries(composed))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector("[role=slider]")).not.toBeNull();
  });
});
