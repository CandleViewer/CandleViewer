// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button } from "../src/components/index.js";
import * as stories from "../src/components/Button.stories.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
const get = (host: HTMLElement, name = "Save"): HTMLButtonElement =>
  within(host).getByRole("button", { name }) as HTMLButtonElement;

describe("Button (CMP-001)", () => {
  it("renders a native button of type button, secondary md by default", async () => {
    const host = await mount(<Button>Save</Button>);
    const b = get(host);
    expect(b.tagName).toBe("BUTTON");
    expect(b).toHaveProperty("type", "button");
    expect(b.dataset["variant"]).toBe("secondary");
    expect(b.dataset["size"]).toBe("md");
    expect(b.dataset["cmp"]).toBe("CMP-001");
    expect(b.hasAttribute("aria-busy")).toBe(false);
    expect(b.hasAttribute("aria-disabled")).toBe(false);
  });

  it.each(["primary", "secondary", "ghost", "danger"] as const)("emits variant %s", async (v) => {
    const host = await mount(<Button variant={v}>Save</Button>);
    expect(get(host).dataset["variant"]).toBe(v);
  });

  it("emits size, full width and density attributes", async () => {
    const host = await mount(
      <Button size="lg" fullWidth density="comfortable">
        Save
      </Button>,
    );
    const b = get(host);
    expect(b.dataset["size"]).toBe("lg");
    expect(b.hasAttribute("data-full-width")).toBe(true);
    expect(b.dataset["density"]).toBe("comfortable");
  });

  it("activates on click, Enter and Space", async () => {
    const onClick = fn();
    const host = await mount(<Button onClick={onClick}>Save</Button>);
    await userEvent.tab();
    expect(get(host)).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await userEvent.click(get(host));
    expect(onClick).toHaveBeenCalledTimes(3);
  });

  it("plain disabled uses the native attribute, leaves the Tab order and fires nothing", async () => {
    const onClick = fn();
    const host = await mount(
      <Button disabled onClick={onClick}>
        Save
      </Button>,
    );
    const b = get(host);
    expect(b.disabled).toBe(true);
    await userEvent.tab();
    expect(b).not.toHaveFocus();
    fireEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("disabled with a reason: focusable, aria-disabled, reason described at mount, no activation", async () => {
    const onClick = fn();
    const host = await mount(
      <Button disabled disabledReason={REASON} onClick={onClick}>
        Save
      </Button>,
    );
    const b = get(host);
    expect(b.disabled).toBe(false);
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).toHaveAccessibleDescription(REASON);
    expect(b.hasAttribute("data-gated")).toBe(true);
    expect(host.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    await userEvent.tab();
    expect(b).toHaveFocus();
    await userEvent.keyboard("{Enter} ");
    await userEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders the reason as plain text, never markup", async () => {
    const host = await mount(<Button disabledReason="<b>no</b>">Save</Button>);
    expect(host.querySelector("b")).toBeNull();
    expect(get(host)).toHaveAccessibleDescription("<b>no</b>");
  });

  it("an empty reason is no reason: plain disabled semantics", async () => {
    const host = await mount(
      <Button disabled disabledReason="">
        Save
      </Button>,
    );
    expect(get(host).disabled).toBe(true);
    expect(host.querySelector(".cv-visually-hidden")).toBeNull();
  });

  it("loading keeps the name, sets aria-busy, stays focusable and suppresses activation", async () => {
    const onClick = fn();
    const host = await mount(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    );
    const b = get(host);
    expect(b).toHaveAttribute("aria-busy", "true");
    expect(b.querySelector(".cv-spinner")).not.toBeNull();
    await userEvent.tab();
    expect(b).toHaveFocus();
    await userEvent.keyboard("{Enter} ");
    await userEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("merges a caller's aria-describedby with the reason and forwards other attributes", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <Button aria-describedby="help" disabledReason={REASON} data-testid="x">
          Save
        </Button>
      </>,
    );
    expect(get(host)).toHaveAccessibleDescription(`Help ${REASON}`);
    expect(get(host)).toHaveAttribute("data-testid", "x");
  });

  it("treats a whitespace-only disabledReason as no reason", async () => {
    const host = await mount(<Button disabledReason="   ">Save</Button>);
    const b = get(host);
    expect(b).not.toHaveAttribute("aria-disabled");
    expect(b).not.toHaveAttribute("data-gated");
    expect(b).not.toHaveAccessibleDescription();
  });

  it("keeps the full text as the accessible name for a long label", async () => {
    const long = "Submit the order to every selected account in the trade group now";
    const host = await mount(<Button fullWidth>{long}</Button>);
    expect(get(host, long).dataset["fullWidth"]).toBe("");
  });

  it("honours type=submit", async () => {
    const host = await mount(<Button type="submit">Save</Button>);
    expect(get(host)).toHaveProperty("type", "submit");
  });
});

describe("Button stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("button").length).toBeGreaterThan(0);
  });
});
