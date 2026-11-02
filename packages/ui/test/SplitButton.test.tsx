// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, expectTypeOf, it } from "vitest";
import {
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
/** A row's own reason (E29-D02 §10.3, §10.4): a Manager's Close under the kill switch, E39-D01's string. */
const FROZEN = "Frozen — the owner closes or releases";
/** A native-stop row's Cancel (E29-D02 §8.2): E32-D01 `sl.note`'s first sentence (PROPOSED as this reason). */
const SL_NOTE = "Every position keeps a native stop — you can move it, not delete it.";
/** `blotter.amend_in_flight` (PROPOSED, E29-D03): a native stop's edit while its TP/SL write is pending. */
const AMEND_IN_FLIGHT = "An amend is already in flight.";

interface Rendered {
  readonly onClick: ReturnType<typeof fn>;
  readonly items: readonly MenuItem[];
}

/** One split button, two ungated items unless `extra.items` says otherwise, plus a button after it (Tab's exit). */
async function render(extra: Partial<SplitButtonProps> = {}): Promise<Rendered> {
  const onClick = fn();
  const items = extra.items ?? [
    { id: "pct25", label: "Close 25 %", onSelect: fn() },
    { id: "pct50", label: "Close 50 %", onSelect: fn() },
  ];
  const props = {
    primary: { label: "Close", busyLabel: "Closing…", onClick },
    menuLabel: MORE,
    ...extra,
    items,
  } as SplitButtonProps; // each gate shape on purpose; the union itself is pinned by "the type-level contract" below
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
      await render({ allowed: false, reason: FROZEN });
      const gated = primary();
      expect(gated).toHaveAttribute("aria-disabled", "true");
      expect(gated).not.toHaveAttribute("disabled");
      expect(gated.tagName).toBe("BUTTON");
      expect(gated).toHaveAccessibleName("Close");
      await userEvent.tab();
      expect(gated).toHaveFocus();
    });

    it("links the reason by aria-describedby to a node in the DOM at mount", async () => {
      await render({ allowed: false, reason: FROZEN });
      const id = primary().getAttribute("aria-describedby") ?? "";
      expect(document.getElementById(id)).toHaveTextContent(FROZEN);
      expect(primary()).toHaveAccessibleDescription(FROZEN);
    });

    it("a press sends nothing and re-shows the reason once, politely, each time", async () => {
      const { onClick } = await render({ allowed: false, reason: FROZEN });
      clearPolite();
      expect(await politeText()).toBe("");
      await userEvent.tab();
      await userEvent.keyboard("{Enter}");
      expect(await politeText()).toBe(FROZEN);
      clearPolite();
      await userEvent.keyboard(" ");
      expect(await politeText()).toBe(FROZEN);
      clearPolite();
      await userEvent.click(primary());
      expect(await politeText()).toBe(FROZEN);
      expect(onClick).not.toHaveBeenCalled();
    });

    it("gates the primary alone: an item its host left ungated stays enabled and runs (C-2.6)", async () => {
      // A native-stop row's Cancel ▾: Cancel is T2, and the stop can still be moved (E29-D02 §8.2, §8.5).
      const onCancel = fn();
      const onEdit = fn();
      await mount(
        <SplitButton
          allowed={false}
          reason={SL_NOTE}
          primary={{ label: "Cancel", onClick: onCancel }}
          menuLabel={MORE}
          items={[
            { id: "trigger", label: "Edit trigger", onSelect: onEdit },
            { id: "chart", label: "Chart", onSelect: fn() },
          ]}
        />,
      );
      expect(primary("Cancel")).toHaveAttribute("aria-disabled", "true");
      expect(primary("Cancel")).toHaveAccessibleDescription(SL_NOTE);
      expect(toggle()).not.toHaveAttribute("aria-disabled");
      toggle().focus();
      await userEvent.keyboard("{ArrowDown}");
      expect(page.getByRole("menuitem", { name: "Edit trigger" })).toHaveFocus();
      for (const item of page.getAllByRole("menuitem")) {
        expect(item).not.toHaveAttribute("aria-disabled");
        expect(item).not.toHaveAccessibleDescription();
      }
      await userEvent.keyboard("{Enter}");
      expect(onEdit).toHaveBeenCalledTimes(1);
      expect(onCancel).not.toHaveBeenCalled();
    });

    it("each item keeps the reason its host computed, never the primary's, and a gated one never runs", async () => {
      const { items } = await render({
        allowed: false,
        reason: SL_NOTE,
        items: [
          { id: "trigger", label: "Edit trigger", onSelect: fn(), disabledReason: AMEND_IN_FLIGHT },
          { id: "chart", label: "Chart", onSelect: fn() },
        ],
      });
      await userEvent.click(toggle());
      const edit = page.getByRole("menuitem", { name: "Edit trigger" });
      expect(edit).toHaveAttribute("aria-disabled", "true");
      expect(edit).toHaveAccessibleDescription(AMEND_IN_FLIGHT);
      expect(page.getByRole("menuitem", { name: "Chart" })).not.toHaveAttribute("aria-disabled");
      await userEvent.keyboard("{Enter}");
      expect(items[0]?.onSelect).not.toHaveBeenCalled();
    });

    it("CMP-079 RbacGate gates it through disabledReason, which wins over a later leg's reason", async () => {
      const onClick = fn();
      await mount(
        <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
          <SplitButton
            allowed={false}
            reason={FROZEN}
            primary={{ label: "Close", onClick }}
            items={[{ id: "chart", label: "Chart", onSelect: fn() }]}
            menuLabel={MORE}
          />
        </RbacGate>,
      );
      expect(primary()).toHaveAccessibleDescription("Read-only while viewing as alex.");
      await userEvent.click(primary());
      expect(onClick).not.toHaveBeenCalled();
      // The role leg gates the primary alone, too: Chart is a read and never takes T2 (E29-D04 §4.2).
      await userEvent.click(toggle());
      expect(page.getByRole("menuitem", { name: "Chart" })).not.toHaveAttribute("aria-disabled");
    });

    it("allowed, or a blank reason, is not gated", async () => {
      await render({ allowed: true, reason: FROZEN });
      expect(primary()).not.toHaveAttribute("aria-disabled");
      await render({ allowed: false, reason: "  " });
      expect(page.getAllByRole("button", { name: "Close" })[1]).not.toHaveAttribute(
        "aria-disabled",
      );
    });

    it("hands an item's re-shown reason to the host's region when it owns one", async () => {
      const announceReason = fn();
      await render({
        announceReason,
        items: [{ id: "pct25", label: "Close 25 %", onSelect: fn(), disabledReason: FROZEN }],
      });
      await userEvent.click(toggle());
      await userEvent.keyboard("{Enter}");
      expect(announceReason).toHaveBeenCalledWith(FROZEN);
      expect(document.querySelector('[data-cmp="CMP-057"] [role="status"]')).toBeNull();
    });

    it("the type-level contract: a denial always carries its reason sentence (tsc checks this file)", () => {
      type Ungated = Pick<SplitButtonProps, "primary" | "items" | "menuLabel">;
      expectTypeOf<Ungated>().toExtend<SplitButtonProps>();
      expectTypeOf<Ungated & { allowed: true }>().toExtend<SplitButtonProps>();
      expectTypeOf<Ungated & { allowed: false; reason: string }>().toExtend<SplitButtonProps>();
      expectTypeOf<Ungated & { allowed: false }>().not.toExtend<SplitButtonProps>();
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
      await render({ busy: true, allowed: false, reason: FROZEN });
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
    await render({ allowed: false, reason: FROZEN });
    expect(await seriousViolations(document.body)).toEqual([]);
  });
});

describe("SplitButton stories", () => {
  const composed = composeStories(stories);

  it.each(Object.entries(composed))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-057"]').length).toBeGreaterThan(0);
  });

  it.each([
    ["T2Reason", MORE],
    ["T2ReasonMenu", MORE],
    ["T2ViaRbacGate", MORE],
    ["ContrastLight", "More close actions, SOLUSDT Long on Sub-2"],
    ["ContrastHighContrast", "More close actions, SOLUSDT Long on Sub-2"],
  ] as const)("%s keeps SL/TP… and Chart enabled under a gated primary", async (name, menu) => {
    const Story = composed[name];
    await mount(<Story />);
    await userEvent.click(page.getByRole("button", { name: menu }));
    expect(page.getByRole("menuitem", { name: "Close 25 %" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    for (const label of ["SL/TP…", "Chart"]) {
      const item = page.getByRole("menuitem", { name: label });
      expect(item).not.toHaveAttribute("aria-disabled");
      expect(item).not.toHaveAccessibleDescription();
    }
  });
});
