// @vitest-environment jsdom
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { IndicatorChips, pickIndicatorSuffix } from "../src/components/index.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const page = within(document.body);

describe("IndicatorChips (CMP-224)", () => {
  it("picks one suffix in the order error → stale → computing → hidden", () => {
    expect(pickIndicatorSuffix({ hidden: 1, computing: 1, stale: 2, error: 1 })).toEqual({
      kind: "error",
      n: 1,
    });
    expect(pickIndicatorSuffix({ hidden: 1, computing: 1, stale: 2 })).toEqual({
      kind: "stale",
      n: 2,
    });
    expect(pickIndicatorSuffix({ hidden: 1, computing: 3 })).toEqual({ kind: "computing", n: 3 });
    expect(pickIndicatorSuffix({ hidden: 1, error: 0 })).toEqual({ kind: "hidden", n: 1 });
    expect(pickIndicatorSuffix({})).toBeUndefined();
  });

  it("reads the count and the suffix as words, with the catalogue's name", async () => {
    await mount(<IndicatorChips count={4} suffix={{ kind: "hidden", n: 1 }} onOpen={fn()} />);
    const chip = page.getByRole("button", {
      name: "Indicators: 4 on this chart, 1 hidden — open the object manager",
    });
    expect(chip).toHaveTextContent("Ind 4·1 hidden");
  });

  it("reads Ind 0 with no suffix, and pluralises errors", async () => {
    await mount(
      <>
        <IndicatorChips count={0} onOpen={fn()} />
        <IndicatorChips count={6} suffix={{ kind: "error", n: 2 }} onOpen={fn()} />
      </>,
    );
    expect(page.getByRole("button", { name: /^Indicators: 0 on this chart — / })).toHaveTextContent(
      "Ind 0",
    );
    expect(page.getByRole("button", { name: /6 on this chart, 2 errors/ })).toBeTruthy();
  });

  it("names the stale and computing suffixes and the singular error, as a plain button", async () => {
    await mount(
      <>
        <IndicatorChips count={3} suffix={{ kind: "stale", n: 2 }} onOpen={fn()} />
        <IndicatorChips count={2} suffix={{ kind: "computing", n: 1 }} onOpen={fn()} />
        <IndicatorChips count={5} suffix={{ kind: "error", n: 1 }} onOpen={fn()} />
      </>,
    );
    expect(page.getByRole("button", { name: /3 on this chart, 2 stale —/ })).toHaveAttribute(
      "type",
      "button",
    );
    expect(page.getByRole("button", { name: /2 on this chart, 1 computing —/ })).toBeTruthy();
    expect(page.getByRole("button", { name: /5 on this chart, 1 error —/ })).toBeTruthy();
  });

  it("is a disclosure opener: aria-expanded tracks the drawer, never aria-pressed", async () => {
    await mount(
      <>
        <IndicatorChips count={1} open onOpen={fn()} />
        <IndicatorChips count={2} open={false} onOpen={fn()} />
        <IndicatorChips count={3} onOpen={fn()} />
      </>,
    );
    const chip = (n: number): HTMLElement =>
      page.getByRole("button", { name: new RegExp(`^Indicators: ${n} `) });
    expect(chip(1)).toHaveAttribute("aria-expanded", "true");
    expect(chip(2)).toHaveAttribute("aria-expanded", "false");
    expect(chip(3)).not.toHaveAttribute("aria-expanded");
    for (const n of [1, 2, 3]) expect(chip(n)).not.toHaveAttribute("aria-pressed");
  });

  it("controls the drawer the host names, and names none otherwise", async () => {
    await mount(
      <>
        <IndicatorChips count={1} open drawerId="scr-036" onOpen={fn()} />
        <IndicatorChips count={2} open={false} onOpen={fn()} />
      </>,
    );
    expect(page.getByRole("button", { name: /^Indicators: 1 / })).toHaveAttribute(
      "aria-controls",
      "scr-036",
    );
    expect(page.getByRole("button", { name: /^Indicators: 2 / })).not.toHaveAttribute(
      "aria-controls",
    );
  });

  it("opens SCR-036 on Enter and on Space", async () => {
    const onOpen = fn();
    await mount(<IndicatorChips count={4} onOpen={onOpen} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("has no serious or critical axe violation", async () => {
    const host = await mount(
      <IndicatorChips count={4} suffix={{ kind: "error", n: 1 }} onOpen={fn()} />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});
