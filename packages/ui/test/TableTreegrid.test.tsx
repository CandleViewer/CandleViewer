// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Checkbox,
  Table,
  type TableColumn,
  type TableProps,
  type TableRowContext,
  type TableTreeRow,
} from "../src/components/index.js";
import * as stories from "../src/components/Table.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

// CMP-049's treegrid (E29-D04 §2.7; D04H A-6.2 to A-6.7; E29-D05 §5.1, §5.3, §6.2): the APG Treegrid over the grid
// mode, the focused row kept mounted outside the window (G-01), pinned columns (F-01) and the totals rowgroup.

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

interface Node {
  readonly id: string;
  readonly kind: "group" | "item" | "total";
  readonly label: string;
  readonly value: number;
}

const COLUMNS: readonly TableColumn<Node>[] = [
  { id: "name", header: "Name", cell: (n) => n.label },
  { id: "value", header: "Value", cell: (n) => n.value, numeric: "qty", precision: 0 },
  { id: "note", header: "Note", cell: (n) => (n.kind === "item" ? "held" : "") },
];
const CAPTION = "Book";

/** The model: `groups` groups of `per` items, flattened through the open ones, each entry's place from the model. */
function treeOf(
  groups: number,
  per: number,
  open: (group: string) => boolean,
): { readonly entries: Node[]; readonly places: Map<string, TableTreeRow> } {
  const entries: Node[] = [];
  const places = new Map<string, TableTreeRow>();
  for (let g = 0; g < groups; g += 1) {
    const id = `g${String(g)}`;
    const expanded = open(id);
    entries.push({ id, kind: "group", label: `Group ${String(g)}`, value: per });
    places.set(id, { level: 1, expanded, posinset: g + 1, setsize: groups });
    if (!expanded) continue;
    for (let i = 0; i < per; i += 1) {
      const item = `${id}-i${String(i)}`;
      entries.push({ id: item, kind: "item", label: `Item ${String(g)}.${String(i)}`, value: i });
      places.set(item, { level: 2, posinset: i + 1, setsize: per });
    }
  }
  return { entries, places };
}

const TOTAL: Node = { id: "total", kind: "total", label: "Total", value: 0 };

/** A ResizeObserver stand-in that keeps each observer's callback and targets; the shell's font is 16 px. */
function stubObservers(): { readonly fire: (target: Element | null, width: number) => void } {
  const observers: { readonly cb: ResizeObserverCallback; readonly targets: Element[] }[] = [];
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) =>
    el instanceof HTMLElement && el.dataset["cmp"] === "CMP-049"
      ? ({ fontSize: "16px" } as CSSStyleDeclaration)
      : real(el, pseudo),
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private readonly entry: { readonly cb: ResizeObserverCallback; readonly targets: Element[] };
      constructor(cb: ResizeObserverCallback) {
        this.entry = { cb, targets: [] };
        observers.push(this.entry);
      }
      observe(target: Element): void {
        this.entry.targets.push(target);
      }
      disconnect(): void {
        this.entry.targets.length = 0;
      }
    },
  );
  return {
    fire: (target, width) => {
      for (const { cb, targets } of observers)
        if (target !== null && targets.includes(target))
          cb(
            [{ target, contentRect: { width } } as unknown as ResizeObserverEntry],
            {} as ResizeObserver,
          );
    },
  };
}

interface Control {
  scrollTo: (offset: number) => void;
  reverse: () => void;
}

type HostProps = Partial<TableProps<Node>> & {
  readonly groups?: number;
  readonly per?: number;
  readonly open?: "all" | readonly string[];
  /** Draws a window of this many entries from `start`; with `keep`, the remembered row stays mounted (G-01). */
  readonly size?: number;
  readonly start?: number;
  readonly keep?: boolean;
  readonly totals?: boolean;
  readonly control?: Partial<Control>;
  readonly onToggle?: (id: string, expanded: boolean) => void;
};

