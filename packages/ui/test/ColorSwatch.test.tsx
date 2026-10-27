// @vitest-environment jsdom
import { useState } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  ColorSwatch,
  ColorSwatchPicker,
  type ColorSwatchOption,
  type ColorSwatchPickerBaseProps,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
const SWATCHES: ColorSwatchOption[] = [
  { value: "cyan", label: "Cyan", color: "var(--color-drawing-default)" },
  { value: "amber", label: "Amber", color: "var(--color-drawing-selected)" },
  { value: "violet", label: "Violet", color: "var(--color-node-logic)" },
];
const swatch = (host: HTMLElement, name: string): HTMLElement =>
  within(host).getByRole("radio", { name });
const checkedOf = (host: HTMLElement): string[] =>
  within(host)
    .getAllByRole("radio")
    .filter((r) => r.getAttribute("aria-checked") === "true")
    .map((r) => r.getAttribute("aria-label") ?? "");

/** Keeps the value like a real host does. */
function Host(props: Partial<ColorSwatchPickerBaseProps>): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <ColorSwatchPicker
      aria-label="Line colour"
      swatches={SWATCHES}
      {...props}
      value={value}
      onChange={(v) => {
        setValue(v);
        props.onChange?.(v);
      }}
    />
  );
}

describe("ColorSwatchPicker (CMP-031)", () => {
  it("is a named radiogroup of radios named by colour, one tab stop on the selected swatch", async () => {
    const host = await mount(<Host value="amber" />);
    const group = within(host).getByRole("radiogroup", { name: "Line colour" });
    expect(group.dataset["cmp"]).toBe("CMP-031");
    expect(
      within(host)
        .getAllByRole("radio")
        .map((r) => r.tabIndex),
    ).toEqual([-1, 0, -1]);
    expect(checkedOf(host)).toEqual(["Amber"]);
    expect(swatch(host, "Amber").style.getPropertyValue("--cv-swatch-color")).toBe(
      "var(--color-drawing-selected)",
    );
  });

  it("shows the check glyph only on the selected swatch, hidden from assistive technology", async () => {
    const host = await mount(<Host value="cyan" />);
    const check = swatch(host, "Cyan").querySelector(".cv-swatch__check");
    expect(check).not.toBeNull();
    expect(check?.getAttribute("aria-hidden")).toBe("true");
    expect(swatch(host, "Amber").querySelector(".cv-swatch__check")).toBeNull();
  });

  it("first enabled swatch holds the tab stop when none is selected", async () => {
    const host = await mount(
      <Host
        swatches={[{ ...(SWATCHES[0] as ColorSwatchOption), disabled: true }, ...SWATCHES.slice(1)]}
      />,
    );
    await userEvent.tab();
    expect(swatch(host, "Amber")).toHaveFocus();
  });

  it("arrows move and select, wrapping both ways; Home / End jump", async () => {
    const onChange = fn();
    const host = await mount(<Host value="cyan" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(swatch(host, "Amber")).toHaveFocus();
    expect(checkedOf(host)).toEqual(["Amber"]);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(swatch(host, "Cyan")).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(checkedOf(host)).toEqual(["Violet"]);
    await userEvent.keyboard("{Home}");
    expect(checkedOf(host)).toEqual(["Cyan"]);
    await userEvent.keyboard("{End}{ArrowUp}");
    expect(checkedOf(host)).toEqual(["Amber"]);
    expect(onChange).toHaveBeenLastCalledWith("amber");
  });

  it("Space selects the focused swatch; Tab leaves the picker", async () => {
    const onChange = fn();
    const host = await mount(
      <>
        <Host onChange={onChange} />
        <button type="button">after</button>
      </>,
    );
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenCalledWith("cyan");
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "after" })).toHaveFocus();
  });

  it("a click selects and focuses the swatch", async () => {
    const onChange = fn();
    const host = await mount(<Host value="cyan" onChange={onChange} />);
    await userEvent.click(swatch(host, "Violet"));
    expect(swatch(host, "Violet")).toHaveFocus();
    expect(onChange).toHaveBeenCalledWith("violet");
  });

  it("T2 swatch: stays focusable in the roving order, its reason is the description, never selected", async () => {
    const onChange = fn();
    const locked = [SWATCHES[0], { ...SWATCHES[1], disabledReason: ` ${REASON} ` }, SWATCHES[2]];
    const host = await mount(
      <Host swatches={locked as ColorSwatchOption[]} value="cyan" onChange={onChange} />,
    );
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    const amber = swatch(host, "Amber");
    expect(amber).toHaveFocus();
    expect(amber).toHaveAttribute("aria-disabled", "true");
    expect(amber).not.toHaveAttribute("disabled");
    expect(amber).toHaveAccessibleDescription(REASON);
    expect(amber.dataset["gated"]).toBe("");
    expect(amber.querySelector(".cv-swatch__badge")?.getAttribute("aria-hidden")).toBe("true");
    await userEvent.keyboard(" ");
    await userEvent.click(amber);
    expect(checkedOf(host)).toEqual(["Cyan"]);
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.keyboard("{ArrowRight}");
    expect(checkedOf(host)).toEqual(["Violet"]);
  });

  it("a gated selected swatch shows both the check and the lock badge", async () => {
    const locked = [{ ...SWATCHES[0], disabledReason: REASON }, SWATCHES[1]];
    const host = await mount(<Host swatches={locked as ColorSwatchOption[]} value="cyan" />);
    const cyan = swatch(host, "Cyan");
    expect(cyan.querySelector(".cv-swatch__check")).not.toBeNull();
    expect(cyan.querySelector(".cv-swatch__badge")).not.toBeNull();
    expect(cyan).toHaveAttribute("aria-checked", "true");
  });

  it("plain-disabled swatch: skipped by the arrows, out of the Tab order, no badge", async () => {
    const list = [SWATCHES[0], { ...SWATCHES[1], disabled: true }, SWATCHES[2]];
    const host = await mount(<Host swatches={list as ColorSwatchOption[]} value="cyan" />);
    const amber = swatch(host, "Amber");
    expect(amber).not.toHaveAttribute("tabindex");
    expect(amber).toHaveAttribute("aria-disabled", "true");
    expect(amber.dataset["disabled"]).toBe("");
    expect(amber.querySelector(".cv-swatch__badge")).toBeNull();
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(checkedOf(host)).toEqual(["Violet"]);
    fireEvent.click(amber);
    expect(checkedOf(host)).toEqual(["Violet"]);
  });

  it("locked picker: aria-disabled, every swatch carries the reason and a lock, keys change nothing", async () => {
    const onChange = fn();
    const host = await mount(<Host value="amber" disabledReason={REASON} onChange={onChange} />);
    const group = within(host).getByRole("radiogroup");
    expect(group).toHaveAttribute("aria-disabled", "true");
    expect(group).toHaveAccessibleDescription(REASON);
    for (const r of within(host).getAllByRole("radio")) {
      expect(r).toHaveAccessibleDescription(REASON);
      expect(r.querySelector(".cv-swatch__badge")).not.toBeNull();
    }
    await userEvent.tab();
    expect(swatch(host, "Amber")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}{Home} ");
    await userEvent.click(swatch(host, "Violet"));
    expect(onChange).not.toHaveBeenCalled();
    expect(checkedOf(host)).toEqual(["Amber"]);
  });

  it("plain-disabled picker: nothing is focusable and no reason is rendered", async () => {
    const host = await mount(<Host value="cyan" disabled />);
    for (const r of within(host).getAllByRole("radio")) {
      expect(r).not.toHaveAttribute("tabindex");
      expect(r).toHaveAttribute("aria-disabled", "true");
    }
    expect(within(host).getByRole("radiogroup")).not.toHaveAttribute("aria-describedby");
  });

  it("glyph tone defaults to inverse; on-action is opt-in per swatch", async () => {
    const list = [SWATCHES[0], { ...SWATCHES[1], glyphTone: "on-action" }];
    const host = await mount(<Host swatches={list as ColorSwatchOption[]} />);
    expect(swatch(host, "Cyan").dataset["glyph"]).toBe("inverse");
    expect(swatch(host, "Amber").dataset["glyph"]).toBe("on-action");
  });

  it("warns in development when two swatches share a value", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await mount(
      <ColorSwatchPicker
        aria-label="Line colour"
        swatches={[...SWATCHES, SWATCHES[0] as ColorSwatchOption]}
      />,
    );
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0]?.[0]).toMatch(/duplicate swatch value "cyan"/);
    warn.mockClear();
    await mount(<ColorSwatchPicker aria-label="Fill colour" swatches={SWATCHES} />);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("is named by aria-labelledby and passes density through", async () => {
    const host = await mount(
      <>
        <span id="lbl">Fill colour</span>
        <ColorSwatchPicker aria-labelledby="lbl" swatches={SWATCHES} density="comfortable" />
      </>,
    );
    const group = within(host).getByRole("radiogroup", { name: "Fill colour" });
    expect(group.dataset["density"]).toBe("comfortable");
  });
});

describe("ColorSwatch, static (CMP-031)", () => {
  it("is a named img, not focusable, with the colour as its fill", async () => {
    const host = await mount(<ColorSwatch color="var(--color-drawing-default)" label="Cyan" />);
    const img = within(host).getByRole("img", { name: "Cyan" });
    expect(img).not.toHaveAttribute("tabindex");
    expect(img).not.toHaveAttribute("data-glyph");
    expect(img.style.getPropertyValue("--cv-swatch-color")).toBe("var(--color-drawing-default)");
  });

  it("decorative: aria-hidden with no role or name", async () => {
    const host = await mount(
      <ColorSwatch
        color="var(--color-drawing-default)"
        label="Cyan"
        decorative
        density="compact"
      />,
    );
    const el = host.querySelector(".cv-swatch");
    expect(el?.getAttribute("aria-hidden")).toBe("true");
    expect(el).not.toHaveAttribute("role");
    expect(el).not.toHaveAttribute("aria-label");
    expect(el?.getAttribute("data-density")).toBe("compact");
  });
});
