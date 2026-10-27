// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Badge } from "../src/components/index.js";
import { badgeCountText } from "../src/components/Badge.js";
import * as stories from "../src/components/Badge.stories.js";
import { mount } from "./theme/mount.js";

describe("Badge (CMP-012)", () => {
  it("a standalone count is an img named by the count and what is counted, neutral by default", async () => {
    const host = await mount(<Badge value={3} label="unread alerts" />);
    const badge = within(host).getByRole("img", { name: "3 unread alerts" });
    expect(badge).toHaveTextContent("3");
    expect(badge.dataset["cmp"]).toBe("CMP-012");
    expect(badge.dataset["variant"]).toBe("count");
    expect(badge.dataset["tone"]).toBe("neutral");
    expect(badge).not.toHaveAttribute("tabindex");
  });

  it("caps the shown count at 99+ while the name keeps the full number", async () => {
    const host = await mount(<Badge value={1500} label="failed orders" tone="danger" />);
    const badge = within(host).getByRole("img", { name: "1500 failed orders" });
    expect(badge).toHaveTextContent(/^99\+$/);
    expect(badge.dataset["tone"]).toBe("danger");
  });

  it.each([
    [0, "0"],
    [99, "99"],
    [100, "99+"],
    [-4, "0"],
    [7.9, "7"],
  ])("displays %s as %s", (value, text) => {
    expect(badgeCountText(value)).toBe(text);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    "renders nothing for a non-finite value (%s), shown or announced",
    async (value) => {
      const host = await mount(<Badge value={value} label="unread alerts" />);
      expect(host).toBeEmptyDOMElement();
    },
  );

  it("a blank label leaves the count hidden, never an unnamed img", async () => {
    const host = await mount(<Badge value={3} label="  " />);
    expect(within(host).queryByRole("img")).toBeNull();
    expect(host.querySelector(".cv-badge")).toHaveAttribute("aria-hidden", "true");
  });

  it("a count on a labelled control is hidden and leaves the name to the control", async () => {
    const host = await mount(
      <button type="button" aria-label="Notifications, 3 unread">
        <Badge value={3} tone="info" />
      </button>,
    );
    expect(within(host).queryByRole("img")).toBeNull();
    expect(host.querySelector(".cv-badge")).toHaveAttribute("aria-hidden", "true");
    expect(within(host).getByRole("button")).toHaveAccessibleName("Notifications, 3 unread");
  });

  it.each(["neutral", "info", "success", "warning", "danger"] as const)(
    "a %s dot is aria-hidden and holds no text",
    async (tone) => {
      const host = await mount(<Badge variant="dot" tone={tone} />);
      const dot = host.querySelector(".cv-badge");
      expect(dot).toHaveAttribute("aria-hidden", "true");
      expect(dot).not.toHaveAttribute("role");
      expect(dot?.textContent).toBe("");
      expect((dot as HTMLElement).dataset["tone"]).toBe(tone);
    },
  );

  it("refuses a value or a label on a dot at the type level", () => {
    // @ts-expect-error a dot never carries a count
    const valued = <Badge variant="dot" value={3} />;
    // @ts-expect-error a dot is never named: it is always paired with a visible word
    const named = <Badge variant="dot" label="alerts" />;
    expect([valued, named]).toHaveLength(2);
  });
});

describe("Badge stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-badge")).not.toBeNull();
  });
});
