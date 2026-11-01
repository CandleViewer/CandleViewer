// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { GatedAnnounceProvider, IconButton } from "../src/components/index.js";
import * as stories from "../src/components/IconButton.stories.js";
import { holdEnter } from "./heldEnter.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

const REASON = "Owner only";
const get = (host: HTMLElement, name = "Settings"): HTMLButtonElement =>
  within(host).getByRole("button", { name }) as HTMLButtonElement;

describe("IconButton (CMP-002)", () => {
  it("is a native button named by the required label, secondary md by default", async () => {
    const host = await mount(<IconButton icon="chevron-down" label="Settings" />);
    const b = get(host);
    expect(b.tagName).toBe("BUTTON");
    expect(b).toHaveProperty("type", "button");
    expect(b).toHaveAttribute("aria-label", "Settings");
    expect(b.dataset["cmp"]).toBe("CMP-002");
    expect(b.dataset["variant"]).toBe("secondary");
    expect(b.dataset["size"]).toBe("md");
    expect(b.textContent).toBe("");
    expect(b.hasAttribute("aria-pressed")).toBe(false);
  });

  it("requires a label and keeps pressed to secondary and ghost at the type level", () => {
    // @ts-expect-error an icon-only control without a label has no accessible name
    const noLabel = <IconButton icon="lock" />;
    // @ts-expect-error pressed is toggle mode: secondary and ghost only
    const pressedPrimary = <IconButton icon="lock" label="x" variant="primary" pressed />;
    expect([noLabel, pressedPrimary]).toHaveLength(2);
  });

  it.each(["primary", "secondary", "ghost", "danger"] as const)("emits variant %s", async (v) => {
    const host = await mount(<IconButton icon="lock" label="Settings" variant={v} />);
    expect(get(host).dataset["variant"]).toBe(v);
  });

  it.each(["sm", "md", "lg"] as const)(
    "scales the glyph at size %s, decoratively",
    async (size) => {
      const host = await mount(<IconButton icon="chevron-down" label="Settings" size={size} />);
      const svg = host.querySelector("svg");
      expect(svg?.getAttribute("aria-hidden")).toBe("true");
      expect(svg?.outerHTML).toContain(`--size-icon-${size}`);
      expect(get(host).dataset["size"]).toBe(size);
    },
  );

  it("emits the density attribute", async () => {
    const host = await mount(<IconButton icon="lock" label="Settings" density="compact" />);
    expect(get(host).dataset["density"]).toBe("compact");
  });

  it("activates on click, Enter and Space", async () => {
    const onClick = fn();
    const host = await mount(<IconButton icon="lock" label="Settings" onClick={onClick} />);
    await userEvent.tab();
    expect(get(host)).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await userEvent.click(get(host));
    expect(onClick).toHaveBeenCalledTimes(3);
  });

  it("toggle mode reports aria-pressed and the name does not change", async () => {
    const host = await mount(
      <>
        <IconButton icon="lock" label="Pin" pressed />
        <IconButton icon="lock" label="Unpin" variant="ghost" pressed={false} />
      </>,
    );
    expect(get(host, "Pin")).toHaveAttribute("aria-pressed", "true");
    expect(get(host, "Unpin")).toHaveAttribute("aria-pressed", "false");
  });

  it("plain disabled uses the native attribute, leaves the Tab order and fires nothing", async () => {
    const onClick = fn();
    const host = await mount(
      <IconButton icon="lock" label="Settings" disabled onClick={onClick} />,
    );
    const b = get(host);
    expect(b.disabled).toBe(true);
    await userEvent.tab();
    expect(b).not.toHaveFocus();
    fireEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("disabled with a reason: focusable, aria-disabled, described, lock badge, no activation", async () => {
    const onClick = fn();
    const host = await mount(
      <IconButton
        icon="chevron-down"
        label="Settings"
        disabled
        disabledReason={REASON}
        onClick={onClick}
      />,
    );
    const b = get(host);
    expect(b.disabled).toBe(false);
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).toHaveAccessibleDescription(REASON);
    expect(b).toHaveAccessibleName("Settings");
    expect(within(b).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    await userEvent.tab();
    expect(b).toHaveFocus();
    await userEvent.keyboard("{Enter} ");
    await userEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders the reason as plain text and treats a blank one as none", async () => {
    const host = await mount(
      <>
        <IconButton icon="lock" label="A" disabledReason="<b>no</b>" />
        <IconButton icon="lock" label="B" disabledReason="  " />
      </>,
    );
    expect(host.querySelector("b")).toBeNull();
    expect(get(host, "A")).toHaveAccessibleDescription("<b>no</b>");
    expect(get(host, "B")).not.toHaveAttribute("aria-disabled");
    expect(get(host, "B").querySelector(".cv-icon-button__badge")).toBeNull();
  });

  it("merges a caller's aria-describedby with the reason and forwards other attributes", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <IconButton
          icon="lock"
          label="Settings"
          aria-describedby="help"
          disabledReason={REASON}
          data-testid="x"
        />
      </>,
    );
    expect(get(host)).toHaveAccessibleDescription(`Help ${REASON}`);
    expect(get(host)).toHaveAttribute("data-testid", "x");
  });
});