/** A treegrid host: it owns the open groups, the window and the order, as every consumer does. */
function TreeHost({
  groups = 3,
  per = 3,
  open = [],
  size,
  start = 0,
  keep = false,
  totals = false,
  control,
  onToggle,
  ...props
}: HostProps): JSX.Element {
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set(open === "all" ? [] : open));
  const [offset, setOffset] = useState(start);
  const [reversed, setReversed] = useState(false);
  const isOpen = (id: string): boolean => open === "all" || opened.has(id);
  const model = treeOf(groups, per, isOpen);
  const entries = reversed ? [...model.entries].reverse() : model.entries;
  if (control !== undefined) {
    control.scrollTo = setOffset;
    control.reverse = () => setReversed((r) => !r);
  }
  const count = size ?? entries.length;
  const windowed = size === undefined ? {} : { rowWindow: { offset, total: entries.length } };
  return (
    <>
      <button type="button">Before</button>
      <Table<Node>
        treegrid
        caption={CAPTION}
        columns={COLUMNS}
        rows={entries.slice(offset, offset + count)}
        rowKey={(n) => n.id}
        treeRow={(n) => model.places.get(n.id) ?? { level: 1, posinset: 1, setsize: 1 }}
        onExpandedChange={(n, expanded) => {
          onToggle?.(n.id, expanded);
          const next = new Set(opened);
          if (expanded) next.add(n.id);
          else next.delete(n.id);
          setOpened(next);
        }}
        totalRows={totals ? [TOTAL] : undefined}
        {...windowed}
        {...(size === undefined
          ? {}
          : {
              onRowsInView: (first: number) =>
                setOffset(Math.min(Math.max(0, first - 2), Math.max(0, entries.length - count))),
            })}
        {...(keep
          ? {
              rowByKey: (key: string) => {
                const index = entries.findIndex((n) => n.id === key);
                const row = entries[index];
                return row === undefined ? undefined : { row, index };
              },
            }
          : {})}
        {...props}
      />
      <button type="button">After</button>
    </>
  );
}

const page = within(document.body);
const tree = (): HTMLElement => page.getByRole("treegrid", { name: CAPTION });
const rowOf = (index: number): HTMLElement => {
  const row = tree().querySelector<HTMLElement>(`tr[aria-rowindex="${String(index)}"]`);
  if (row === null) throw new Error(`no row ${String(index)}`);
  return row;
};
const cellAt = (r: number, c: number): HTMLElement => {
  const cell = tree().querySelector<HTMLElement>(
    `[data-cv-r="${String(r)}"][data-cv-c="${String(c)}"]`,
  );
  if (cell === null) throw new Error(`no cell ${String(r)},${String(c)}`);
  return cell;
};
const focusedRowIndex = (): string | null | undefined =>
  document.activeElement?.closest("tr")?.getAttribute("aria-rowindex");

