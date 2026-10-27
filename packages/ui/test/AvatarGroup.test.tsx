// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { AvatarGroup } from "../src/components/index.js";
import * as stories from "../src/components/AvatarGroup.stories.js";
import { mount } from "./theme/mount.js";

describe("AvatarGroup (CMP-025)", () => {
  const items = ["Alpha Desk", "Bravo Sub", "Carry Fund", "Delta Main", "Echo Hedge"].map(
    (label) => ({ label }),
  );

  it("is one img whose name lists every label, the hidden ones included", async () => {
    const host = await mount(<AvatarGroup items={items} max={3} />);
    const group = within(host).getByRole("img", {
      name: "5 accounts: Alpha Desk, Bravo Sub, Carry Fund, Delta Main, Echo Hedge",
    });
    expect(group.dataset["cmp"]).toBe("CMP-025");
    expect(group).toHaveAttribute("data-overflow");
    expect(group.querySelectorAll(".cv-avatar")).toHaveLength(3);
    const more = group.querySelector(".cv-avatar-group__more");
    expect(more).toHaveTextContent("+2");
    expect(more).toHaveAttribute("aria-hidden", "true");
    for (const avatar of group.querySelectorAll(".cv-avatar")) {
      expect(avatar).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("draws no chip when every item fits, and names a single account in the singular", async () => {
    const host = await mount(<AvatarGroup items={items.slice(0, 1)} max={3} />);
    const group = within(host).getByRole("img", { name: "1 account: Alpha Desk" });
    expect(group).not.toHaveAttribute("data-overflow");
    expect(group.querySelector(".cv-avatar-group__more")).toBeNull();
  });

  it.each([
    [5, 0, 0, "+5"],
    [5, -2, 0, "+5"],
    [5, Number.NaN, 0, "+5"],
    [5, 2.7, 2, "+3"],
    [5, Number.POSITIVE_INFINITY, 5, null],
    [1, 1, 1, null],
  ])("%s items at max %s: %s avatars, chip %s", async (count, max, drawn, chip) => {
    const host = await mount(<AvatarGroup items={items.slice(0, count)} max={max} />);
    const group = within(host).getByRole("img", {
      name: count === 1 ? "1 account: Alpha Desk" : /^5 accounts: Alpha Desk, .*Echo Hedge$/,
    });
    expect(group.querySelectorAll(".cv-avatar")).toHaveLength(drawn);
    const more = group.querySelector(".cv-avatar-group__more");
    if (chip === null) expect(more).toBeNull();
    else expect(more).toHaveTextContent(chip);
  });

  it("renders nothing for no items", async () => {
    const host = await mount(<AvatarGroup items={[]} max={3} />);
    expect(host).toBeEmptyDOMElement();
  });
});

describe("AvatarGroup stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getByRole("img")).toHaveAccessibleName(/accounts: /);
  });
});
