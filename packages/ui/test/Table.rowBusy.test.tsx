// @vitest-environment jsdom
/**
 * E42-S02 (#1023): CMP-049's `rowBusy` (E42-D03 U-7). A row whose write is in flight keeps its actions trigger
 * mounted, CMP-002 `busy`: named by the busy words, `aria-busy`, still the cell's focusable control, so focus that
 * was on it (or returns to it) stays; neither its menu button nor the context menu opens for that row.
 *
 * Beside E29-S01's treegrid (`15` CMP-049): the context menu drops a busy row's request at once, as it drops an empty
 * row's, so one open as the write starts closes and never opens by itself later; busy is the trigger's and the menus'
 * alone, so a busy row still opens and closes, and its parent and children keep their own; a kept row (G-01) keeps its
 * busy trigger mounted and focused; a totals row, which has no row menu, is never asked.
 */
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { beforeEach, describe, it, vi } from "vitest";
import {
  Table,
  type MenuItem,
  type TableColumn,
  type TableTreeRow,
} from "../src/components/index.js";
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

  it("a context menu open as its row's write starts closes, focus back on its cell, and never reopens by itself", async () => {
    await mount(<Host />);
    const cell = page.getByRole("gridcell", { name: "alex" });
    await act(async () => cell.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await page.findByRole("menu", { name: "Actions for alex" });
    // CMP-041 moves focus in from a passive effect, which can run after the menu is found.
    await waitFor(() => expect(menu.contains(document.activeElement)).toBe(true));
    // The toggle is clicked without a pointer press, which CMP-041 would read as an outside press that closes it.
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    expect(page.queryByRole("menu")).toBeNull();
    expect(cell).toHaveFocus();
    // The words go: the request was dropped as the write started, so nothing opens by itself.
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Toggle" }));
    });
    expect(page.queryByRole("menu")).toBeNull();
    expect(cell).toHaveFocus();
    // A new request opens it again.
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(await page.findByRole("menu", { name: "Actions for alex" })).toBeVisible();
  });
});

/** `teams` team rows (level 1), each holding `per` users (level 2) while open; every place from the model. */
function treeOf(
  teams: number,
  per: number,
  open: ReadonlySet<string>,
): { readonly entries: User[]; readonly places: Map<string, TableTreeRow> } {
  const entries: User[] = [];
  const places = new Map<string, TableTreeRow>();
  for (let t = 0; t < teams; t += 1) {
    const id = `t${String(t)}`;
    const expanded = open.has(id);
    entries.push({ id, name: `team ${String(t)}` });
    places.set(id, { level: 1, expanded, posinset: t + 1, setsize: teams });
    if (!expanded) continue;
    for (let u = 0; u < per; u += 1) {
      entries.push({ id: `${id}-u${String(u)}`, name: `user ${String(t)}.${String(u)}` });
      places.set(`${id}-u${String(u)}`, { level: 2, posinset: u + 1, setsize: per });
    }
  }
  return { entries, places };
}

const TOTAL: User = { id: "total", name: "All teams" };

interface TreeControl {
  setBusy: (id: string | undefined) => void;
  scrollTo: (offset: number) => void;
}

interface TreeHostProps {
  readonly teams?: number;
  readonly per?: number;
  readonly open?: readonly string[];
  /** Draws a window of this many entries; the remembered row stays mounted outside it (G-01). */
  readonly size?: number;
  readonly totals?: boolean;
  /** The host's busy words; by default the row `control.setBusy` names is "Disabling {name}…". */
  readonly busy?: (row: User) => string | undefined;
  readonly control?: Partial<TreeControl>;
  readonly onToggle?: (id: string, expanded: boolean) => void;
}

/** A treegrid of teams and their users: the host owns the open teams, the window and the write in flight. */
function TreeHost({
  teams = 2,
  per = 2,
  open = [],
  size,
  totals = false,
  busy,
  control,
  onToggle,
}: TreeHostProps): JSX.Element {
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set(open));
  const [busyId, setBusyId] = useState<string | undefined>(undefined);
  const [offset, setOffset] = useState(0);
  if (control !== undefined) {
    control.setBusy = setBusyId;
    control.scrollTo = setOffset;
  }
  const { entries, places } = treeOf(teams, per, opened);
  const windowed =
    size === undefined
      ? {}
      : {
          rowWindow: { offset, total: entries.length },
          rowByKey: (id: string) => {
            const index = entries.findIndex((e) => e.id === id);
            const row = entries[index];
            return row === undefined ? undefined : { row, index };
          },
        };
  return (
    <Table<User>
      treegrid
      caption="Teams"
      columns={COLUMNS}
      rows={size === undefined ? entries : entries.slice(offset, offset + size)}
      rowKey={(e) => e.id}
      rowLabel={(e) => e.name}
      treeRow={(e) => places.get(e.id) ?? { level: 1, posinset: 1, setsize: 1 }}
      onExpandedChange={(e, expanded) => {
        onToggle?.(e.id, expanded);
        const next = new Set(opened);
        if (expanded) next.add(e.id);
        else next.delete(e.id);
        setOpened(next);
      }}
      rowActions={actions}
      rowBusy={busy ?? ((e) => (e.id === busyId ? `Disabling ${e.name}…` : undefined))}
      totalRows={totals ? [TOTAL] : undefined}
      {...windowed}
    />
  );
}

