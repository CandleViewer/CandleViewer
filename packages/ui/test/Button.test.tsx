// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button } from "../src/components/index.js";
import * as stories from "../src/components/Button.stories.js";
import { mount } from "./theme/mount.js";
import { politeText } from "./theme/polite.js";

const REASON = "Owner only";
// exactOptionalPropertyTypes rejects a literal `iconLeft={undefined}`; callers forwarding an optional prop do this.
const EXPLICIT_UNDEFINED: object = { iconLeft: undefined };
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

  it.each(["primary", "secondary", "ghost", "danger", "buy", "sell"] as const)(
    "emits variant %s",
    async (v) => {
      const host = await mount(<Button variant={v}>Save</Button>);
      expect(get(host).dataset["variant"]).toBe(v);
    },
  );

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

describe("Button buy, sell and icons", () => {
  const glyphs = (b: HTMLElement): NodeListOf<SVGElement> => b.querySelectorAll("svg");

  it.each([
    ["buy", "Buy / Long"],
    ["sell", "Sell / Short"],
  ] as const)(
    "%s leads with a decorative arrow and keeps its word in the name",
    async (v, name) => {
      const host = await mount(<Button variant={v}>{name}</Button>);
      const b = get(host, name);
      expect(b.dataset["side"]).toBe("");
      expect(b.querySelector(".cv-button__icon")?.nextElementSibling).toBe(
        b.querySelector(".cv-button__label"),
      );
      expect(glyphs(b)).toHaveLength(1);
      expect(glyphs(b)[0]?.getAttribute("aria-hidden")).toBe("true");
    },
  );

  it("buy and sell arrows differ, an iconLeft replaces the arrow, and iconLeft undefined keeps it", async () => {
    const host = await mount(
      <>
        <Button variant="buy">Buy</Button>
        <Button variant="sell">Sell</Button>
        <Button variant="buy" iconLeft="chevron-right">
          Buy more
        </Button>
        <Button variant="buy" {...EXPLICIT_UNDEFINED}>
          Buy again
        </Button>
      </>,
    );
    const html = (n: string): string => glyphs(get(host, n))[0]?.innerHTML ?? "";
    expect(html("Buy")).not.toBe(html("Sell"));
    expect(html("Buy more")).not.toBe(html("Buy"));
    expect(glyphs(get(host, "Buy again"))).toHaveLength(1);
    expect(html("Buy again")).toBe(html("Buy"));
  });

  it("renders iconLeft and iconRight as decorative glyphs around the label", async () => {
    const host = await mount(
      <Button iconLeft="chevron-down" iconRight="chevron-right">
        Save
      </Button>,
    );
    const b = get(host);
    expect(glyphs(b)).toHaveLength(2);
    expect(b).toHaveAccessibleName("Save");
    expect(host.querySelector(".cv-button__icon")).not.toBeNull();
  });

  it("a plain button has no glyph and no side marker", async () => {
    const host = await mount(<Button>Save</Button>);
    expect(glyphs(get(host))).toHaveLength(0);
    expect(get(host).hasAttribute("data-side")).toBe(false);
  });

  it("buy loading keeps the arrow and label, with the spinner in flow after them", async () => {
    const host = await mount(
      <Button variant="buy" loading>
        Buy / Long
      </Button>,
    );
    const b = get(host, "Buy / Long");
    expect(b).toHaveAttribute("aria-busy", "true");
    expect(b.lastElementChild?.className).toBe("cv-spinner");
    expect(b.querySelector(".cv-button__icon svg")).not.toBeNull();
  });

  it("the spinner takes the iconRight slot of a loading side button, so it does not widen", async () => {
    const host = await mount(
      <Button variant="sell" loading iconRight="chevron-right">
        Sell
      </Button>,
    );
    expect(host.querySelectorAll(".cv-button__icon")).toHaveLength(1);
  });

  it("the lock takes the iconRight slot of a gated button, keeping the arrow", async () => {
    const host = await mount(
      <Button variant="sell" iconRight="chevron-right" disabledReason={REASON}>
        Sell
      </Button>,
    );
    const b = get(host, "Sell");
    expect(b.querySelectorAll(".cv-button__icon")).toHaveLength(1);
    expect(b.querySelectorAll(".cv-button__glyph")).toHaveLength(1);
    expect(b).toHaveAccessibleDescription(REASON);
  });

  it("a gated side button no-ops on Enter and Space and keeps its arrow", async () => {
    const onClick = fn();
    const host = await mount(
      <Button variant="buy" disabledReason={REASON} onClick={onClick}>
        Buy
      </Button>,
    );
    await userEvent.tab();
    await userEvent.keyboard("{Enter} ");
    expect(onClick).not.toHaveBeenCalled();
    expect(get(host, "Buy").querySelector(".cv-button__icon svg")).not.toBeNull();
  });
});

describe("Button stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("button").length).toBeGreaterThan(0);
  });
});

describe("Button gated announcement (D09 2.2)", () => {
  it("click, Enter and Space each announce the reason once and never call the handler", async () => {
    const onClick = fn();
    const host = await mount(
      <Button disabledReason={REASON} onClick={onClick}>
        Save
      </Button>,
    );
    const b = within(host).getByRole("button", { name: "Save" });
    expect(await politeText()).toBe("");
    await userEvent.click(b);
    expect(await politeText()).toBe(REASON);
    await userEvent.keyboard("{Enter}");
    expect(await politeText()).toBe(REASON);
    await userEvent.keyboard(" ");
    expect(await politeText()).toBe(REASON);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("a repeat press clears the region first, so the same sentence announces again", async () => {
    const host = await mount(<Button disabledReason={REASON}>Save</Button>);
    const b = within(host).getByRole("button", { name: "Save" });
    fireEvent.click(b);
    expect(document.getElementById("cv-theme-live-region")?.textContent).toBe("");
    expect(await politeText()).toBe(REASON);
  });

  it("focus and hover announce nothing, and an allowed activation announces nothing", async () => {
    const onClick = fn();
    const gated = await mount(<Button disabledReason={REASON}>Save</Button>);
    await userEvent.tab();
    await userEvent.hover(within(gated).getByRole("button"));
    expect(await politeText()).toBe("");
    const open = await mount(<Button onClick={onClick}>Go</Button>);
    await userEvent.click(within(open).getByRole("button", { name: "Go" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(await politeText()).toBe("");
  });
});
