// @vitest-environment jsdom
import { describe, it, vi } from "vitest";
import { expect } from "storybook/test";
import { ConfidenceDots } from "../src/components/index.js";
import { confidenceLabel } from "../src/components/ConfidenceDots.js";
import { mount } from "./theme/mount.js";

const filled = (host: HTMLElement): number =>
  host.querySelectorAll(".cv-confidence__dot[data-filled]").length;

describe("ConfidenceDots (CMP-032)", () => {
  // #265 Gherkin "Estimated confidence is not colour-only".
  it("low confidence is conveyed by one filled dot of three and the text, not by hue alone", async () => {
    const host = await mount(<ConfidenceDots level="low" />);
    expect(host.querySelectorAll(".cv-confidence__dot")).toHaveLength(3);
    expect(filled(host)).toBe(1);
    expect(host.querySelector(".cv-confidence__dots")).toHaveAttribute("aria-hidden", "true");
    expect(host.querySelector(".cv-confidence__label")).toHaveTextContent(/^Low confidence$/);
    // The accessible text is the label alone: the dots add nothing a screen reader hears.
    expect(host.querySelector("[data-cmp='CMP-032']")).toHaveTextContent(/^Low confidence$/);
  });

  it.each([
    ["low", 1, "Low confidence"],
    ["medium", 2, "Medium confidence"],
    ["high", 3, "High confidence"],
  ] as const)("%s: %i filled dots and %s", async (level, count, text) => {
    const host = await mount(<ConfidenceDots level={level} />);
    expect(filled(host)).toBe(count);
    expect(host.querySelector("[data-cmp='CMP-032']")).toHaveAttribute("data-level", level);
    expect(host.querySelector(".cv-confidence__label")).toHaveTextContent(text);
  });

  it("one tone for every level: the level is never a data-tone or a colour attribute", async () => {
    for (const level of ["low", "medium", "high"] as const) {
      const host = await mount(<ConfidenceDots level={level} />);
      const root = host.querySelector("[data-cmp='CMP-032']");
      expect(root).not.toHaveAttribute("data-tone");
      expect(root?.getAttribute("style")).toBeNull();
    }
  });

  it("is static: not focusable, no role, no live region", async () => {
    const host = await mount(<ConfidenceDots level="medium" />);
    expect(host.querySelector("[tabindex], [role], [aria-live]")).toBeNull();
  });

  it("an override that names the level is shown as given", () => {
    expect(confidenceLabel("medium", "72 %, medium confidence")).toBe("72 %, medium confidence");
    expect(confidenceLabel("high", "HIGH")).toBe("HIGH");
  });

  it("an override without the level word gets it appended, so the text always names the level", async () => {
    expect(confidenceLabel("low", "72 %")).toBe("72 %, low confidence");
    // "highly" is not the word "high".
    expect(confidenceLabel("high", "highly likely")).toBe("highly likely, high confidence");
    expect(confidenceLabel("low", "   ")).toBe("Low confidence");
    const host = await mount(<ConfidenceDots level="high" label="Iceberg" />);
    expect(host.querySelector(".cv-confidence__label")).toHaveTextContent(
      /^Iceberg, high confidence$/,
    );
  });

  it("an override naming a different level is replaced by the level's wording, with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(confidenceLabel("low", "High")).toBe("Low confidence");
    expect(confidenceLabel("medium", "72 %, low or high")).toBe("Medium confidence");
    expect(warn).toHaveBeenCalledTimes(2);
    expect(warn.mock.calls[0]?.[0]).toMatch(/names another level/);
    const host = await mount(<ConfidenceDots level="low" label="High confidence" />);
    expect(host.querySelector(".cv-confidence__label")).toHaveTextContent(/^Low confidence$/);
    warn.mockRestore();
  });

  it("hyphenated and longer words name no level: 'high-water', 'lower', 'Highs'", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(confidenceLabel("low", "high-water mark")).toBe("high-water mark, low confidence");
    expect(confidenceLabel("medium", "lower Highs")).toBe("lower Highs, medium confidence");
    expect(confidenceLabel("high", "low-latency, high")).toBe("low-latency, high");
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});