const cellAt = (r: number, c: number): HTMLElement => {
  const cell = document.querySelector<HTMLElement>(
    `[data-cv-r="${String(r)}"][data-cv-c="${String(c)}"]`,
  );
  if (cell === null) throw new Error(`no cell ${String(r)},${String(c)}`);
  return cell;
};

describe("Table (CMP-049) rowBusy in a treegrid (E29-S01)", () => {
  it("a busy team row still opens and closes, by arrow or by a press on its first cell", async () => {
    const onToggle = vi.fn();
    const control: Partial<TreeControl> = {};
    await mount(<TreeHost control={control} onToggle={onToggle} />);
    act(() => control.setBusy?.("t0"));
    const trigger = page.getByRole("button", { name: "Disabling team 0…" });
    const first = cellAt(1, 0);
    act(() => first.focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(onToggle).toHaveBeenLastCalledWith("t0", true);
    expect(first.closest("tr")).toHaveAttribute("aria-expanded", "true");
    expect(first).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onToggle).toHaveBeenLastCalledWith("t0", false);
    expect(first.closest("tr")).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(first);
    expect(onToggle).toHaveBeenLastCalledWith("t0", true);
    // The tree was never the trigger's: it is busy throughout, the same element.
    expect(page.getByRole("button", { name: "Disabling team 0…" })).toBe(trigger);
    expect(trigger).toHaveAttribute("aria-busy", "true");
  });

  it("busy is the row's own: a team's users keep their triggers and menus, and a user's busy leaves its team", async () => {
    const control: Partial<TreeControl> = {};
    await mount(<TreeHost open={["t0"]} control={control} />);
    act(() => control.setBusy?.("t0-u1"));
    expect(page.getByRole("button", { name: "Disabling user 0.1…" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(page.getByRole("button", { name: "Actions for team 0" })).not.toHaveAttribute(
      "aria-busy",
    );
    act(() => control.setBusy?.("t0"));
    for (const name of ["Actions for user 0.0", "Actions for user 0.1"])
      expect(page.getByRole("button", { name })).not.toHaveAttribute("aria-busy");
    // Shift+F10 on the busy team opens nothing; on its first user, that user's own menu.
    act(() => cellAt(1, 0).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
    act(() => cellAt(2, 0).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(await page.findByRole("menu", { name: "Actions for user 0.0" })).toBeVisible();
  });

  it("a kept row (G-01) keeps its busy trigger mounted and focused as the window scrolls away", async () => {
    const control: Partial<TreeControl> = {};
    await mount(<TreeHost teams={1} per={40} open={["t0"]} size={10} control={control} />);
    const trigger = page.getByRole("button", { name: "Actions for user 0.1" });
    act(() => trigger.focus());
    act(() => control.setBusy?.("t0-u1"));
    expect(trigger).toHaveAccessibleName("Disabling user 0.1…");
    // Entries 20 to 29 drawn: user 0.1 (entry 2) is the one row kept outside the window.
    act(() => control.scrollTo?.(20));
    expect(trigger.isConnected).toBe(true);
    expect(trigger.closest("tr")).toHaveAttribute("aria-rowindex", "4");
    expect(trigger).toHaveAttribute("aria-busy", "true");
    expect(trigger).toHaveFocus();
    act(() => control.setBusy?.(undefined));
    expect(trigger).toHaveAccessibleName("Actions for user 0.1");
    expect(trigger).toHaveFocus();
  });

  it("a totals row, which has no row menu, is never asked for busy words", async () => {
    const busy = vi.fn<(row: User) => string | undefined>();
    await mount(<TreeHost open={["t0"]} totals busy={busy} />);
    const total = page.getByRole("rowheader", { name: "All teams" });
    act(() => total.focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
    // Every body row was asked (its trigger's words); the totals row never.
    const asked = new Set(busy.mock.calls.map(([row]) => row.id));
    expect([...asked].sort()).toEqual(["t0", "t0-u0", "t0-u1", "t1"]);
  });
});
