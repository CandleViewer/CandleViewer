// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Avatar } from "../src/components/index.js";
import { avatarInitials } from "../src/components/Avatar.js";
import * as stories from "../src/components/Avatar.stories.js";
import { mount } from "./theme/mount.js";

describe("Avatar (CMP-013)", () => {
  it("is decorative by default, beside its visible name", async () => {
    const host = await mount(<Avatar label="Alpha Desk" />);
    expect(within(host).queryByRole("img")).toBeNull();
    const avatar = host.querySelector(".cv-avatar");
    expect(avatar).toHaveAttribute("aria-hidden", "true");
    expect(avatar).toHaveTextContent("AD");
    expect((avatar as HTMLElement).dataset["size"]).toBe("md");
  });

  it("standalone, it is an img named by the full label, never the initials", async () => {
    const host = await mount(<Avatar label="Alpha Desk" standalone />);
    const avatar = within(host).getByRole("img", { name: "Alpha Desk" });
    expect(avatar).not.toHaveAttribute("aria-hidden");
    expect(avatar.dataset["cmp"]).toBe("CMP-013");
  });

  it.each(["", "   "])(
    "standalone with a blank label %j stays hidden, never an unnamed img",
    async (label) => {
      const host = await mount(<Avatar label={label} standalone />);
      expect(within(host).queryByRole("img")).toBeNull();
      expect(host.querySelector(".cv-avatar")).toHaveAttribute("aria-hidden", "true");
    },
  );

  it.each([
    ["Alpha Desk", "md", "AD"],
    ["Alpha Desk", "sm", "A"],
    ["  bravo   sub fund ", "md", "BS"],
    ["echo", "md", "E"],
    ["", "md", ""],
  ] as const)("derives the initials of %j at %s as %j", (label, size, initials) => {
    expect(avatarInitials(label, size)).toBe(initials);
  });
});

describe("Avatar stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-avatar")).not.toBeNull();
  });
});
