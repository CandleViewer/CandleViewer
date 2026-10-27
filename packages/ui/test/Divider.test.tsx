// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Divider, DividerLabel } from "../src/components/index.js";
import * as stories from "../src/components/Divider.stories.js";
import { mount } from "./theme/mount.js";

describe("Divider (CMP-018)", () => {
  it("is a horizontal separator by default, never focusable", async () => {
    const host = await mount(<Divider />);
    const rule = within(host).getByRole("separator");
    expect(rule).not.toHaveAttribute("aria-orientation");
    expect(rule).not.toHaveAttribute("tabindex");
    expect(rule.dataset["cmp"]).toBe("CMP-018");
    expect(rule.dataset["orientation"]).toBe("horizontal");
    expect(rule).not.toHaveAttribute("data-inset");
  });

  it("states a vertical orientation and marks the inset", async () => {
    const host = await mount(<Divider orientation="vertical" inset />);
    const rule = within(host).getByRole("separator");
    expect(rule).toHaveAttribute("aria-orientation", "vertical");
    expect(rule).toHaveAttribute("data-inset", "");
  });

  it.each(["horizontal", "vertical"] as const)(
    "decorative (%s) leaves the accessibility tree",
    async (orientation) => {
      const host = await mount(<Divider decorative orientation={orientation} />);
      expect(within(host).queryByRole("separator")).toBeNull();
      const rule = host.querySelector(".cv-divider");
      expect(rule).toHaveAttribute("role", "none");
      expect(rule).not.toHaveAttribute("aria-orientation");
    },
  );
});

describe("DividerLabel (CMP-030)", () => {
  it("names a horizontal separator by its visible sibling caption", async () => {
    const host = await mount(<DividerLabel label="Take profit" />);
    const rule = within(host).getByRole("separator", { name: "Take profit" });
    expect(rule).not.toHaveAttribute("aria-orientation");
    expect(rule).toBeEmptyDOMElement();
    const caption = within(host).getByText("Take profit");
    expect(caption.dataset["variant"]).toBe("caption");
    expect(caption.dataset["tone"]).toBe("secondary");
    expect(rule.getAttribute("aria-labelledby")).toBe(caption.id);
    expect(host.firstElementChild?.getAttribute("data-cmp")).toBe("CMP-030");
  });
});

describe("Divider stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-divider")).not.toBeNull();
  });
});
