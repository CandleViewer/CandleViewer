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
