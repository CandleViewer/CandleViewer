// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button, GatedAnnounceProvider } from "../src/components/index.js";
import { mountLiveRegion } from "../src/theme/a11y.js";
import * as stories from "../src/components/Button.stories.js";
import { holdEnter } from "./heldEnter.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

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
    clearPolite();
    await userEvent.keyboard("{Enter}");
    expect(await politeText()).toBe(REASON);
    clearPolite();
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

describe("Button gated announcement routed by a host", () => {
  it("a provider's announce receives the reason, and the default region stays empty", async () => {
    clearPolite();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Button disabledReason={REASON}>Save</Button>
      </GatedAnnounceProvider>,
    );
    await userEvent.click(within(host).getByRole("button"));
    expect(announce).toHaveBeenCalledTimes(1);
    expect(announce).toHaveBeenCalledWith(REASON);
    expect(await politeText()).toBe("");
  });

  it("under a no-op provider the atom announces nothing; under the default it announces once", async () => {
    clearPolite();
    const quiet = await mount(
      <GatedAnnounceProvider announce={() => undefined}>
        <Button disabledReason={REASON}>Quiet</Button>
      </GatedAnnounceProvider>,
    );
    await userEvent.click(within(quiet).getByRole("button", { name: "Quiet" }));
    expect(await politeText()).toBe("");
    const spoken = await mount(<Button disabledReason={REASON}>Spoken</Button>);
    // Count the region's non-empty writes: the text is replaced, so reading it alone can't tell once from twice.
    const region = mountLiveRegion();
    const records: MutationRecord[] = [];
    const watch = new MutationObserver((batch) => records.push(...batch));
    watch.observe(region, { childList: true });
    await userEvent.click(within(spoken).getByRole("button", { name: "Spoken" }));
    expect(await politeText()).toBe(REASON);
    records.push(...watch.takeRecords());
    watch.disconnect();
    const writes = records
      .flatMap((r) => [...r.addedNodes].map((n) => n.textContent ?? ""))
      .filter((text) => text !== "");
    expect(writes).toEqual([REASON]);
    clearPolite();
  });
});

// E09-D09 §2.2 rendering 2a with the reason node the host's (a caption under the button, or a read-only panel's
// one notice): E08-S08's FileDrop targets and ColumnPicker's menu button point at it.
describe("Button disabledReasonId: the reason shown by the host (2a)", () => {
  const Captioned = (): JSX.Element => (
    <>
      <Button disabledReason={REASON} disabledReasonId="save-reason">
        Save
      </Button>
      <p id="save-reason">{REASON}</p>
    </>
  );

  it("is described by the host's node alone: no copy of its own and no echo", async () => {
    const host = await mount(<Captioned />);
    const b = get(host, "Not available Save");
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).toHaveAttribute("aria-describedby", "save-reason");
    expect(b).toHaveAccessibleDescription(REASON);
    expect(within(host).getAllByText(REASON)).toHaveLength(1);
    await userEvent.hover(b);
    expect(document.querySelector('[data-cmp="CMP-016"]')).toBeNull();
  });

  it("its lock leads the label, named Not available, and no lock trails it", async () => {
    const host = await mount(<Captioned />);
    const b = get(host, "Not available Save");
    const lock = within(b).getByRole("img", { name: "Not available" });
    expect(b.firstElementChild).toContainElement(lock);
    expect(b.querySelectorAll("svg")).toHaveLength(1);
  });

  it("a press changes nothing and announces the reason once", async () => {
    const onClick = fn();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Button disabledReason={REASON} disabledReasonId="save-reason" onClick={onClick}>
          Save
        </Button>
        <p id="save-reason">{REASON}</p>
      </GatedAnnounceProvider>,
    );
    await userEvent.click(get(host, "Not available Save"));
    expect(onClick).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[REASON]]);
  });

  it("without a reason the id points at nothing: an enabled button with no description", async () => {
    const host = await mount(<Button disabledReasonId="save-reason">Save</Button>);
    const b = get(host);
    expect(b).not.toHaveAttribute("aria-describedby");
    expect(b).not.toHaveAttribute("aria-disabled");
  });
});

