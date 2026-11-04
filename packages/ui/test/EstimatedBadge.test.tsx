// @vitest-environment jsdom
import { act } from "react";
import { createRequire } from "node:module";
import { describe, it, vi } from "vitest";
import { expect, fireEvent, within } from "storybook/test";
import {
  EstimatedBadge,
  EstimatedBadgeOutsideProviderError,
  EstimatedMethodologyProvider,
  estimatedName,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const open = vi.fn();
const badge = (extra: object = {}): React.ReactNode => (
  <EstimatedMethodologyProvider openMethodology={open}>
    <EstimatedBadge detector="funding" variant="inline" size="sm" {...extra} />
  </EstimatedMethodologyProvider>
);

describe("CMP-227 EstimatedBadge", () => {
  it("is a button whose name holds the word estimated and the display name", async () => {
    const host = await mount(badge());
    const button = within(host).getByRole("button", { name: "Estimated, Funding rate" });
    expect(button).toHaveAttribute("aria-haspopup", "dialog");
    expect(button).toHaveTextContent("(estimated)");
  });

  it("adds the confidence as a word", () => {
    expect(estimatedName("funding", "low")).toBe("Estimated, Funding rate, low confidence");
    expect(estimatedName("iceberg", undefined, "Iceberg 63,118")).toBe("Estimated, Iceberg 63,118");
  });

  it("opens the methodology at its detector on click, passing the badge as the focus-return target", async () => {
    const host = await mount(badge());
    const button = within(host).getByRole("button");
    fireEvent.click(button); // no focus(): a mouse click may leave `body` focused
    expect(open).toHaveBeenCalledWith("funding", button);
  });

  it("describes itself with its tooltip's text", async () => {
    const host = await mount(badge({ tooltip: "The rate accruing for the next settlement." }));
    const button = within(host).getByRole("button");
    expect(button).toHaveAccessibleDescription("The rate accruing for the next settlement.");
  });

  it("the marker keeps the word in the DOM, visually hidden", async () => {
    const host = await mount(badge({ variant: "marker" }));
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent("(estimated)");
  });

  it("throws outside the provider", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await expect(
      act(async () => {
        await mount(<EstimatedBadge detector="funding" variant="inline" size="sm" />);
      }),
    ).rejects.toBeInstanceOf(EstimatedBadgeOutsideProviderError);
    error.mockRestore();
  });

  it("has no serious or critical axe violation", async () => {
    const host = await mount(badge());
    const { violations } = await axe.run(host);
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  }, 30_000);
});
