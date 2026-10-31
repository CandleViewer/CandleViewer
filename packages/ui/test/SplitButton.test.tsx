// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  formatRbacReason,
  RbacGate,
  SplitButton,
  type MenuItem,
  type SplitButtonProps,
} from "../src/components/index.js";
import * as stories from "../src/components/SplitButton.stories.js";
import { seriousViolations } from "./axe.js";
import { clearPolite, politeText } from "./theme/polite.js";
import { mount } from "./theme/mount.js";

const page = within(document.body);
const MORE = "More close actions, BTCUSDT Long on Main";
const VIEWER = formatRbacReason("rbac.permission", { verb: "change positions" });

interface Rendered {
  readonly onClick: ReturnType<typeof fn>;
  readonly items: MenuItem[];
}

/** One split button with two items, plus a button after it (where Tab leaves to). */
async function render(extra: Partial<SplitButtonProps> = {}): Promise<Rendered> {
  const onClick = fn();
  const items: MenuItem[] = [
    { id: "pct25", label: "Close 25 %", onSelect: fn() },
    { id: "pct50", label: "Close 50 %", onSelect: fn() },
  ];
  const props = {
    primary: { label: "Close", busyLabel: "Closing…", onClick },
    items,
    menuLabel: MORE,
    ...extra,
  } as SplitButtonProps; // the test passes each gate shape on purpose; the props union is checked by tsc below
  await mount(
    <>
      <SplitButton {...props} />
      <button type="button">After</button>
    </>,
  );
  return { onClick, items };
}
const primary = (name = "Close"): HTMLElement => page.getByRole("button", { name });
const toggle = (): HTMLElement => page.getByRole("button", { name: MORE });