// G-T2.3 (E09-D09 §9.3; the orchestrator's design read on #5146): a held Enter repeats its keydown, and each repeat
// clicks a native button. A T2 button swallows the repeats, so a held key says its reason once per press.
describe("Button T2: a held Enter says the reason once per press", () => {
  it("a held Enter's repeats change nothing and say nothing; the next press says the reason again", async () => {
    const onClick = fn();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Button disabledReason={REASON} onClick={onClick}>
          Save
        </Button>
      </GatedAnnounceProvider>,
    );
    holdEnter(get(host), 2);
    expect(announce.mock.calls).toEqual([[REASON]]);
    holdEnter(get(host), 0);
    expect(announce.mock.calls).toEqual([[REASON], [REASON]]);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("the caller's onKeyDown still sees every keydown of the held key", async () => {
    const onKeyDown = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={() => undefined}>
        <Button disabledReason={REASON} onKeyDown={onKeyDown}>
          Save
        </Button>
      </GatedAnnounceProvider>,
    );
    holdEnter(get(host), 2);
    expect(onKeyDown).toHaveBeenCalledTimes(3);
  });

  it("an enabled button keeps the native repeat: a held Enter clicks once per keydown", async () => {
    const onClick = fn();
    const host = await mount(<Button onClick={onClick}>Save</Button>);
    holdEnter(get(host), 2);
    expect(onClick).toHaveBeenCalledTimes(3);
  });
});

// The validity look (E09-D09 §9.1: a control disabled by form validity is the host's call; E16-D04 §1.3, E16-D06
// T2-07 and T2-10): never T2. The button stays a Tab stop with aria-disabled, its fill and label dimmed and no lock,
// described by the host's reason node; a press does nothing here and says nothing (the host answers it).
describe("Button unavailableReasonId: the validity look", () => {
  const WHY = "Type ETHUSDT exactly to confirm.";
  const Invalid = ({ onClick }: { readonly onClick?: () => void }): JSX.Element => (
    <>
      <Button variant="danger" unavailableReasonId="purge-why" {...(onClick ? { onClick } : {})}>
        Purge ETHUSDT data
      </Button>
      <p id="purge-why">{WHY}</p>
    </>
  );

  it("stays a Tab stop: aria-disabled, not disabled, described by the host's node, no lock and no echo", async () => {
    const host = await mount(<Invalid />);
    const b = get(host, "Purge ETHUSDT data");
    expect(b.disabled).toBe(false);
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).toHaveAttribute("data-unavailable", "");
    expect(b).not.toHaveAttribute("data-gated");
    expect(b).toHaveAccessibleDescription(WHY);
    expect(within(b).queryByRole("img", { name: "Not available" })).toBeNull();
    expect(b.querySelectorAll("svg")).toHaveLength(0);
    await userEvent.tab();
    expect(b).toHaveFocus();
    await userEvent.hover(b);
    expect(document.querySelector('[data-cmp="CMP-016"]')).toBeNull();
  });

  it("a click, Enter or Space does nothing and announces nothing; a held Enter's repeats are swallowed", async () => {
    const onClick = fn();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Invalid onClick={onClick} />
      </GatedAnnounceProvider>,
    );
    const b = get(host, "Purge ETHUSDT data");
    await userEvent.click(b);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(fireEvent.keyDown(b, { key: "Enter", repeat: true })).toBe(false);
    expect(onClick).not.toHaveBeenCalled();
    expect(announce).not.toHaveBeenCalled();
  });

  it("a disabledReason wins (T2, the lock), and native disabled wins over the look", async () => {
    const gated = await mount(
      <Button disabledReason={REASON} unavailableReasonId="purge-why">
        Save
      </Button>,
    );
    const t2 = within(gated).getByRole("button", { name: /Save/ });
    expect(t2).toHaveAttribute("data-gated", "");
    expect(t2).not.toHaveAttribute("data-unavailable");
    expect(t2).toHaveAccessibleDescription(REASON);
    const off = await mount(
      <Button disabled unavailableReasonId="purge-why">
        Close
      </Button>,
    );
    const b = get(off, "Close");
    expect(b).toBeDisabled();
    expect(b).not.toHaveAttribute("aria-disabled");
    expect(b).not.toHaveAttribute("data-unavailable");
  });

  it("a blank id is no look: the button is enabled and undescribed", async () => {
    const onClick = fn();
    const host = await mount(
      <Button unavailableReasonId="  " onClick={onClick}>
        Save
      </Button>,
    );
    const b = get(host);
    expect(b).not.toHaveAttribute("aria-disabled");
    expect(b).not.toHaveAttribute("aria-describedby");
    await userEvent.click(b);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
