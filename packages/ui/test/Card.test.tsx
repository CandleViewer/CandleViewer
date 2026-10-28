// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button, Card } from "../src/components/index.js";
import * as stories from "../src/components/Card.stories.js";
import { mount } from "./theme/mount.js";

const root = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>(".cv-card");
  if (el === null) throw new Error("no card rendered");
  return el;
};

describe("Card (CMP-050)", () => {
  it("defaults: elevated, panel padding, a level-3 heading, no role of its own", async () => {
    const host = await mount(<Card title="Accounts">Body</Card>);
    const card = root(host);
    expect(card.dataset["cmp"]).toBe("CMP-050");
    expect(card.dataset["surface"]).toBe("elevated");
    expect(card.dataset["padding"]).toBe("panel");
    expect(card.tagName).toBe("DIV");
    expect(card).not.toHaveAttribute("role");
    expect(card).not.toHaveAttribute("aria-labelledby");
    expect(within(host).getByRole("heading", { level: 3, name: "Accounts" })).toBeVisible();
    expect(within(host).queryByRole("region")).toBeNull();
  });

  it.each([2, 3, 4] as const)("headingLevel %s renders that heading level", async (level) => {
    const host = await mount(
      <Card title="Accounts" headingLevel={level}>
        Body
      </Card>,
    );
    expect(within(host).getByRole("heading", { level, name: "Accounts" })).toBeVisible();
  });

  it("headingLevel 0 renders the title as plain text, never a heading", async () => {
    const host = await mount(
      <Card title="Scalping layout" headingLevel={0}>
        Body
      </Card>,
    );
    expect(within(host).queryByRole("heading")).toBeNull();
    expect(root(host)).toHaveTextContent("Scalping layout");
  });

  it("region: a section landmark named by its heading", async () => {
    const host = await mount(
      <Card region title="Audit log" headingLevel={2}>
        Body
      </Card>,
    );
    const region = within(host).getByRole("region", { name: "Audit log" });
    expect(region.tagName).toBe("SECTION");
    expect(region.getAttribute("aria-labelledby")).toBe(
      within(host).getByRole("heading", { name: "Audit log" }).id,
    );
  });

  it("flat and padding none reach the data attributes the CSS keys on", async () => {
    const host = await mount(
      <Card title="Fills" surface="flat" padding="none">
        Body
      </Card>,
    );
    expect(root(host).dataset["surface"]).toBe("flat");
    expect(root(host).dataset["padding"]).toBe("none");
  });

  it("without a title or actions there is no header; the body still renders", async () => {
    const host = await mount(<Card>Only body</Card>);
    expect(host.querySelector(".cv-card__header")).toBeNull();
    expect(host.querySelector(".cv-card__body")).toHaveTextContent("Only body");
  });

  it("actions sit in the header after the title, before the body (DOM order)", async () => {
    const host = await mount(
      <Card title="Accounts" actions={<Button>Manage</Button>}>
        <p>Body</p>
      </Card>,
    );
    const header = host.querySelector(".cv-card__header");
    expect(header?.lastElementChild).toHaveTextContent("Manage");
    const order = [...root(host).querySelectorAll("h3, button, p")].map((e) => e.tagName);
    expect(order).toEqual(["H3", "BUTTON", "P"]);
  });

  it("actions without a title still render the header", async () => {
    const host = await mount(<Card actions={<Button>Manage</Button>}>Body</Card>);
    expect(within(host).getByRole("button", { name: "Manage" })).toBeVisible();
    expect(within(host).queryByRole("heading")).toBeNull();
  });
});

describe("Card stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector(".cv-card")).not.toBeNull();
  });
});