describe("IconButton stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("button").length).toBeGreaterThan(0);
  });
});

describe("IconButton gated announcement (D09 2.2)", () => {
  it("announces the reason on a gated click, announces nothing when allowed", async () => {
    const onClick = fn();
    const host = await mount(
      <IconButton icon="lock" label="Arm" disabledReason={REASON} onClick={onClick} />,
    );
    await userEvent.click(within(host).getByRole("button", { name: "Arm" }));
    expect(await politeText()).toBe(REASON);
    expect(onClick).not.toHaveBeenCalled();
    clearPolite();
    const open = await mount(<IconButton icon="lock" label="Arm" onClick={onClick} />);
    await userEvent.click(within(open).getByRole("button", { name: "Arm" }));
    expect(await politeText()).toBe("");
  });
});

// E09-D09 §2.2 "one notice, many pointers": a read-only panel's one notice describes every gated control;
// E08-S08's WatchlistGroupTabs "+" and ColumnPicker's move buttons point at it. 2b stays: the badge and the echo.
describe("IconButton disabledReasonId: the reason shown by the host's notice", () => {
  it("is described by the notice alone, keeps its name, badge and echo, and renders no hidden copy", async () => {
    const host = await mount(
      <>
        <p id="notice">{REASON}</p>
        <IconButton
          icon="plus"
          label="New watchlist"
          disabledReason={REASON}
          disabledReasonId="notice"
        />
      </>,
    );
    const b = get(host, "New watchlist");
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).toHaveAttribute("aria-describedby", "notice");
    expect(b).toHaveAccessibleDescription(REASON);
    expect(within(host).getAllByText(REASON)).toHaveLength(1);
    expect(b.querySelector(".cv-icon-button__badge svg")).not.toBeNull();
    expect(document.querySelector('[data-cmp="CMP-016"]')).toHaveTextContent(
      `New watchlist · ${REASON}`,
    );
  });
});

// G-T2.3 (E09-D09 §9.3): a held Enter's repeats would each click the native button; a T2 one swallows them.
describe("IconButton T2: a held Enter says the reason once per press", () => {
  it("a held Enter's repeats change nothing and say nothing; the next press says the reason again", async () => {
    const onClick = fn();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <IconButton icon="plus" label="Settings" disabledReason={REASON} onClick={onClick} />
      </GatedAnnounceProvider>,
    );
    holdEnter(get(host), 2);
    expect(announce.mock.calls).toEqual([[REASON]]);
    holdEnter(get(host), 0);
    expect(announce.mock.calls).toEqual([[REASON], [REASON]]);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("an enabled icon button keeps the native repeat: a held Enter clicks once per keydown", async () => {
    const onClick = fn();
    const host = await mount(<IconButton icon="plus" label="Settings" onClick={onClick} />);
    holdEnter(get(host), 2);
    expect(onClick).toHaveBeenCalledTimes(3);
  });
});