describe("SplitButton (CMP-057)", () => {
  it("marks exactly one root with data-cmp", async () => {
    await render();
    expect(document.querySelectorAll('[data-cmp="CMP-057"]')).toHaveLength(1);
  });

  it("is two separately focusable controls: the primary by its label, the ▾ by its row's name", async () => {
    const { onClick } = await render();
    const root = document.querySelector<HTMLElement>('[data-cmp="CMP-057"]');
    expect(root?.hasAttribute("role")).toBe(false);
    expect(primary().dataset["cmp"]).toBe("CMP-001");
    expect(toggle().dataset["cmp"]).toBe("CMP-002");
    expect(toggle()).toHaveAttribute("aria-haspopup", "menu");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    await userEvent.tab();
    expect(primary()).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledTimes(1);
    await userEvent.tab();
    expect(toggle()).toHaveFocus();
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
  });

  it("the ▾ follows CMP-041: ↓ opens on the first item, Enter selects and returns focus, Esc closes", async () => {
    const { items } = await render();
    toggle().focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(page.getByRole("menu", { name: MORE })).toBeDefined();
    expect(page.getByRole("menuitem", { name: "Close 25 %" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(items[1]?.onSelect).toHaveBeenCalledTimes(1);
    expect(toggle()).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(page.getByRole("menuitem", { name: "Close 25 %" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(toggle()).toHaveFocus();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  describe("the T2 contract of the primary's reason (32-design-specs G-T2)", () => {
    it("keeps its role and full label, aria-disabled and never disabled, in the Tab order", async () => {
      await render({ allowed: false, reason: VIEWER });
      const gated = primary();
      expect(gated).toHaveAttribute("aria-disabled", "true");
      expect(gated).not.toHaveAttribute("disabled");
      expect(gated.tagName).toBe("BUTTON");
      expect(gated).toHaveAccessibleName("Close");
      await userEvent.tab();
      expect(gated).toHaveFocus();
    });

    it("links the reason by aria-describedby to a node in the DOM at mount", async () => {
      await render({ allowed: false, reason: VIEWER });
      const id = primary().getAttribute("aria-describedby") ?? "";
      expect(document.getElementById(id)).toHaveTextContent(VIEWER);
      expect(primary()).toHaveAccessibleDescription(VIEWER);
    });

    it("a press sends nothing and re-shows the reason once, politely, each time", async () => {
      const { onClick } = await render({ allowed: false, reason: VIEWER });
      clearPolite();
      expect(await politeText()).toBe("");
      await userEvent.tab();
      await userEvent.keyboard("{Enter}");
      expect(await politeText()).toBe(VIEWER);
      clearPolite();
      await userEvent.keyboard(" ");
      expect(await politeText()).toBe(VIEWER);
      clearPolite();
      await userEvent.click(primary());
      expect(await politeText()).toBe(VIEWER);
      expect(onClick).not.toHaveBeenCalled();
    });

    it("the ▾ still opens; every item keeps its label, the reason its second line, and never runs", async () => {
      const { items } = await render({ allowed: false, reason: VIEWER });
      expect(toggle()).not.toHaveAttribute("aria-disabled");
      await userEvent.click(toggle());
      const item = page.getByRole("menuitem", { name: "Close 25 %" });
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(item).toHaveAccessibleDescription(VIEWER);
      await userEvent.keyboard("{Enter}");
      expect(items[0]?.onSelect).not.toHaveBeenCalled();
      expect(page.getByRole("menuitem", { name: "Close 50 %" })).toHaveAccessibleDescription(
        VIEWER,
      );
    });

    it("CMP-079 RbacGate gates it through disabledReason, which wins over a later leg's reason", async () => {
      const onClick = fn();
      await mount(
        <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
          <SplitButton
            allowed={false}
            reason={VIEWER}
            primary={{ label: "Close", onClick }}
            items={[]}
            menuLabel={MORE}
          />
        </RbacGate>,
      );
      expect(primary()).toHaveAccessibleDescription("Read-only while viewing as alex.");
      await userEvent.click(primary());
      expect(onClick).not.toHaveBeenCalled();
    });

    it("allowed, or a blank reason, is not gated", async () => {
      await render({ allowed: true, reason: VIEWER });
      expect(primary()).not.toHaveAttribute("aria-disabled");
      await render({ allowed: false, reason: "  " });
      expect(page.getAllByRole("button", { name: "Close" })[1]).not.toHaveAttribute(
        "aria-disabled",
      );
    });

    it("hands an item's re-shown reason to the host's region when it owns one", async () => {
      const announceReason = fn();
      await render({ allowed: false, reason: VIEWER, announceReason });
      await userEvent.click(toggle());
      await userEvent.keyboard("{Enter}");
      expect(announceReason).toHaveBeenCalledWith(VIEWER);
      expect(document.querySelector('[data-cmp="CMP-057"] [role="status"]')).toBeNull();
    });
  });

  describe("busy", () => {
    it("keeps its label (busyLabel), aria-busy and a leading glyph; a press does nothing; not T2", async () => {
      const { onClick } = await render({ busy: true });
      const busy = primary("Closing…");
      expect(busy).toHaveAttribute("aria-busy", "true");
      expect(busy).not.toHaveAttribute("aria-disabled");
      expect(busy).not.toHaveAttribute("aria-describedby");
      expect(busy.querySelector(".cv-button__label")).toHaveTextContent("Closing…");
      expect(busy.querySelector(".cv-button__icon svg")).not.toBeNull();
      await userEvent.click(busy);
      await userEvent.tab();
      expect(onClick).not.toHaveBeenCalled();
      expect(document.querySelector('[data-cmp="CMP-057"]')).toHaveAttribute("data-busy");
    });

    it("keeps the label itself when no busyLabel is given", async () => {
      await mount(
        <SplitButton
          busy
          primary={{ label: "Cancel", onClick: fn() }}
          items={[]}
          menuLabel="More"
        />,
      );
      expect(primary("Cancel")).toHaveAttribute("aria-busy", "true");
    });

    it("a gate wins over busy: the reason is what a user can act on", async () => {
      await render({ busy: true, allowed: false, reason: VIEWER });
      const gated = primary();
      expect(gated).toHaveAttribute("aria-disabled", "true");
      expect(gated).not.toHaveAttribute("aria-busy");
    });
  });

  it("passes variant and density to both halves", async () => {
    await render({ variant: "ghost", density: "comfortable" });
    for (const half of [primary(), toggle()]) {
      expect(half.dataset["variant"]).toBe("ghost");
      expect(half.dataset["density"]).toBe("comfortable");
    }
  });

  it("has no serious or critical axe violation: default, busy and gated", async () => {
    await render();
    await render({ busy: true });
    await render({ allowed: false, reason: VIEWER });
    expect(await seriousViolations(document.body)).toEqual([]);
  });
});

describe("SplitButton stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-057"]').length).toBeGreaterThan(0);
  });
});
