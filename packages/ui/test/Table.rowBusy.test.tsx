// @vitest-environment jsdom
/**
 * E42-S02 (#1023): CMP-049's `rowBusy` (E42-D03 U-7). A row whose write is in flight keeps its actions trigger
 * mounted, CMP-002 `busy`: named by the busy words, `aria-busy`, still the cell's focusable control, so focus that
 * was on it (or returns to it) stays; neither its menu button nor the context menu opens for that row.
 */
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { beforeEach, describe, it, vi } from "vitest";
import { Table, type MenuItem, type TableColumn } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

interface User {
  readonly id: string;
  readonly name: string;
}

const USERS: readonly User[] = [
  { id: "u1", name: "alex" },
  { id: "u2", name: "sam" },
];
const COLUMNS: readonly TableColumn<User>[] = [{ id: "name", header: "User", cell: (u) => u.name }];

const page = within(document.body);
const actions = (u: User): readonly MenuItem[] => [
  { id: "disable", label: `Disable ${u.name}…`, opensConfirm: true, onSelect: () => undefined },
];

/** A users grid whose host marks a row busy, as SCR-121 does while a row's write is in flight. */
function Host({ busyId: initial }: { readonly busyId?: string }): JSX.Element {
  const [busyId, setBusyId] = useState<string | undefined>(initial);
  return (
    <>
      <Table<User>
        caption="Users"
        columns={COLUMNS}
        rows={USERS}
        rowKey={(u) => u.id}
        rowActions={actions}
        rowLabel={(u) => u.name}
        rowBusy={(u) => (u.id === busyId ? `Disabling ${u.name}…` : undefined)}
      />
      <button type="button" onClick={() => setBusyId((b) => (b === undefined ? "u1" : undefined))}>
        Toggle
      </button>
    </>
  );
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("Table (CMP-049) rowBusy", () => {
  it("names the busy row's trigger by its busy words, aria-busy, still the cell's control", async () => {
    await mount(<Host busyId="u1" />);
    const busy = page.getByRole("button", { name: "Disabling alex…" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toBeEnabled();
    expect(busy.closest('[role="gridcell"]')).not.toBeNull();
    // The other row is as it was.
    const other = page.getByRole("button", { name: "Actions for sam" });
    expect(other).not.toHaveAttribute("aria-busy");
  });

  it("whitespace-only busy words are no busy state: the trigger stays idle and Shift+F10 opens the menu", async () => {
    await mount(
      <Table<User>
        caption="Users"
        columns={COLUMNS}
        rows={USERS}
        rowKey={(u) => u.id}
        rowActions={actions}
        rowLabel={(u) => u.name}
        rowBusy={() => "  "}
      />,
    );
    // The trigger trims its words, so it is idle; the context menu must read them the same way.
    expect(page.getByRole("button", { name: "Actions for alex" })).not.toHaveAttribute("aria-busy");
    await act(async () => page.getByRole("gridcell", { name: "alex" }).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(await page.findByRole("menu", { name: "Actions for alex" })).toBeVisible();
  });

  it("the busy trigger opens no menu, by press or by key", async () => {
    await mount(<Host busyId="u1" />);
    const busy = page.getByRole("button", { name: "Disabling alex…" });
    await userEvent.click(busy);
    expect(page.queryByRole("menu")).toBeNull();
    await act(async () => busy.focus());
    await userEvent.keyboard("{Enter}");
    expect(page.queryByRole("menu")).toBeNull();
    expect(busy).toHaveAttribute("aria-expanded", "false");
    // Another row's opens as before.
    await userEvent.click(page.getByRole("button", { name: "Actions for sam" }));
    expect(page.getByRole("menu")).toBeVisible();
  });

  it("stacked, where no table arrow moves a row, ↓ and ↑ on the busy trigger open nothing either", async () => {
    // Stacked, the table is no grid of rows (no roving focus), so ↑ / ↓ reach CMP-041's menu button itself and the
    // row menu's own refusal is all that keeps the menu shut. Stubbed as Table.test.tsx's stacked reflow does.
    class FakeObserver implements ResizeObserver {
      readonly observed: Element[] = [];
      constructor(readonly callback: ResizeObserverCallback) {
        all.push(this);
      }
      observe(target: Element): void {
        this.observed.push(target);
      }
      unobserve(): void {}
      disconnect(): void {}
    }
    const all: FakeObserver[] = [];
    vi.stubGlobal("ResizeObserver", FakeObserver);
    const real = window.getComputedStyle.bind(window);
    const style = vi
      .spyOn(window, "getComputedStyle")
      .mockImplementation((el, pseudo) =>
        el instanceof HTMLElement && el.dataset["cmp"] === "CMP-049"
          ? ({ fontSize: "16px" } as CSSStyleDeclaration)
          : real(el, pseudo),
      );
    try {
      const host = await mount(<Host busyId="u1" />);
      const shell = all
        .filter((o) => o.observed.some((t) => t.matches('[data-cmp="CMP-049"]')))
        .at(-1);
      if (shell === undefined) throw new Error("no shell observer");
      // The name column (8 em) and the actions column (3 em) at 16 px want 176 px: a 100 px shell stacks.
      const entries = [
        { target: shell.observed[0] as Element, contentRect: { width: 100 } as DOMRectReadOnly },
      ] as ResizeObserverEntry[];
      await act(async () => shell.callback(entries, shell));
      expect(host.querySelector('[data-cmp="CMP-049"]')).toHaveAttribute("data-layout", "stacked");
      const busy = page.getByRole("button", { name: "Disabling alex…" });
      await act(async () => busy.focus());
      await userEvent.keyboard("{ArrowDown}");
      expect(page.queryByRole("menu")).toBeNull();
      await userEvent.keyboard("{ArrowUp}");
      expect(page.queryByRole("menu")).toBeNull();
      expect(busy).toHaveAttribute("aria-expanded", "false");
      // The same key on an idle row's trigger opens its menu in this layout.
      await act(async () => page.getByRole("button", { name: "Actions for sam" }).focus());
      await userEvent.keyboard("{ArrowDown}");
      expect(await page.findByRole("menu", { name: "Actions for sam" })).toBeVisible();
    } finally {
      style.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("Shift+F10 on the busy row opens no context menu; on another row it does", async () => {
    await mount(<Host busyId="u1" />);
    const busyCell = page.getByRole("gridcell", { name: "alex" });
    await act(async () => busyCell.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
    await act(async () => page.getByRole("gridcell", { name: "sam" }).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.getByRole("menu", { name: "Actions for sam" })).toBeVisible();
  });

  it("a context-menu request made while the row is busy is dropped, so nothing opens when the words go", async () => {
    await mount(<Host busyId="u1" />);
    const cell = page.getByRole("gridcell", { name: "alex" });
    await act(async () => cell.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
    // The words go: the request made meanwhile was not kept.
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    expect(page.getByRole("button", { name: "Actions for alex" })).not.toHaveAttribute("aria-busy");
    expect(page.queryByRole("menu")).toBeNull();
    // A new request opens it.
    await act(async () => cell.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(await page.findByRole("menu", { name: "Actions for alex" })).toBeVisible();
  });

  it("a row menu open as its row's write starts closes, focus back on its trigger, and never reopens by itself", async () => {
    await mount(<Host />);
    const trigger = page.getByRole("button", { name: "Actions for alex" });
    await userEvent.click(trigger);
    const menu = await page.findByRole("menu", { name: "Actions for alex" });
    // CMP-041 moves focus in from a passive effect, which can run after the menu is found.
    await waitFor(() => expect(menu.contains(document.activeElement)).toBe(true));
    // The toggle is clicked without a pointer press, which CMP-041 would read as an outside press that closes it.
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    expect(page.queryByRole("menu")).toBeNull();
    expect(page.getByRole("button", { name: "Disabling alex…" })).toBe(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
    // The words go: the menu was closed as the write started, so nothing opens by itself.
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    expect(page.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("keeps the same trigger element through busy, so focus on it stays (U-7)", async () => {
    await mount(<Host />);
    const trigger = page.getByRole("button", { name: "Actions for alex" });
    await act(async () => trigger.focus());
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    const busy = page.getByRole("button", { name: "Disabling alex…" });
    expect(busy).toBe(trigger);
    expect(busy).toHaveFocus();
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    expect(page.getByRole("button", { name: "Actions for alex" })).toBe(trigger);
  });
});