describe("Table (CMP-049) treegrid: roles, levels and indices", () => {
  // The fixture is drawn whole, so the rows are read from the DOM directly: a role query per row would cost seconds.
  // Measured 3.4 s at a load of 23 on 8 cores; the 30 s ceiling covers a loaded runner, where the code lens saw the
  // grid's slowest tests near 18 s.
  it(
    "is a treegrid named by its caption, its rows' levels and set positions from the model on a 500-row fixture",
    { timeout: 30_000 },
    async () => {
      // 20 groups of 24 items: 500 rows, every one drawn (D02:142's fixture), one column so the DOM stays small.
      await mount(
        <TreeHost groups={20} per={24} open="all" totals columns={COLUMNS.slice(0, 1)} />,
      );
      const { entries, places } = treeOf(20, 24, () => true);
      expect(entries).toHaveLength(500);
      expect(tree()).toHaveAttribute("aria-rowcount", "502");
      expect(tree()).toHaveAttribute("aria-colcount", "1");
      const rows = [...tree().querySelectorAll<HTMLElement>("tr[aria-rowindex]")];
      // The header row, 500 body rows and the totals row; native rows, every cell a gridcell.
      expect(rows).toHaveLength(502);
      expect(rows.every((r) => r.tagName === "TR" && !r.hasAttribute("role"))).toBe(true);
      expect(
        tree().querySelectorAll('tbody:not(.cv-table__totals) td[role="gridcell"]'),
      ).toHaveLength(500);
      entries.forEach((entry, i) => {
        const row = rows[i + 1];
        const place = places.get(entry.id);
        expect(row?.getAttribute("aria-rowindex")).toBe(String(i + 2));
        expect(row?.getAttribute("aria-level")).toBe(String(place?.level));
        expect(row?.getAttribute("aria-posinset")).toBe(String(place?.posinset));
        expect(row?.getAttribute("aria-setsize")).toBe(String(place?.setsize));
        expect(row?.getAttribute("aria-expanded")).toBe(
          place?.expanded === undefined ? null : String(place.expanded),
        );
      });
      expect(rows.at(-1)?.closest("tbody")).toHaveClass("cv-table__totals");
    },
  );

  it("a window of the 500 rows: absolute indices, set sizes counting the undrawn rows, spacers for the rest", async () => {
    await mount(<TreeHost groups={20} per={24} open="all" size={40} start={251} totals />);
    expect(tree()).toHaveAttribute("aria-rowcount", "502");
    const drawn = within(tree()).getAllByRole("row").slice(1, -1);
    expect(drawn).toHaveLength(40);
    expect(drawn[0]).toHaveAttribute("aria-rowindex", "253");
    // Entry 251 is group 10's item 0 (each group is 25 rows): 1 of 24, whatever the window draws.
    expect(drawn[0]).toHaveAttribute("aria-level", "2");
    expect(drawn[0]).toHaveAttribute("aria-posinset", "1");
    expect(drawn[0]).toHaveAttribute("aria-setsize", "24");
    const spacers = tree().querySelectorAll<HTMLElement>(".cv-table__spacer");
    expect([...spacers].every((s) => s.getAttribute("aria-hidden") === "true")).toBe(true);
    const heights = [...spacers].map((s) => s.querySelector("td")?.style.blockSize ?? "");
    expect(heights).toEqual([
      "calc(251 * var(--size-row-height))",
      "calc(209 * var(--size-row-height))",
    ]);
  });

  it("a collapsed group shows no children: aria-expanded false, its set intact", async () => {
    await mount(<TreeHost />);
    const rows = within(tree()).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.getAttribute("aria-expanded"))).toEqual(["false", "false", "false"]);
    expect(rows.map((r) => r.getAttribute("aria-posinset"))).toEqual(["1", "2", "3"]);
    expect(rows.every((r) => r.getAttribute("aria-setsize") === "3")).toBe(true);
  });

  it("a plain grid carries none of the tree's attributes", async () => {
    const host = await mount(
      <Table<Node> grid caption="Plain" columns={COLUMNS} rows={[TOTAL]} rowKey={(n) => n.id} />,
    );
    const grid = within(host).getByRole("grid", { name: "Plain" });
    const row = within(grid).getAllByRole("row")[1];
    for (const name of ["aria-level", "aria-expanded", "aria-posinset", "aria-setsize"])
      expect(row).not.toHaveAttribute(name);
  });

  it("a treegrid does not stack, however narrow its shell (the reading taken pending OQ-19)", async () => {
    const observers = stubObservers();
    const host = await mount(<TreeHost open="all" />);
    const shell = host.querySelector<HTMLElement>('[data-cmp="CMP-049"]');
    await act(async () => observers.fire(shell, 10));
    expect(shell).not.toHaveAttribute("data-layout");
    expect(tree()).toBeInTheDocument();
  });

  it("multiselectable marks the treegrid when the host's rows carry their own selection", async () => {
    await mount(<TreeHost multiselectable />);
    expect(tree()).toHaveAttribute("aria-multiselectable", "true");
  });

  it("has no serious or critical axe violation, expanded with its totals", async () => {
    const host = await mount(<TreeHost open="all" totals />);
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("Table (CMP-049) treegrid: keys (APG Treegrid)", () => {
  it("→ on a collapsed row's first cell expands it, focus kept; → again moves to its first child", async () => {
    const onToggle = vi.fn();
    await mount(<TreeHost onToggle={onToggle} />);
    act(() => cellAt(2, 0).focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(onToggle).toHaveBeenCalledWith("g1", true);
    expect(rowOf(3)).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(cellAt(2, 0));
    await userEvent.keyboard("{ArrowRight}");
    expect(focusedRowIndex()).toBe("4");
    expect(document.activeElement?.closest("tr")).toHaveAttribute("aria-level", "2");
  });

  it("← on a child's first cell moves to its parent; ← there collapses it", async () => {
    const onToggle = vi.fn();
    await mount(<TreeHost open={["g0"]} onToggle={onToggle} />);
    act(() => cellAt(3, 0).focus());
    await userEvent.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(cellAt(1, 0));
    await userEvent.keyboard("{ArrowLeft}");
    expect(onToggle).toHaveBeenCalledWith("g0", false);
    expect(rowOf(2)).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(cellAt(1, 0));
  });

  it("past the tree cell, ← and → move by cell; → on a leaf's first cell moves right", async () => {
    const onToggle = vi.fn();
    await mount(<TreeHost open="all" onToggle={onToggle} />);
    act(() => cellAt(2, 0).focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(cellAt(2, 1));
    await userEvent.keyboard("{ArrowRight}{ArrowLeft}");
    expect(document.activeElement).toBe(cellAt(2, 1));
    // A group row's other cells move by cell too: no toggle from them.
    act(() => cellAt(1, 1).focus());
    await userEvent.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(cellAt(1, 0));
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("a click on a row's first cell opens and closes it; a click elsewhere, or on a leaf, does not", async () => {
    const onToggle = vi.fn();
    await mount(<TreeHost onToggle={onToggle} />);
    await userEvent.click(cellAt(1, 0));
    expect(onToggle).toHaveBeenLastCalledWith("g0", true);
    expect(rowOf(2)).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(cellAt(1, 0));
    expect(onToggle).toHaveBeenLastCalledWith("g0", false);
    await userEvent.click(cellAt(1, 1));
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("a click on a control inside the tree cell is the control's, not a toggle", async () => {
    const onToggle = vi.fn();
    const onPress = vi.fn();
    const renderRow = (n: Node, grid: TableRowContext): JSX.Element => (
      <tr {...grid.rowProps}>
        <td {...grid.cellProps(0, { interactive: true })}>
          <button type="button" onClick={onPress}>
            Press {n.label}
          </button>
        </td>
        <td {...grid.cellProps(1, { span: 2 })}>{n.value}</td>
      </tr>
    );
    await mount(<TreeHost onToggle={onToggle} renderRow={renderRow} />);
    await userEvent.click(page.getByRole("button", { name: "Press Group 0" }));
    expect(onPress).toHaveBeenCalled();
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("← on a top-level row that is collapsed stays; ↑ / ↓ never toggle", async () => {
    const onToggle = vi.fn();
    await mount(<TreeHost open={["g1"]} onToggle={onToggle} />);
    act(() => cellAt(1, 0).focus());
    await userEvent.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(cellAt(1, 0));
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowUp}");
    expect(document.activeElement).toBe(cellAt(2, 0));
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("Home / End move to the row's ends; Page Down / Page Up by a page (10 rows unlaid)", async () => {
    await mount(<TreeHost groups={3} per={8} open="all" />);
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{End}");
    expect(document.activeElement).toBe(cellAt(2, 2));
    await userEvent.keyboard("{Home}");
    expect(document.activeElement).toBe(cellAt(2, 0));
    await userEvent.keyboard("{PageDown}");
    expect(document.activeElement).toBe(cellAt(12, 0));
    await userEvent.keyboard("{PageUp}");
    expect(document.activeElement).toBe(cellAt(2, 0));
  });

  it("↓ from the last body row reaches the totals row; Ctrl+End its last cell; ↑ back", async () => {
    await mount(<TreeHost open="all" totals />);
    act(() => cellAt(12, 1).focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(focusedRowIndex()).toBe("14");
    await userEvent.keyboard("{ArrowUp}");
    expect(focusedRowIndex()).toBe("13");
    await userEvent.keyboard("{Control>}{End}{/Control}");
    expect(document.activeElement).toBe(cellAt(13, 2));
  });

  it("a parent above the window is asked of the host (posinset rows up) and focused once drawn", async () => {
    await mount(<TreeHost groups={3} per={20} open="all" size={10} start={15} keep />);
    // Entry 15 is group 0's item 14 (posinset 15): its parent is entry 0, above the window.
    act(() => cellAt(16, 0).focus());
    await userEvent.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(cellAt(1, 0));
    expect(rowOf(2)).toHaveAttribute("aria-level", "1");
  });

  it("selection is unchanged: the select column, Space on a body cell and aria-selected", async () => {
    const onRowSelect = vi.fn();
    await mount(<TreeHost open="all" onRowSelect={onRowSelect} selected={new Set(["g0"])} />);
    expect(tree()).toHaveAttribute("aria-multiselectable", "true");
    expect(rowOf(2)).toHaveAttribute("aria-selected", "true");
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard(" ");
    expect(onRowSelect).toHaveBeenCalledWith(new Set(["g0", "g0-i0"]));
  });

  it("a row whose rowActions are empty opens no context menu; a row with items opens its own", async () => {
    await mount(
      <TreeHost
        open="all"
        rowActions={(n) =>
          n.kind === "group" ? [] : [{ id: "act", label: "Act", onSelect: () => undefined }]
        }
      />,
    );
    act(() => cellAt(1, 0).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
    act(() => cellAt(2, 0).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    const menu = await page.findByRole("menu", { name: "Actions for Item 0.0" });
    expect(within(menu).getByRole("menuitem", { name: "Act" })).toHaveFocus();
  });
});

describe("Table (CMP-049) treegrid: focus identity and the kept row (E29-D05 §5.3, §5.4)", () => {
  it("a re-sort keeps focus on the same row and cell; its aria-rowindex follows the row", async () => {
    const control: Partial<Control> = {};
    await mount(<TreeHost open="all" control={control} />);
    act(() => cellAt(3, 1).focus());
    const cell = document.activeElement;
    expect(cell?.closest("tr")).toHaveAttribute("aria-rowindex", "4");
    act(() => control.reverse?.());
    expect(document.activeElement).toBe(cell);
    // 12 rows reversed: the third row is now the tenth.
    expect(cell?.closest("tr")).toHaveAttribute("aria-rowindex", "11");
    expect(tree().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    expect(cell).toHaveAttribute("tabindex", "0");
  });

  it("the focused row stays mounted when the window scrolls away: the one row outside it, focus kept (G-01)", async () => {
    const control: Partial<Control> = {};
    await mount(<TreeHost groups={4} per={24} open="all" size={20} keep control={control} />);
    act(() => cellAt(3, 1).focus());
    const cell = document.activeElement;
    act(() => control.scrollTo?.(60));
    expect(document.activeElement).toBe(cell);
    expect(cell?.isConnected).toBe(true);
    expect(cell?.closest("tr")).toHaveAttribute("aria-rowindex", "4");
    const rows = within(tree()).getAllByRole("row").slice(1);
    // The window's 20 rows and the kept one, first in the body: nothing else off-screen is drawn.
    expect(rows).toHaveLength(21);
    expect(rows[0]).toHaveAttribute("aria-rowindex", "4");
    expect(rows[1]).toHaveAttribute("aria-rowindex", "62");
    // The spacers still hold every undrawn row's height around it.
    const heights = [...tree().querySelectorAll<HTMLElement>(".cv-table__spacer td")].map(
      (td) => td.style.blockSize,
    );
    expect(heights).toEqual([
      "calc(2 * var(--size-row-height))",
      "calc(57 * var(--size-row-height))",
      "calc(20 * var(--size-row-height))",
    ]);
  });

  it("the kept row stays the one Tab stop: Tab out and back lands on it", async () => {
    const control: Partial<Control> = {};
    await mount(<TreeHost groups={4} per={24} open="all" size={20} keep control={control} />);
    act(() => cellAt(3, 1).focus());
    const cell = document.activeElement;
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
    act(() => control.scrollTo?.(60));
    expect(tree().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(cell);
  });

  it("the kept row goes once focus moves into the window", async () => {
    const control: Partial<Control> = {};
    await mount(<TreeHost groups={4} per={24} open="all" size={20} keep control={control} />);
    act(() => cellAt(3, 1).focus());
    act(() => control.scrollTo?.(60));
    expect(within(tree()).getAllByRole("row")).toHaveLength(22);
    act(() => cellAt(70, 1).focus());
    expect(tree().querySelector('tr[aria-rowindex="4"]')).toBeNull();
    expect(within(tree()).getAllByRole("row")).toHaveLength(21);
  });

  it("a re-sort that moves the focused row out of the window keeps it mounted and focused", async () => {
    const control: Partial<Control> = {};
    await mount(<TreeHost groups={4} per={24} open="all" size={20} keep control={control} />);
    act(() => cellAt(3, 1).focus());
    const cell = document.activeElement;
    act(() => control.reverse?.());
    expect(document.activeElement).toBe(cell);
    // 100 rows reversed: the third is the 98th, past the window of the first 20.
    expect(cell?.closest("tr")).toHaveAttribute("aria-rowindex", "99");
  });

  it("a kept row the host no longer finds is dropped; the Tab stop falls back to a drawn row", async () => {
    const control: Partial<Control> = {};
    let drop: () => void = () => undefined;
    const Dropping = (): JSX.Element => {
      const [gone, setGone] = useState(false);
      drop = () => setGone(true);
      return (
        <TreeHost
          groups={4}
          per={24}
          open="all"
          size={20}
          keep
          control={control}
          {...(gone ? { rowByKey: () => undefined } : {})}
        />
      );
    };
    await mount(<Dropping />);
    act(() => cellAt(3, 1).focus());
    act(() => control.scrollTo?.(60));
    expect(tree().querySelector('tr[aria-rowindex="4"]')).not.toBeNull();
    act(() => drop());
    expect(tree().querySelector('tr[aria-rowindex="4"]')).toBeNull();
    expect(tree().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
  });
});

describe("Table (CMP-049) treegrid: the totals rowgroup (D04H A-6.4, A-6.5)", () => {
  it("is a trailing rowgroup after the body, its row led by a rowheader, at the row index after the body", async () => {
    await mount(<TreeHost open="all" totals />);
    const groups = within(tree()).getAllByRole("rowgroup");
    expect(groups).toHaveLength(3);
    const totals = groups[2];
    expect(totals).toHaveClass("cv-table__totals");
    const header = within(totals ?? tree()).getByRole("rowheader", { name: "Total" });
    expect(header.tagName).toBe("TH");
    expect(header).toHaveAttribute("scope", "row");
    expect(header.closest("tr")).toHaveAttribute("aria-rowindex", "14");
    expect(header.closest("tr")).not.toHaveAttribute("aria-level");
    expect(header.closest("tr")?.style.getPropertyValue("--cv-table-after")).toBe("0");
  });

  it("a totals row has no select box, no selection and no row menu", async () => {
    const onRowSelect = vi.fn();
    const rowActions = vi.fn(() => [{ id: "a", label: "Act", onSelect: () => undefined }]);
    await mount(<TreeHost open="all" totals onRowSelect={onRowSelect} rowActions={rowActions} />);
    const totals = tree().querySelector(".cv-table__totals tr");
    expect(totals).not.toHaveAttribute("aria-selected");
    expect(totals?.querySelector("input")).toBeNull();
    expect(totals?.querySelector("button")).toBeNull();
    const cell = totals?.querySelector<HTMLElement>("[data-cv-c]");
    act(() => cell?.focus());
    await userEvent.keyboard(" ");
    expect(onRowSelect).not.toHaveBeenCalled();
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.queryByRole("menu")).toBeNull();
  });

  it("pins its rows to the region's bottom, and focused body cells scroll clear of them", async () => {
    const host = await mount(<TreeHost open="all" totals />);
    const shell = host.querySelector<HTMLElement>('[data-cmp="CMP-049"]');
    expect(shell?.style.getPropertyValue("--cv-table-totals")).toBe("1");
    const without = await mount(
      <Table<Node>
        grid
        caption="No totals"
        columns={COLUMNS}
        rows={[TOTAL]}
        rowKey={(n) => n.id}
      />,
    );
    expect(
      without
        .querySelector<HTMLElement>('[data-cmp="CMP-049"]')
        ?.style.getPropertyValue("--cv-table-totals"),
    ).toBe("");
  });

  it("a custom totals row takes the row contract: its rowheader, cells and the pin offset", async () => {
    const renderRow = (n: Node, grid: TableRowContext): JSX.Element => (
      <tr {...grid.rowProps}>
        <th {...grid.cellProps(0, { header: true, span: 2 })}>{n.label}</th>
        <td {...grid.cellProps(2)}>{n.kind}</td>
      </tr>
    );
    await mount(<TreeHost open="all" totals renderRow={renderRow} />);
    const row = tree().querySelector<HTMLElement>(".cv-table__totals tr");
    expect(row).toHaveClass("cv-table__total-row");
    expect(row).toHaveAttribute("aria-rowindex", "14");
    expect(row?.style.getPropertyValue("--cv-table-after")).toBe("0");
    expect(within(row ?? tree()).getByRole("rowheader", { name: "Total" })).toHaveAttribute(
      "colspan",
      "2",
    );
  });
});

describe("Table (CMP-049) pinned columns (E29-D04 §2.7; E29-D05 §6.2 F-01)", () => {
  const pins = (r: HTMLElement): (string | null)[] =>
    [...r.children].map((cell) =>
      cell.hasAttribute("data-pin-end") ? "end" : cell.getAttribute("data-pin-start"),
    );

  it("pins the leading columns, the select column counted, and the last one", async () => {
    await mount(
      <TreeHost
        open="all"
        onRowSelect={() => undefined}
        rowActions={() => []}
        stickyFirstColumn={2}
        stickyLastColumn
      />,
    );
    const [header, first] = within(tree()).getAllByRole("row");
    expect(pins(header ?? tree())).toEqual(["0", "1", null, null, "end"]);
    expect(pins(first ?? tree())).toEqual(["0", "1", null, null, "end"]);
  });

  it("true pins the first column alone; none pins nothing", async () => {
    const pinned = await mount(<TreeHost open="all" stickyFirstColumn />);
    const row = pinned.querySelectorAll<HTMLElement>("tbody tr[aria-rowindex]")[0];
    expect(pins(row ?? pinned)).toEqual(["0", null, null]);
    const plain = await mount(<TreeHost open="all" />);
    expect(plain.querySelector("[data-pin-start], [data-pin-end]")).toBeNull();
  });

  it("a merged cell is pinned only within the pinned columns", async () => {
    const renderRow = (n: Node, grid: TableRowContext): JSX.Element =>
      n.kind === "group" ? (
        <tr {...grid.rowProps}>
          <th {...grid.cellProps(0, { header: true, span: 3 })}>{n.label}</th>
        </tr>
      ) : (
        <tr {...grid.rowProps}>
          <th {...grid.cellProps(0, { header: true })}>{n.label}</th>
          <td {...grid.cellProps(1, { span: 2 })}>{n.value}</td>
        </tr>
      );
    await mount(<TreeHost open="all" renderRow={renderRow} stickyFirstColumn={2} />);
    const [, group, item] = within(tree()).getAllByRole("row");
    expect(pins(group ?? tree())).toEqual([null]);
    expect(pins(item ?? tree())).toEqual(["0", null]);
  });

  it("measures the pinned columns from the header row into the shell's offsets; a pin change or an unmount disconnects", async () => {
    let measure: () => void = () => undefined;
    const observed: Element[] = [];
    // Every observer CMP-049 makes, with its targets: the pinned columns' one watches the header cells.
    const observers: { readonly targets: Element[]; readonly disconnect: () => void }[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        readonly targets: Element[] = [];
        readonly disconnect = vi.fn();
        constructor(cb: () => void) {
          measure = cb;
          observers.push(this);
        }
        observe(target: Element): void {
          this.targets.push(target);
          observed.push(target);
        }
      },
    );
    /** How many times the pinned columns' observers let go of the header cells. */
    const pinDisconnects = (): number =>
      observers
        .filter((o) => o.targets.some((target) => target.tagName === "TH"))
        .reduce((sum, o) => sum + vi.mocked(o.disconnect).mock.calls.length, 0);
    const widths = new Map([
      ["Name", 96],
      ["Value", 80.5],
      ["Note", 64],
    ]);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      const width = widths.get(this.textContent?.trim() ?? "") ?? 0;
      return { width, height: 24, top: 0, left: 0, right: width, bottom: 24 } as DOMRect;
    });
    const Toggle = (): JSX.Element => {
      const [shown, setShown] = useState(true);
      const [pins, setPins] = useState(2);
      return (
        <>
          <button type="button" onClick={() => setPins(1)}>
            Fewer pins
          </button>
          <button type="button" onClick={() => setShown(false)}>
            Hide
          </button>
          {shown ? <TreeHost open="all" stickyFirstColumn={pins} stickyLastColumn /> : null}
        </>
      );
    };
    const host = await mount(<Toggle />);
    const shell = host.querySelector<HTMLElement>('[data-cmp="CMP-049"]');
    await act(async () => measure());
    expect(shell?.style.getPropertyValue("--cv-table-pin-1")).toBe("96px");
    expect(shell?.style.getPropertyValue("--cv-table-pin-start")).toBe("176.5px");
    expect(shell?.style.getPropertyValue("--cv-table-pin-end")).toBe("64px");
    expect(observed.some((cell) => cell.tagName === "TH")).toBe(true);
    expect(pinDisconnects()).toBe(0);
    // Fewer pins: the old observer lets its cells go before a new one measures the one pinned column.
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Fewer pins" }));
    });
    expect(pinDisconnects()).toBe(1);
    await act(async () => measure());
    expect(shell?.style.getPropertyValue("--cv-table-pin-start")).toBe("96px");
    expect(shell?.style.getPropertyValue("--cv-table-pin-1")).toBe("");
    await act(async () => {
      fireEvent.click(page.getByRole("button", { name: "Hide" }));
    });
    expect(pinDisconnects()).toBe(2);
    expect(shell?.style.getPropertyValue("--cv-table-pin-start")).toBe("");
  });

  it("a stacked table pins nothing", async () => {
    const observers = stubObservers();
    const host = await mount(
      <Table<Node>
        grid
        caption="Stacking"
        columns={COLUMNS}
        rows={[TOTAL]}
        rowKey={(n) => n.id}
        stickyFirstColumn
      />,
    );
    const shell = host.querySelector<HTMLElement>('[data-cmp="CMP-049"]');
    expect(host.querySelector("[data-pin-start]")).not.toBeNull();
    await act(async () => observers.fire(shell, 10));
    expect(shell).toHaveAttribute("data-layout", "stacked");
    expect(host.querySelector("[data-pin-start]")).toBeNull();
  });
});

describe("Table (CMP-049) custom cells: widget and interactive", () => {
  const renderRow = (n: Node, grid: TableRowContext): JSX.Element => (
    <tr {...grid.rowProps}>
      <td {...grid.cellProps(0, { widget: true })}>
        <Checkbox label={`Select ${n.label}`} tabIndex={grid.tabIndexOf(0)} />
      </td>
      <th {...grid.cellProps(1, { header: true })}>{n.label}</th>
      <td {...grid.cellProps(2, { interactive: true })}>
        <button type="button">Act on {n.label}</button>
      </td>
    </tr>
  );

  it("a widget cell takes no tabindex: its control carries the roving one and takes focus in its place", async () => {
    await mount(<TreeHost open="all" renderRow={renderRow} />);
    const box = page.getByRole("checkbox", { name: "Select Group 0" });
    const cell = box.closest("td");
    expect(cell).toHaveAttribute("data-cv-widget", "");
    expect(cell).not.toHaveAttribute("tabindex");
    expect(box).toHaveAttribute("tabindex", "0");
    await userEvent.tab();
    await userEvent.tab();
    expect(box).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(page.getByRole("checkbox", { name: "Select Item 0.0" })).toHaveFocus();
    expect(box).toHaveAttribute("tabindex", "-1");
  });

  it("an interactive cell's controls leave the Tab order; Enter moves in, Esc back", async () => {
    await mount(<TreeHost open="all" renderRow={renderRow} />);
    const button = page.getByRole("button", { name: "Act on Group 0" });
    const cell = button.closest("td");
    expect(cell).toHaveAttribute("data-cv-interactive", "");
    expect(button).toHaveAttribute("tabindex", "-1");
    act(() => cell?.focus());
    await userEvent.keyboard("{Enter}");
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(cell).toHaveFocus();
  });
});

describe("Table treegrid stories", () => {
  const all = composeStories(stories);
  const tree = [
    "Treegrid",
    "TreegridExpanded",
    "StickyLeadColumns",
    "TotalsRowgroup",
    "FocusedRowOutsideWindow",
    "ContrastLight",
    "ContrastHighContrast",
  ] as const;
  // The theme stories' plays wait for the preview's theme runtime, which a unit test does not load: mounted only.
  const themed = new Set<string>(["ContrastLight", "ContrastHighContrast"]);

  // Each story mounts, plays and runs axe: at most 3.0 s apiece at a load of 23 on 8 cores, near 18 s at 35 to 45 (the
  // code lens' run), so a measured 30 s ceiling, as the Table story test's own.
  it.each(tree)(
    "%s runs its play and has no serious or critical axe violation",
    { timeout: 30_000 },
    async (name) => {
      const Story = all[name];
      const canvasElement = await mount(<Story />);
      const play = stories[name].play as
        ((context: { canvasElement: HTMLElement }) => Promise<void>) | undefined;
      if (!themed.has(name)) await play?.({ canvasElement });
      const root = canvasElement.querySelector('[data-cmp="CMP-049"]');
      expect(root).not.toBeNull();
      expect(await seriousViolations(root ?? canvasElement)).toEqual([]);
    },
  );
});
