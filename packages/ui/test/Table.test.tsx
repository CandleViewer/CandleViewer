// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  EmptyState,
  GatedAnnounceProvider,
  Table,
  type MenuItem,
  type TableColumn,
  type TableProps,
  type TableRowContext,
  type TableSort,
} from "../src/components/index.js";
import { seriousViolations } from "./axe.js";
import { find, loadCss } from "./css-contract.js";
import { holdEnter } from "./heldEnter.js";
import * as stories from "../src/components/Table.stories.js";
import { mount } from "./theme/mount.js";
import { politeText } from "./theme/polite.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

interface User {
  readonly id: string;
  readonly name: string;
  readonly accounts: number;
  readonly pnl: number;
}

const USERS: readonly User[] = [
  { id: "u1", name: "alex", accounts: 3, pnl: 12.5 },
  { id: "u2", name: "sam", accounts: 1, pnl: -4 },
  { id: "u3", name: "kim", accounts: 2, pnl: 0 },
];

const COLUMNS: readonly TableColumn<User>[] = [
  { id: "name", header: "Name", cell: (u) => u.name, sortable: true },
  { id: "accounts", header: "Accounts", cell: (u) => u.accounts, numeric: "qty", precision: 0 },
  { id: "pnl", header: "PnL", cell: (u) => u.pnl, numeric: "pnl", sortable: true },
];

const CAPTION = "Users";

type HostProps = Partial<TableProps<User>> & { readonly initialSort?: TableSort };

const Host = ({ initialSort, ...props }: HostProps): JSX.Element => {
  const [sort, setSort] = useState<TableSort | undefined>(initialSort);
  return (
    <>
      <Table<User>
        caption={CAPTION}
        columns={COLUMNS}
        rows={USERS}
        rowKey={(u) => u.id}
        sort={sort}
        onSortChange={setSort}
        {...props}
      />
      <button type="button">After</button>
    </>
  );
};

const base = (props: Partial<TableProps<User>> = {}): JSX.Element => (
  <Table<User> caption={CAPTION} columns={COLUMNS} rows={USERS} rowKey={(u) => u.id} {...props} />
);

describe("Table (CMP-049), table mode", () => {
  it("is a native table named by its caption, with column headers and absolute row indices", async () => {
    const host = await mount(<Host />);
    const table = within(host).getByRole("table", { name: CAPTION });
    expect(table).toHaveAttribute("aria-rowcount", "4");
    const rows = within(table).getAllByRole("row");
    expect(rows.map((r) => r.getAttribute("aria-rowindex"))).toEqual(["1", "2", "3", "4"]);
    for (const header of within(table).getAllByRole("columnheader")) {
      expect(header).toHaveAttribute("scope", "col");
    }
    expect(host.querySelector('[data-cmp="CMP-049"]')).not.toBeNull();
  });

  it("renders numeric cells through NumericText, end-aligned, and pnl with its sign", async () => {
    const host = await mount(<Host />);
    const cell = within(host).getByText("+12.50").closest("td");
    expect(cell).toHaveAttribute("data-numeric", "");
    expect(cell?.querySelector('[data-cmp="CMP-020"]')).not.toBeNull();
    expect(within(host).getByText("3").closest("td")).toHaveAttribute("data-numeric", "");
    expect(within(host).getByRole("columnheader", { name: "PnL" })).toHaveAttribute(
      "data-numeric",
      "",
    );
  });

  // table.css gives an end-aligned header its start padding as room (E08-D07 §4.1, interim): its rules reach a header
  // marked `data-numeric` and the sort button inside it, and no start-aligned header.
  it("an end-aligned header is marked around its label or its sort button; a start-aligned one is not", async () => {
    const host = await mount(<Host />);
    const canvas = within(host);
    const pnl = canvas.getByRole("columnheader", { name: "PnL" });
    expect(pnl).toHaveClass("cv-table__header");
    expect(pnl).toHaveAttribute("data-numeric", "");
    expect(pnl.firstElementChild).toHaveClass("cv-table__sort");
    expect(pnl.querySelector(".cv-table__sort > .cv-table__label")).not.toBeNull();
    const accounts = canvas.getByRole("columnheader", { name: "Accounts" });
    expect(accounts).toHaveAttribute("data-numeric", "");
    expect(accounts.firstElementChild).toHaveClass("cv-table__label");
    const name = canvas.getByRole("columnheader", { name: "Name" });
    expect(name).toHaveClass("cv-table__header");
    expect(name).not.toHaveAttribute("data-numeric");
  });

  it("text cells ellipsize with the full text in the DOM", async () => {
    const long = "a user name long enough to overflow any column it is put in";
    const host = await mount(base({ rows: [{ id: "x", name: long, accounts: 1, pnl: 0 }] }));
    const text = within(host).getByText(long);
    expect(text).toHaveClass("cv-table__text");
    expect(text.textContent).toBe(long);
    expect(within(host).getByRole("cell", { name: long })).toBeInTheDocument();
  });

  it("marks sortable headers with aria-sort, none when unsorted, and none on plain headers", async () => {
    const host = await mount(<Host initialSort={{ columnId: "pnl", direction: "descending" }} />);
    const canvas = within(host);
    expect(canvas.getByRole("columnheader", { name: "PnL" })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    expect(canvas.getByRole("columnheader", { name: "Name" })).toHaveAttribute("aria-sort", "none");
    expect(canvas.getByRole("columnheader", { name: "Accounts" })).not.toHaveAttribute("aria-sort");
    expect(canvas.queryByRole("button", { name: "Accounts" })).toBeNull();
  });

  it("keyboard header-sort: Enter sorts ascending, then descending; Space too", async () => {
    const host = await mount(<Host />);
    const canvas = within(host);
    const button = canvas.getByRole("button", { name: "Name" });
    const header = canvas.getByRole("columnheader", { name: "Name" });
    await userEvent.tab();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(header).toHaveAttribute("aria-sort", "ascending");
    await userEvent.keyboard("{Enter}");
    expect(header).toHaveAttribute("aria-sort", "descending");
    await userEvent.keyboard(" ");
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(button).toHaveFocus();
  });

  it("a press on another column sorts it ascending", async () => {
    const onSortChange = vi.fn();
    const host = await mount(
      base({ sort: { columnId: "name", direction: "ascending" }, onSortChange }),
    );
    fireEvent.click(within(host).getByRole("button", { name: "PnL" }));
    expect(onSortChange).toHaveBeenCalledWith({ columnId: "pnl", direction: "ascending" });
  });

  it("a sortable column without onSortChange renders no button", async () => {
    const host = await mount(base());
    expect(within(host).queryByRole("button")).toBeNull();
    expect(within(host).getByRole("columnheader", { name: "Name" })).not.toHaveAttribute(
      "aria-sort",
    );
  });

  it("sortPending: the button keeps its name and aria-sort, is busy, shows a spinner, and a press changes nothing", async () => {
    const onSortChange = vi.fn();
    const host = await mount(
      base({
        sort: { columnId: "pnl", direction: "ascending" },
        sortPending: "pnl",
        onSortChange,
      }),
    );
    const button = within(host).getByRole("button", { name: "PnL" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).not.toBeDisabled();
    expect(button.querySelector('[data-cmp="CMP-014"]')).toHaveAttribute("aria-hidden", "true");
    expect(within(host).getByRole("columnheader", { name: "PnL" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    fireEvent.click(button);
    expect(onSortChange).not.toHaveBeenCalled();
  });

  it("puts no Tab stop in the body: the header buttons, then out", async () => {
    const host = await mount(<Host />);
    const canvas = within(host);
    await userEvent.tab();
    expect(canvas.getByRole("button", { name: "Name" })).toHaveFocus();
    await userEvent.tab();
    expect(canvas.getByRole("button", { name: "PnL" })).toHaveFocus();
    await userEvent.tab();
    expect(canvas.getByRole("button", { name: "After" })).toHaveFocus();
    expect(host.querySelectorAll("tbody [tabindex]")).toHaveLength(0);
  });

  it("the region takes a Tab stop named by the caption only when it scrolls", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(400);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    const host = await mount(<Host />);
    const region = within(host).getByRole("region", { name: CAPTION });
    await userEvent.tab();
    expect(region).toHaveFocus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "Name" })).toHaveFocus();
  });

  it("a region that does not scroll is no landmark and no Tab stop", async () => {
    const host = await mount(<Host />);
    expect(within(host).queryByRole("region")).toBeNull();
    expect(host.querySelector(".cv-table__region")).not.toHaveAttribute("tabindex");
  });

  it("emits data-density on the root, and none when absent (inherit)", async () => {
    const compact = await mount(base({ density: "compact" }));
    expect(compact.querySelector<HTMLElement>('[data-cmp="CMP-049"]')?.dataset["density"]).toBe(
      "compact",
    );
    const inherit = await mount(base());
    expect(inherit.querySelector('[data-cmp="CMP-049"]')).not.toHaveAttribute("data-density");
  });

  it("observes the region and its table, re-measures on resize, and disconnects on content change and unmount", async () => {
    interface Stub {
      readonly measure: () => void;
      readonly observed: Element[];
      disconnected: boolean;
    }
    const observers: Stub[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        private readonly stub: Stub;
        constructor(callback: () => void) {
          this.stub = { measure: callback, observed: [], disconnected: false };
          observers.push(this.stub);
        }
        observe(target: Element): void {
          this.stub.observed.push(target);
        }
        disconnect(): void {
          this.stub.disconnected = true;
        }
      },
    );
    let overflowing = false;
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(() =>
      overflowing ? 400 : 100,
    );
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    const Toggle = (): JSX.Element => {
      const [shown, setShown] = useState(true);
      const [rows, setRows] = useState<readonly User[]>(USERS);
      return (
        <>
          <button type="button" onClick={() => setRows(USERS.slice(0, 1))}>
            Fewer
          </button>
          <button type="button" onClick={() => setShown(false)}>
            Hide
          </button>
          {shown ? base({ rows }) : null}
        </>
      );
    };
    const host = await mount(<Toggle />);
    const region = host.querySelector(".cv-table__region");
    // The reflow's own observer (on the shell) is covered by the reflow tests; these watch the region.
    const shell = host.querySelector('[data-cmp="CMP-049"]');
    const scrollers = (): Stub[] => observers.filter((o) => !o.observed.some((t) => t === shell));
    const first = scrollers()[0];
    expect(scrollers()).toHaveLength(1);
    expect(first?.observed).toEqual([region, host.querySelector("table")]);
    expect(within(host).queryByRole("region")).toBeNull();

    overflowing = true;
    await act(async () => first?.measure());
    expect(within(host).getByRole("region", { name: CAPTION })).toBe(region);

    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Fewer" }));
    });
    expect(first?.disconnected).toBe(true);
    expect(scrollers()).toHaveLength(2);
    const second = scrollers()[1];
    expect(second?.disconnected).toBe(false);

    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Hide" }));
    });
    expect(second?.disconnected).toBe(true);
  });

  it("forces no synchronous reflow on mount when ResizeObserver exists: its first callback measures", async () => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe(): void {}
        disconnect(): void {}
      },
    );
    const read = vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(100);
    await mount(<Host />);
    expect(read).not.toHaveBeenCalled();
  });

  it("captionHidden hides the caption visually and still names the table", async () => {
    const host = await mount(base({ captionHidden: true }));
    expect(within(host).getByText(CAPTION)).toHaveClass("cv-visually-hidden");
    expect(within(host).getByRole("table", { name: CAPTION })).toBeInTheDocument();
  });
});

describe("Table (CMP-049) stacked reflow", () => {
  interface Reflow {
    /** Fires the shell's observer as a resize to `width` px of content box. */
    readonly resize: (width: number) => Promise<void>;
    /** Fires it as the 1 em probe resizing (a font-size change at the same width). */
    readonly rescale: () => Promise<void>;
    readonly observed: Element[];
    readonly disconnected: () => boolean;
  }

  /** Stubs ResizeObserver and the shell's computed font size; returns the shell observer's controls. */
  const stub = (fontPx: { value: number }): (() => Reflow) => {
    class FakeObserver implements ResizeObserver {
      readonly observed: Element[] = [];
      disconnected = false;
      constructor(readonly callback: ResizeObserverCallback) {
        all.push(this);
      }
      observe(target: Element): void {
        this.observed.push(target);
      }
      unobserve(): void {}
      disconnect(): void {
        this.disconnected = true;
      }
    }
    const all: FakeObserver[] = [];
    vi.stubGlobal("ResizeObserver", FakeObserver);
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) =>
      el instanceof HTMLElement && el.dataset["cmp"] === "CMP-049"
        ? ({ fontSize: `${fontPx.value}px` } as CSSStyleDeclaration)
        : real(el, pseudo),
    );
    return () => {
      const o = all.filter((x) => x.observed.some((t) => t.matches('[data-cmp="CMP-049"]'))).at(-1);
      if (o === undefined) throw new Error("no shell observer");
      const fire = async (entries: Partial<ResizeObserverEntry>[]): Promise<void> => {
        await act(async () => o.callback(entries as ResizeObserverEntry[], o));
      };
      const shell = o.observed[0] as Element;
      return {
        resize: (width) => fire([{ target: shell, contentRect: { width } as DOMRectReadOnly }]),
        rescale: () =>
          fire([
            { target: o.observed[1] as Element, contentRect: { width: 0 } as DOMRectReadOnly },
          ]),
        observed: o.observed,
        disconnected: () => o.disconnected,
      };
    };
  };

  const layout = (host: HTMLElement): string | undefined =>
    host.querySelector<HTMLElement>('[data-cmp="CMP-049"]')?.dataset["layout"];

  // COLUMNS give no minWidthEm: 3 x the default 8 em = 24 em; at 16 px that is 384 px.
  it("stacks below the summed default minimums times the shell's font size, and not at or above it", async () => {
    const fontPx = { value: 16 };
    const observer = stub(fontPx);
    const host = await mount(base());
    const ro = observer();
    expect(ro.observed).toEqual([
      host.querySelector('[data-cmp="CMP-049"]'),
      host.querySelector(".cv-table__em-probe"),
    ]);
    expect(layout(host)).toBeUndefined();
    await ro.resize(384);
    expect(layout(host)).toBeUndefined();
    await ro.resize(383.5);
    expect(layout(host)).toBe("stacked");
  });

  it("sums each column's minWidthEm, defaulting the ones without", async () => {
    const fontPx = { value: 10 };
    const observer = stub(fontPx);
    const columns: readonly TableColumn<User>[] = [
      { ...COLUMNS[0], minWidthEm: 20 } as TableColumn<User>,
      COLUMNS[1] as TableColumn<User>,
      { ...COLUMNS[2], minWidthEm: 12 } as TableColumn<User>,
    ];
    const host = await mount(base({ columns }));
    const ro = observer();
    await ro.resize(399); // (20 + 8 + 12) em x 10 px = 400 px
    expect(layout(host)).toBe("stacked");
    await ro.resize(400);
    expect(layout(host)).toBeUndefined();
  });

  it("tracks a font-size change at the same width (200 % zoom) through the em probe", async () => {
    const fontPx = { value: 16 };
    const observer = stub(fontPx);
    const host = await mount(base());
    const ro = observer();
    await ro.resize(600);
    expect(layout(host)).toBeUndefined();
    fontPx.value = 32; // 24 em = 768 px > 600
    await ro.rescale();
    expect(layout(host)).toBe("stacked");
    fontPx.value = 16;
    await ro.rescale();
    expect(layout(host)).toBeUndefined();
  });

  it("switches back to the table layout, dropping the explicit roles and the header labels", async () => {
    const observer = stub({ value: 16 });
    const host = await mount(base());
    const ro = observer();
    await ro.resize(200);
    expect(layout(host)).toBe("stacked");
    expect(host.querySelectorAll(".cv-table__cell-label").length).toBeGreaterThan(0);
    await ro.resize(800);
    expect(layout(host)).toBeUndefined();
    expect(host.querySelector("[role]:not([role=status])")).toBeNull();
    expect(host.querySelector(".cv-table__cell-label")).toBeNull();
  });

  it("a zero width (not laid out) keeps the last layout", async () => {
    const observer = stub({ value: 16 });
    const host = await mount(base());
    const ro = observer();
    await ro.resize(200);
    await ro.resize(0);
    expect(layout(host)).toBe("stacked");
  });

  it("keeps explicit table roles while stacked: table, rowgroups, rows, column headers and cells", async () => {
    const observer = stub({ value: 16 });
    const host = await mount(
      base({ sort: { columnId: "pnl", direction: "ascending" }, onSortChange: () => undefined }),
    );
    await observer().resize(200);
    const table = within(host).getByRole("table", { name: CAPTION });
    expect(table).toHaveAttribute("role", "table");
    expect(host.querySelectorAll("thead[role=rowgroup], tbody[role=rowgroup]")).toHaveLength(2);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    for (const row of rows) expect(row).toHaveAttribute("role", "row");
    expect(rows.map((r) => r.getAttribute("aria-rowindex"))).toEqual(["1", "2", "3", "4"]);
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.getAttribute("role"))).toEqual(Array(3).fill("columnheader"));
    expect(within(table).getByRole("columnheader", { name: "PnL" })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(within(table).getAllByRole("cell")).toHaveLength(9);
  });

  it("stacked cells: the first is the heading line; the others carry a visible, AT-hidden header label before the value", async () => {
    const observer = stub({ value: 16 });
    const host = await mount(base());
    await observer().resize(200);
    const row = within(host).getAllByRole("row")[1] as HTMLElement;
    const [first, accounts, pnl] = within(row).getAllByRole("cell");
    expect(first?.querySelector(".cv-table__cell-label")).toBeNull();
    expect(first).toHaveTextContent("alex");
    const label = accounts?.querySelector(".cv-table__cell-label");
    expect(label).toHaveTextContent("Accounts");
    expect(label).toHaveAttribute("aria-hidden", "true");
    expect(label?.nextElementSibling).toHaveTextContent("3");
    // The accessible name is the value alone: the header comes from the columnheader, once.
    expect(within(row).getByRole("cell", { name: "+12.50" })).toBe(pnl);
  });

  it("a stacked grid degrades to a table: table roles, no roving tabindex, each control a Tab stop in order", async () => {
    const observer = stub({ value: 16 });
    const host = await mount(
      <Table<User>
        caption={CAPTION}
        columns={COLUMNS}
        rows={USERS.slice(0, 1)}
        rowKey={(u) => u.id}
        selected={new Set(["u1"])}
        onRowSelect={() => undefined}
        rowActions={() => [{ id: "open", label: "Open", onSelect: () => undefined }]}
      />,
    );
    // 3 x 8 em + 2 control columns x 3 em = 30 em = 480 px at 16 px.
    await observer().resize(479);
    expect(layout(host)).toBe("stacked");
    const canvas = within(host);
    expect(canvas.queryByRole("grid")).toBeNull();
    const table = canvas.getByRole("table", { name: CAPTION });
    expect(table).toHaveAttribute("role", "table");
    expect(within(table).getAllByRole("cell")).toHaveLength(5);
    expect(within(table).getAllByRole("row")[1]).toHaveAttribute("aria-selected", "true");
    expect(host.querySelectorAll('td[tabindex], th[tabindex], [tabindex="-1"]')).toHaveLength(0);
    await userEvent.tab();
    expect(canvas.getByRole("checkbox", { name: "Select all rows" })).toHaveFocus();
    await userEvent.tab();
    expect(canvas.getByRole("checkbox", { name: "Select alex" })).toHaveFocus();
    await userEvent.tab();
    expect(canvas.getByRole("button", { name: "Actions for alex" })).toHaveFocus();
    // The heading line is the first data cell, not the select cell.
    expect(host.querySelector("td[data-heading]")).toHaveTextContent("alex");
    await observer().resize(480);
    expect(layout(host)).toBeUndefined();
    expect(canvas.getByRole("grid", { name: CAPTION })).toBeInTheDocument();
  });

  it("a stacked grid gives an interactive cell's controls back their Tab stops", async () => {
    const observer = stub({ value: 16 });
    const host = await mount(
      base({
        columns: [
          ...COLUMNS,
          {
            id: "note",
            header: "Note",
            interactive: true,
            cell: (u) => <input aria-label={`Note for ${u.name}`} />,
          },
        ],
      }),
    );
    const input = within(host).getByRole("textbox", { name: "Note for alex" });
    expect(input).toHaveAttribute("tabindex", "-1");
    await observer().resize(100);
    expect(input).not.toHaveAttribute("tabindex");
    await observer().resize(1000);
    expect(input).toHaveAttribute("tabindex", "-1");
  });

  it("stays a table without ResizeObserver", async () => {
    vi.stubGlobal("ResizeObserver", undefined);
    const host = await mount(base());
    expect(layout(host)).toBeUndefined();
  });

  it("disconnects its observer on unmount, and re-observes when the threshold changes", async () => {
    const observer = stub({ value: 16 });
    const Switch = (): JSX.Element => {
      const [shown, setShown] = useState(true);
      const [wide, setWide] = useState(false);
      const columns = wide ? COLUMNS.map((c) => ({ ...c, minWidthEm: 30 })) : COLUMNS;
      return (
        <>
          <button type="button" onClick={() => setWide(true)}>
            Wide
          </button>
          <button type="button" onClick={() => setShown(false)}>
            Hide
          </button>
          {shown ? base({ columns: columns as readonly TableColumn<User>[] }) : null}
        </>
      );
    };
    const host = await mount(<Switch />);
    const first = observer();
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Wide" }));
    });
    expect(first.disconnected()).toBe(true);
    const second = observer();
    await second.resize(800); // 90 em x 16 px = 1440 px
    expect(layout(host)).toBe("stacked");
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Hide" }));
    });
    expect(second.disconnected()).toBe(true);
  });

  it('reflow "grid": stacked, a grid keeps role grid, its gridcells and one Tab stop (E08-D07 D30 cards)', async () => {
    const observer = stub({ value: 16 });
    const host = await mount(base({ grid: true, reflow: "grid" }));
    await observer().resize(300);
    expect(layout(host)).toBe("stacked");
    const grid = within(host).getByRole("grid", { name: CAPTION });
    expect(within(grid).getAllByRole("gridcell")).toHaveLength(9);
    expect(grid.querySelectorAll('[tabindex="0"]')).toHaveLength(1);
  });

  it('reflow "grid": stacked, the arrows still move by cell', async () => {
    const observer = stub({ value: 16 });
    const host = await mount(base({ grid: true, reflow: "grid" }));
    await observer().resize(300);
    const first = within(host).getAllByRole("gridcell")[0] as HTMLElement;
    act(() => first.focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toHaveTextContent("sam");
  });
});

describe("Table (CMP-049) states", () => {
  it("loading: the header row kept, CMP-015 skeleton rows hidden from AT, aria-busy and the loading words", async () => {
    const host = await mount(base({ loading: true, loadingText: "Loading users…" }));
    const table = within(host).getByRole("table", { name: CAPTION });
    expect(table).toHaveAttribute("aria-busy", "true");
    expect(table).toHaveAttribute("aria-rowcount", "-1");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    expect(host.querySelectorAll('tbody [data-cmp="CMP-015"]').length).toBeGreaterThan(0);
    expect(within(table).getAllByRole("row")).toHaveLength(1);
    expect(within(host).getByText("Loading users…")).toBeVisible();
    expect(within(host).queryByText("alex")).toBeNull();
  });

  it("empty: CMP-026 across every column, the header row kept", async () => {
    const host = await mount(base({ rows: [] }));
    const cell = host.querySelector("tbody td");
    expect(cell).toHaveAttribute("colspan", "3");
    expect(cell?.querySelector('[data-cmp="CMP-026"]')).not.toBeNull();
    expect(within(host).getByRole("heading", { name: "No rows to show" })).toBeInTheDocument();
    expect(within(host).getAllByRole("columnheader")).toHaveLength(3);
  });

  it("filtered-empty: the host's CMP-026 filtered-empty with Clear filters", async () => {
    const clear = vi.fn();
    const host = await mount(
      base({
        rows: [],
        emptyState: (
          <EmptyState
            variant="filtered-empty"
            title="No rows match: role Viewer"
            cta={{ label: "Clear filters", onClick: clear }}
          />
        ),
      }),
    );
    expect(host.querySelector('[data-cmp="CMP-026"]')).toHaveAttribute(
      "data-variant",
      "filtered-empty",
    );
    fireEvent.click(within(host).getByRole("button", { name: "Clear filters" }));
    expect(clear).toHaveBeenCalledOnce();
  });

  it("error: CMP-027 with Retry, no second live region, the message said once by the table's region", async () => {
    const onRetry = vi.fn();
    const message = "Couldn't load users — store unavailable.";
    const host = await mount(base({ rows: [], error: { message, onRetry } }));
    expect(host.querySelector('tbody [data-cmp="CMP-027"]')).not.toBeNull();
    const regions = within(host).getAllByRole("status");
    expect(regions).toHaveLength(1);
    expect(regions[0]).toHaveTextContent(message);
    expect(regions[0]).toHaveAttribute("aria-live", "polite");
    fireEvent.click(within(host).getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("loading wins over a stale error while a Retry runs", async () => {
    const host = await mount(
      base({ loading: true, error: { message: "Failed", onRetry: () => undefined } }),
    );
    expect(host.querySelector('[data-cmp="CMP-027"]')).toBeNull();
    expect(host.querySelector('[data-cmp="CMP-049"]')).toHaveAttribute("data-state", "loading");
  });
});

describe("Table (CMP-049) live region", () => {
  const Loader = (): JSX.Element => {
    const [loading, setLoading] = useState(true);
    return (
      <>
        <button type="button" onClick={() => setLoading(false)}>
          Done
        </button>
        {base({ loading, rows: loading ? [] : USERS })}
      </>
    );
  };

  it("is silent on the first render of a populated table", async () => {
    const host = await mount(<Host initialSort={{ columnId: "name", direction: "ascending" }} />);
    expect(within(host).getByRole("status")).toHaveTextContent("");
  });

  it("says a settled sort once", async () => {
    const host = await mount(<Host />);
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "PnL" }));
    });
    expect(within(host).getByRole("status")).toHaveTextContent("Sorted by PnL, ascending");
  });

  it("waits for a pending sort to settle before saying it", async () => {
    const Pending = (): JSX.Element => {
      const [pending, setPending] = useState<string | undefined>("pnl");
      return (
        <>
          <button type="button" onClick={() => setPending(undefined)}>
            Settle
          </button>
          {base({ sort: { columnId: "pnl", direction: "descending" }, sortPending: pending })}
        </>
      );
    };
    const host = await mount(<Pending />);
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent("");
    fireEvent.click(within(host).getByRole("button", { name: "Settle" }));
    await act(async () => undefined);
    expect(status).toHaveTextContent("Sorted by PnL, descending");
  });

  /** Records every text the status region takes, so an identical result said again shows as a change. */
  const record = (status: HTMLElement): string[] => {
    const seen: string[] = [];
    new MutationObserver(() => seen.push(status.textContent ?? "")).observe(status, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    return seen;
  };
  const flush = async (): Promise<void> => {
    await act(async () => undefined);
  };

  it("clears as a reload starts, so the same row count is said again", async () => {
    const Reloader = (): JSX.Element => {
      const [loading, setLoading] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setLoading((l) => !l)}>
            Toggle
          </button>
          {base({ loading })}
        </>
      );
    };
    const host = await mount(<Reloader />);
    const status = within(host).getByRole("status");
    const toggle = within(host).getByRole("button", { name: "Toggle" });
    for (let i = 0; i < 2; i += 1) {
      fireEvent.click(toggle);
      await flush();
      expect(status).toHaveTextContent("");
      fireEvent.click(toggle);
      await flush();
      expect(status).toHaveTextContent("3 rows");
    }
    const seen = record(status);
    fireEvent.click(toggle);
    await flush();
    fireEvent.click(toggle);
    await flush();
    expect(seen).toEqual(["", "3 rows"]);
  });

  it("a Retry that fails with the same message says it again (Retry with a load)", async () => {
    const message = "Couldn't load users — store unavailable.";
    const Failing = (): JSX.Element => {
      const [loading, setLoading] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setLoading(false)}>
            Fail
          </button>
          {base({ rows: [], loading, error: { message, onRetry: () => setLoading(true) } })}
        </>
      );
    };
    const host = await mount(<Failing />);
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent(message);
    const seen = record(status);
    fireEvent.click(within(host).getByRole("button", { name: "Retry" }));
    await flush();
    expect(status).toHaveTextContent("");
    fireEvent.click(within(host).getByRole("button", { name: "Fail" }));
    await flush();
    expect(status).toHaveTextContent(message);
    expect(seen).toEqual(["", message]);
  });

  it("a Retry that fails with the same message says it again (no load between)", async () => {
    const message = "Couldn't load users — store unavailable.";
    const Failing = (): JSX.Element => {
      const [attempt, setAttempt] = useState(0);
      return (
        <>
          <span data-testid="attempt">{attempt}</span>
          {base({ rows: [], error: { message, onRetry: () => setAttempt((n) => n + 1) } })}
        </>
      );
    };
    const host = await mount(<Failing />);
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent(message);
    const seen = record(status);
    fireEvent.click(within(host).getByRole("button", { name: "Retry" }));
    await flush();
    expect(within(host).getByTestId("attempt")).toHaveTextContent("1");
    expect(status).toHaveTextContent(message);
    expect(seen).toContain("");
    expect(seen.at(-1)).toBe(message);
  });

  it("an error kept across unrelated re-renders is said once", async () => {
    const message = "Couldn't load users — store unavailable.";
    const Rerender = (): JSX.Element => {
      const [n, setN] = useState(0);
      return (
        <>
          <button type="button" onClick={() => setN(n + 1)}>
            Rerender {n}
          </button>
          {base({ rows: [], error: { message, onRetry: () => undefined } })}
        </>
      );
    };
    const host = await mount(<Rerender />);
    const status = within(host).getByRole("status");
    const seen = record(status);
    fireEvent.click(within(host).getByRole("button", { name: /Rerender/ }));
    await flush();
    expect(status).toHaveTextContent(message);
    expect(seen).toEqual([]);
  });

  it("does not re-say a sort when inline columns and sort objects are re-created", async () => {
    const Inline = (): JSX.Element => {
      const [n, setN] = useState(0);
      return (
        <>
          <button type="button" onClick={() => setN(n + 1)}>
            Rerender {n}
          </button>
          <Table<User>
            caption={CAPTION}
            columns={COLUMNS.map((c) => ({ ...c }))}
            rows={USERS}
            rowKey={(u) => u.id}
            sort={{ columnId: "pnl", direction: n === 0 ? "ascending" : "descending" }}
            onSortChange={() => undefined}
          />
        </>
      );
    };
    const host = await mount(<Inline />);
    const status = within(host).getByRole("status");
    const button = within(host).getByRole("button", { name: /Rerender/ });
    fireEvent.click(button);
    await flush();
    expect(status).toHaveTextContent("Sorted by PnL, descending");
    const seen = record(status);
    fireEvent.click(button);
    await flush();
    fireEvent.click(button);
    await flush();
    expect(seen).toEqual([]);
  });

  it("clears while a sort is pending", async () => {
    const Pending = (): JSX.Element => {
      const [pending, setPending] = useState<string | undefined>(undefined);
      const [loading, setLoading] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setLoading(false)}>
            Done
          </button>
          <button type="button" onClick={() => setPending("pnl")}>
            Ask
          </button>
          {base({
            loading,
            sort: { columnId: "pnl", direction: "ascending" },
            sortPending: pending,
          })}
        </>
      );
    };
    const host = await mount(<Pending />);
    const status = within(host).getByRole("status");
    fireEvent.click(within(host).getByRole("button", { name: "Done" }));
    await flush();
    expect(status).toHaveTextContent("3 rows");
    fireEvent.click(within(host).getByRole("button", { name: "Ask" }));
    await flush();
    expect(status).toHaveTextContent("");
  });

  it("says the row count when a load ends", async () => {
    const host = await mount(<Loader />);
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent("");
    fireEvent.click(within(host).getByRole("button", { name: "Done" }));
    await act(async () => undefined);
    expect(status).toHaveTextContent("3 rows");
  });
});

describe("Table (CMP-049) v0 bound", () => {
  const rows = (n: number): User[] =>
    Array.from({ length: n }, (_, i) => ({ id: `u${i}`, name: `user ${i}`, accounts: 1, pnl: 0 }));

  it("warns in development above 200 rows and still renders every row", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const host = await mount(base({ rows: rows(201) }));
    expect(warn).toHaveBeenCalledOnce();
    expect(warn.mock.calls[0]?.[0]).toContain("v0 bound of 200");
    expect(host.querySelectorAll("tbody tr")).toHaveLength(201);
  });

  it("is quiet at 200 rows", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await mount(base({ rows: rows(200) }));
    expect(warn).not.toHaveBeenCalled();
  });
});

describe("Table (CMP-049) grid mode, selection and row actions", () => {
  const page = within(document.body);
  const opened = vi.fn<(id: string) => void>();
  const gated = vi.fn<() => void>();
  const actions = (u: User): readonly MenuItem[] => [
    { id: "open", label: "Open", onSelect: () => opened(u.id) },
    {
      id: "caps",
      label: "Edit risk caps",
      disabledReason: "Only the owner can change account settings.",
      onSelect: gated,
    },
  ];

  type GridHostProps = Partial<TableProps<User>> & { readonly initial?: readonly string[] };

  /** Columns: 0 select, 1 Name, 2 Accounts, 3 PnL, 4 actions; rows: 0 header, 1 alex, 2 sam, 3 kim. */
  const GridHost = ({ initial = [], ...props }: GridHostProps): JSX.Element => {
    const [selected, setSelected] = useState<ReadonlySet<string>>(new Set(initial));
    const [sort, setSort] = useState<TableSort | undefined>(undefined);
    return (
      <>
        <button type="button">Before</button>
        <Table<User>
          caption={CAPTION}
          columns={COLUMNS}
          rows={USERS}
          rowKey={(u) => u.id}
          sort={sort}
          onSortChange={setSort}
          selected={selected}
          onRowSelect={setSelected}
          rowActions={actions}
          {...props}
        />
        <button type="button">After</button>
      </>
    );
  };

  const press = async (keys: string): Promise<void> => {
    await userEvent.keyboard(keys);
  };
  const grid = (): HTMLElement => page.getByRole("grid", { name: CAPTION });
  /** The element focus lands on for cell (r, c): its built-in control, else the cell. */
  const target = (r: number, c: number): HTMLElement => {
    const cell = grid().querySelector<HTMLElement>(`[data-cv-r="${r}"][data-cv-c="${c}"]`);
    if (cell === null) throw new Error(`no cell ${r},${c}`);
    return cell.hasAttribute("data-cv-widget")
      ? (cell.querySelector<HTMLElement>("input, button") as HTMLElement)
      : cell;
  };
  /** The table's own polite line (each row menu with a T2 item keeps its own reason region, CMP-041). */
  const status = (): HTMLElement => {
    const line = grid().closest(".cv-table")?.querySelector<HTMLElement>(".cv-table__live");
    if (line == null) throw new Error("no table status");
    return line;
  };

  beforeEach(() => {
    opened.mockReset();
    gated.mockReset();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("an interactive column makes a grid: role grid, gridcells, aria-colcount and multiselectable", async () => {
    await mount(<GridHost />);
    const g = grid();
    expect(g).toHaveAttribute("aria-colcount", "5");
    expect(g).toHaveAttribute("aria-multiselectable", "true");
    expect(within(g).getAllByRole("gridcell")).toHaveLength(15);
    expect(within(g).getAllByRole("columnheader")).toHaveLength(5);
    expect(page.queryByRole("table")).toBeNull();
    for (const row of within(g).getAllByRole("row").slice(1))
      expect(row).toHaveAttribute("aria-selected", "false");
  });

  it("grid forces grid mode on a static table; a table without it stays a table", async () => {
    await mount(base({ grid: true }));
    expect(grid()).not.toHaveAttribute("aria-multiselectable");
    expect(within(grid()).getAllByRole("gridcell")).toHaveLength(9);
  });

  it("is one Tab stop: in on the first body cell, out on the next Tab, back to the last focused cell", async () => {
    await mount(<GridHost />);
    page.getByRole("button", { name: "Before" }).focus();
    await userEvent.tab();
    expect(page.getByRole("checkbox", { name: "Select alex" })).toHaveFocus();
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    await press("{ArrowDown}{ArrowRight}{ArrowRight}");
    expect(target(2, 2)).toHaveFocus();
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(target(2, 2)).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(page.getByRole("button", { name: "Before" })).toHaveFocus();
  });

  it("keyboard matrix: arrows by cell (the header row included), Home / End, Ctrl+Home / Ctrl+End, clamped at the edges", async () => {
    await mount(<GridHost />);
    act(() => target(1, 0).focus());
    await press("{ArrowLeft}");
    expect(target(1, 0)).toHaveFocus();
    await press("{ArrowRight}");
    expect(target(1, 1)).toHaveFocus();
    expect(target(1, 1)).toHaveTextContent("alex");
    await press("{End}");
    expect(page.getByRole("button", { name: "Actions for alex" })).toHaveFocus();
    await press("{ArrowRight}");
    expect(target(1, 4)).toHaveFocus();
    await press("{Home}");
    expect(target(1, 0)).toHaveFocus();
    await press("{ArrowUp}");
    expect(page.getByRole("checkbox", { name: "Select all rows" })).toHaveFocus();
    await press("{ArrowUp}{ArrowRight}");
    expect(page.getByRole("button", { name: "Name" })).toHaveFocus();
    await press("{ArrowRight}");
    expect(target(0, 2)).toHaveFocus(); // a plain header cell takes focus itself
    await press("{Control>}{End}{/Control}");
    expect(page.getByRole("button", { name: "Actions for kim" })).toHaveFocus();
    await press("{ArrowDown}");
    expect(page.getByRole("button", { name: "Actions for kim" })).toHaveFocus();
    expect(page.queryByRole("menu")).toBeNull(); // ↓ moved (nowhere), it did not open the menu
    await press("{Control>}{Home}{/Control}");
    expect(page.getByRole("checkbox", { name: "Select all rows" })).toHaveFocus();
  });

  it("↑ / ↓ on an actions button move between rows instead of opening its menu", async () => {
    await mount(<GridHost />);
    act(() => target(1, 4).focus());
    await press("{ArrowDown}");
    expect(page.getByRole("button", { name: "Actions for sam" })).toHaveFocus();
    await press("{ArrowUp}");
    expect(page.getByRole("button", { name: "Actions for alex" })).toHaveFocus();
    expect(page.queryByRole("menu")).toBeNull();
  });

  it("Page Up / Page Down move by the rows that fit the region, less the header", async () => {
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(50);
    vi.spyOn(HTMLTableRowElement.prototype, "getBoundingClientRect").mockReturnValue({
      height: 25,
    } as DOMRect);
    await mount(<GridHost />);
    act(() => target(1, 1).focus());
    await press("{PageDown}");
    expect(target(2, 1)).toHaveFocus();
    await press("{PageDown}{PageDown}");
    expect(target(3, 1)).toHaveFocus();
    await press("{PageUp}");
    expect(target(2, 1)).toHaveFocus();
  });

  it("Page Down with nothing laid out steps a fixed page, clamped to the last row", async () => {
    await mount(<GridHost />);
    act(() => target(0, 2).focus());
    await press("{PageDown}");
    expect(target(3, 2)).toHaveFocus();
    await press("{PageUp}");
    expect(target(0, 2)).toHaveFocus();
  });

  it("a focused cell is scrolled into view at the nearest edge (its scroll margin clears the sticky header)", async () => {
    await mount(<GridHost />);
    act(() => target(1, 1).focus());
    await press("{ArrowDown}");
    const cell = target(2, 1);
    expect(cell.scrollIntoView).toHaveBeenLastCalledWith({ block: "nearest", inline: "nearest" });
    expect(vi.mocked(Element.prototype.scrollIntoView).mock.contexts.at(-1)).toBe(cell);
  });

  it("Space toggles the focused row: aria-selected, the row's box, and one polite count", async () => {
    await mount(<GridHost />);
    act(() => target(2, 2).focus());
    await press(" ");
    const sam = page.getAllByRole("row")[2] as HTMLElement;
    expect(sam).toHaveAttribute("aria-selected", "true");
    expect(page.getByRole("checkbox", { name: "Select sam" })).toBeChecked();
    await waitFor(() => expect(status()).toHaveTextContent("1 selected"));
    await press(" ");
    expect(sam).toHaveAttribute("aria-selected", "false");
    await waitFor(() => expect(status()).toHaveTextContent("0 selected"));
  });

  it("Space on a row's box toggles it once (natively), not twice", async () => {
    await mount(<GridHost />);
    act(() => target(1, 0).focus());
    await press(" ");
    expect(page.getByRole("checkbox", { name: "Select alex" })).toBeChecked();
    await waitFor(() => expect(status()).toHaveTextContent("1 selected"));
  });

  it("select-all: unchecked, mixed when some rows are selected, checked when all; a press from mixed selects all", async () => {
    await mount(<GridHost initial={["u2"]} />);
    const all = page.getByRole("checkbox", { name: "Select all rows" });
    expect(all).toBePartiallyChecked();
    await userEvent.click(all);
    expect(all).toBeChecked();
    expect(all).not.toBePartiallyChecked();
    expect(
      page
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.getAttribute("aria-selected")),
    ).toEqual(["true", "true", "true"]);
    await waitFor(() => expect(status()).toHaveTextContent("3 selected"));
    await userEvent.click(all);
    expect(all).not.toBeChecked();
    expect(all).not.toBePartiallyChecked();
    await waitFor(() => expect(status()).toHaveTextContent("0 selected"));
  });

  it("says a selection change once: the first render and unrelated re-renders say nothing", async () => {
    await mount(<GridHost initial={["u1"]} />);
    expect(status()).toHaveTextContent("");
    const said: string[] = [];
    const watcher = new MutationObserver(() => said.push(status().textContent ?? ""));
    watcher.observe(status(), { childList: true, subtree: true, characterData: true });
    await userEvent.click(page.getByRole("checkbox", { name: "Select kim" }));
    await act(async () => {
      fireEvent.focus(target(1, 2));
    });
    await act(async () => {
      fireEvent.focus(target(3, 3));
    });
    watcher.disconnect();
    expect(said).toEqual(["2 selected"]);
  });

  it("select-all is disabled with no rows, and its header cell keeps the Tab stop", async () => {
    await mount(<GridHost rows={[]} />);
    expect(page.getByRole("checkbox", { name: "Select all rows" })).toBeDisabled();
    await userEvent.tab();
    await userEvent.tab();
    expect(target(0, 0)).toHaveFocus();
  });

  it("selectDisabledReason: every select box and select-all are T2, state the reason, and change nothing", async () => {
    const onRowSelect = vi.fn();
    await mount(
      <GridHost selectDisabledReason="Your role can't change alerts." onRowSelect={onRowSelect} />,
    );
    for (const name of ["Select all rows", "Select alex", "Select sam", "Select kim"]) {
      const box = page.getByRole("checkbox", { name });
      expect(box).toHaveAttribute("aria-disabled", "true");
      expect(box).toHaveAccessibleDescription("Your role can't change alerts.");
    }
    await userEvent.click(page.getByRole("checkbox", { name: "Select alex" }));
    await userEvent.click(page.getByRole("checkbox", { name: "Select all rows" }));
    act(() => target(2, 2).focus());
    await press(" ");
    expect(page.getAllByRole("row")[2]).not.toHaveAttribute("aria-selected", "true");
    expect(onRowSelect).not.toHaveBeenCalled();
  });

  it("the actions button opens the row menu; Esc returns focus to it", async () => {
    await mount(<GridHost />);
    const button = page.getByRole("button", { name: "Actions for sam" });
    act(() => button.focus());
    await press("{Enter}");
    const menu = page.getByRole("menu", { name: "Actions for sam" });
    expect(menu).toBeVisible();
    expect(within(menu).getByRole("menuitem", { name: "Open" })).toHaveFocus();
    await press("{Escape}");
    expect(page.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
    await press("{Enter}{Enter}");
    expect(opened).toHaveBeenCalledWith("u2");
  });

  it("T2 items are arrow-reachable, never activated, and keep their reason", async () => {
    await mount(<GridHost />);
    act(() => page.getByRole("button", { name: "Actions for alex" }).focus());
    await press("{Enter}{ArrowDown}");
    const caps = page.getByRole("menuitem", { name: /Edit risk caps/ });
    expect(caps).toHaveFocus();
    expect(caps).toHaveAttribute("aria-disabled", "true");
    expect(caps).toHaveAccessibleDescription(/Only the owner can change account settings\./);
    await press("{Enter}");
    await userEvent.click(caps);
    expect(gated).not.toHaveBeenCalled();
  });

  it("Shift+F10 on a focused row opens that row's menu at the row; Esc returns focus to the cell", async () => {
    await mount(<GridHost />);
    act(() => target(2, 2).focus());
    await press("{Shift>}{F10}{/Shift}");
    const menu = page.getByRole("menu", { name: "Actions for sam" });
    expect(within(menu).getByRole("menuitem", { name: "Open" })).toHaveFocus();
    await press("{Escape}");
    expect(page.queryByRole("menu")).toBeNull();
    expect(target(2, 2)).toHaveFocus();
    await press("{ArrowDown}{Shift>}{F10}{/Shift}{Enter}");
    expect(opened).toHaveBeenCalledWith("u3");
  });

  it("the ContextMenu key opens it too", async () => {
    await mount(<GridHost />);
    act(() => target(1, 3).focus());
    await press("{ContextMenu}");
    expect(page.getByRole("menu", { name: "Actions for alex" })).toBeVisible();
  });

  it("rowLabel names the row's box and actions", async () => {
    await mount(<GridHost rowLabel={(u) => `user ${u.name}`} />);
    expect(page.getByRole("checkbox", { name: "Select user alex" })).toBeInTheDocument();
    expect(page.getByRole("button", { name: "Actions for user alex" })).toBeInTheDocument();
  });

  it("the default row name falls back to the key when the first column is not text", async () => {
    const columns: readonly TableColumn<User>[] = [
      { id: "badge", header: "Badge", cell: (u) => <b>{u.name}</b> },
      ...COLUMNS,
    ];
    await mount(<GridHost columns={columns} />);
    expect(page.getByRole("button", { name: "Actions for u1" })).toBeInTheDocument();
  });

  it("an interactive cell: its controls leave the Tab order; Enter or F2 moves in, Esc moves back", async () => {
    const columns: readonly TableColumn<User>[] = [
      ...COLUMNS,
      {
        id: "note",
        header: "Note",
        interactive: true,
        cell: (u) => <input aria-label={`Note for ${u.name}`} />,
      },
    ];
    await mount(<GridHost columns={columns} onRowSelect={undefined} rowActions={undefined} />);
    const input = page.getByRole("textbox", { name: "Note for alex" });
    expect(input).toHaveAttribute("tabindex", "-1");
    act(() => target(1, 3).focus());
    await press("{Enter}");
    expect(input).toHaveFocus();
    await press("ab{ArrowLeft}");
    expect(input).toHaveFocus(); // the control owns its keys
    await press("{Escape}");
    expect(target(1, 3)).toHaveFocus();
    await press("{F2}");
    expect(input).toHaveFocus();
  });

  const named = (u: User): readonly MenuItem[] => [
    { id: "open", label: `Open ${u.name}`, onSelect: () => opened(u.id) },
    {
      id: "caps",
      label: "Edit risk caps",
      disabledReason: "Only the owner can change account settings.",
      onSelect: gated,
    },
  ];

  it("a right-click opens the pressed row's menu, not the remembered row's", async () => {
    await mount(<GridHost rowActions={named} />);
    act(() => target(1, 1).focus());
    await userEvent.pointer({ keys: "[MouseRight]", target: target(3, 2) });
    const menu = page.getByRole("menu", { name: "Actions for kim" });
    expect(within(menu).getByRole("menuitem", { name: "Open kim" })).toHaveFocus();
    expect(within(menu).queryByRole("menuitem", { name: "Open alex" })).toBeNull();
    await press("{Escape}");
    expect(target(3, 2)).toHaveFocus();
  });

  it("a right-click on the actions or select cell's padding opens that row's menu, focus on its control", async () => {
    await mount(<GridHost rowActions={named} />);
    act(() => target(1, 1).focus());
    const actionsCell = grid().querySelector<HTMLElement>('[data-cv-r="3"][data-cv-c="4"]');
    await userEvent.pointer({ keys: "[MouseRight]", target: actionsCell as HTMLElement });
    expect(page.getByRole("menu", { name: "Actions for kim" })).toBeVisible();
    await press("{Escape}");
    expect(page.getByRole("button", { name: "Actions for kim" })).toHaveFocus();
    const selectCell = grid().querySelector<HTMLElement>('[data-cv-r="2"][data-cv-c="0"]');
    await userEvent.pointer({ keys: "[MouseRight]", target: selectCell as HTMLElement });
    expect(page.getByRole("menu", { name: "Actions for sam" })).toBeVisible();
    await press("{Escape}");
    expect(page.getByRole("checkbox", { name: "Select sam" })).toHaveFocus();
  });

  it("a press on a widget cell's padding focuses its control; a press on the control is left alone", async () => {
    await mount(<GridHost />);
    const downOn = (node: Element): MouseEvent => {
      const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
      act(() => {
        node.dispatchEvent(event);
      });
      return event;
    };
    const selectCell = grid().querySelector('[data-cv-r="2"][data-cv-c="0"]') as Element;
    // The page's own focus change is prevented; the box takes focus.
    expect(downOn(selectCell).defaultPrevented).toBe(true);
    expect(page.getByRole("checkbox", { name: "Select sam" })).toHaveFocus();
    expect(downOn(page.getByRole("button", { name: "Actions for kim" })).defaultPrevented).toBe(
      false,
    );
  });

  it("one live region: row menus with T2 items add none, closed or open; the table's line says a reason per press", async () => {
    await mount(<GridHost rowActions={named} />);
    expect(document.querySelectorAll('[role="status"]')).toHaveLength(1);
    act(() => page.getByRole("button", { name: "Actions for sam" }).focus());
    await press("{Enter}");
    expect(page.getByRole("menu", { name: "Actions for sam" })).toBeVisible();
    expect(document.querySelectorAll('[role="status"]')).toHaveLength(1);
    await press("{ArrowDown}{Enter}");
    expect(gated).not.toHaveBeenCalled();
    const said = status().firstElementChild;
    expect(status()).toHaveTextContent("Only the owner can change account settings.");
    await press("{Enter}");
    // The same reason again: a new node, so it is said again.
    expect(status().firstElementChild).not.toBe(said);
    expect(status()).toHaveTextContent("Only the owner can change account settings.");
    await press("{Escape}");
    await press("{Shift>}{F10}{/Shift}");
    expect(page.getByRole("menu", { name: "Actions for sam" })).toBeVisible();
    expect(document.querySelectorAll('[role="status"]')).toHaveLength(1);
  });

  it("asks for a row's actions only while its menu is open", async () => {
    const spy = vi.fn(named);
    await mount(<GridHost rowActions={spy} />);
    expect(spy).not.toHaveBeenCalled();
    act(() => page.getByRole("button", { name: "Actions for sam" }).focus());
    await press("{Enter}");
    expect(spy).toHaveBeenCalled();
    expect(new Set(spy.mock.calls.map(([u]) => u.id))).toEqual(new Set(["u2"]));
    await press("{Escape}");
    spy.mockClear();
    act(() => target(3, 1).focus());
    await press("{ArrowUp}");
    expect(spy).not.toHaveBeenCalled();
  });

  it("counts only selected keys among the rows: a stale key is not counted", async () => {
    await mount(<GridHost initial={["u1", "gone"]} />);
    await userEvent.click(page.getByRole("checkbox", { name: "Select sam" }));
    await waitFor(() => expect(status()).toHaveTextContent("2 selected"));
    expect(page.getByRole("checkbox", { name: "Select all rows" })).toBePartiallyChecked();
  });

  it("a load says no count; the same selection after it stays silent", async () => {
    const Reload = (): JSX.Element => {
      const [loading, setLoading] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setLoading((l) => !l)}>
            Reload
          </button>
          <GridHost initial={["u1"]} loading={loading} />
        </>
      );
    };
    await mount(<Reload />);
    const reload = page.getByRole("button", { name: "Reload" });
    await userEvent.click(reload);
    await userEvent.click(reload);
    await waitFor(() => expect(status()).toHaveTextContent("3 rows"));
    expect(status()).not.toHaveTextContent("selected");
  });

  it("table mode is unchanged: no grid, no data-cv cells, the region keeps its Tab stop", async () => {
    await mount(<Host />);
    expect(page.queryByRole("grid")).toBeNull();
    expect(document.querySelector("[data-cv-c]")).toBeNull();
  });

  it("in grid mode a scrolling region is a named landmark but no Tab stop (the grid is the one stop)", async () => {
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(400);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(100);
    await mount(<GridHost />);
    expect(page.getByRole("region", { name: CAPTION })).not.toHaveAttribute("tabindex");
  });
});

describe("Table (CMP-049) grid mode: E08-D07's window, custom rows, merged cells and T2", () => {
  const page = within(document.body);

  interface Sym {
    readonly id: string;
    readonly symbol: string;
    readonly last: number;
  }
  const LIST: readonly Sym[] = Array.from({ length: 120 }, (_, i) => ({
    id: `s${i}`,
    symbol: `S${String(i).padStart(3, "0")}USDT`,
    last: 100 + i,
  }));
  const SYM_COLUMNS: readonly TableColumn<Sym>[] = [
    { id: "symbol", header: "Symbol", cell: (s) => s.symbol },
    { id: "last", header: "Last", cell: (s) => s.last, numeric: "price" },
    { id: "chg", header: "24h %", cell: (s) => s.last / 10, numeric: "pct" },
  ];
  const LIVE_SORT = "Live sort needs every symbol live.";

  type WindowHostProps = Partial<TableProps<Sym>> & {
    readonly size?: number;
    readonly start?: number;
  };

  /** A host that windows the list: `size` rows from the first row it is asked for, as SCR-100 does past 60. */
  const WindowHost = ({ size = 10, start = 0, ...props }: WindowHostProps): JSX.Element => {
    const [offset, setOffset] = useState(start);
    return (
      <>
        <button type="button" onClick={() => setOffset(60)}>
          Jump
        </button>
        <Table<Sym>
          grid
          caption="Alts"
          columns={SYM_COLUMNS}
          rows={LIST.slice(offset, offset + size)}
          rowKey={(s) => s.id}
          rowWindow={{ offset, total: LIST.length }}
          onRowsInView={(first) => setOffset(Math.min(Math.max(0, first), LIST.length - size))}
          {...props}
        />
        <button type="button">After</button>
      </>
    );
  };

  /** A custom row as CMP-161 draws one: the symbol is the row header, then the values. */
  const renderSym = (s: Sym, grid: TableRowContext): JSX.Element => (
    <tr {...grid.rowProps}>
      <th {...grid.cellProps(0, { header: true })}>{s.symbol}</th>
      <td {...grid.cellProps(1, { numeric: true })}>{s.last.toFixed(2)}</td>
      <td {...grid.cellProps(2, { numeric: true })}>{(s.last / 10).toFixed(2)}</td>
    </tr>
  );
  /** Row s1 merges its two value cells, as a delisted watchlist row does (E08-D07 D20). */
  const renderMerged = (s: Sym, grid: TableRowContext): JSX.Element =>
    s.id === "s1" ? (
      <tr {...grid.rowProps}>
        <th {...grid.cellProps(0, { header: true })}>{s.symbol}</th>
        <td {...grid.cellProps(1, { span: 2 })}>Delisted by the exchange</td>
      </tr>
    ) : (
      renderSym(s, grid)
    );
  /** Enter on any cell of a row is refused with a reason (a T2 key, E08-D07 §6.6). */
  const renderRefused = (s: Sym, grid: TableRowContext): JSX.Element => (
    <tr
      {...grid.rowProps}
      onKeyDown={(event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        grid.refuse("Delisted by the exchange");
      }}
    >
      <th {...grid.cellProps(0, { header: true })}>{s.symbol}</th>
      <td {...grid.cellProps(1, { numeric: true })}>{s.last.toFixed(2)}</td>
      <td {...grid.cellProps(2, { numeric: true, echo: "Last update 10:31:02 UTC" })}>
        {(s.last / 10).toFixed(2)}
      </td>
    </tr>
  );
  const CustomHost = (props: Partial<TableProps<Sym>>): JSX.Element => (
    <>
      <button type="button">Before</button>
      <Table<Sym>
        grid
        caption="Majors"
        columns={SYM_COLUMNS}
        rows={LIST.slice(0, 4)}
        rowKey={(s) => s.id}
        renderRow={renderSym}
        {...props}
      />
      <button type="button">After</button>
    </>
  );

  const grid = (): HTMLElement => page.getByRole("grid");
  const cellAt = (r: number, c: number): HTMLElement => {
    const cell = grid().querySelector<HTMLElement>(`[data-cv-r="${r}"][data-cv-c="${c}"]`);
    if (cell === null) throw new Error(`no cell ${r},${c}`);
    return cell;
  };
  const rowOfFocus = (): string | null | undefined =>
    document.activeElement?.closest("tr")?.getAttribute("aria-rowindex");
  const echo = (): HTMLElement | null =>
    document.querySelector<HTMLElement>('.cv-table__echo[data-cmp="CMP-016"]');
  const line = (): HTMLElement =>
    grid().closest(".cv-table")?.querySelector<HTMLElement>(".cv-table__live") as HTMLElement;
  const rect = (top: number, height: number): DOMRect =>
    ({ top, height, bottom: top + height, left: 0, right: 0, width: 0, x: 0, y: top }) as DOMRect;

  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("a window: aria-rowcount counts the whole list and each drawn row's aria-rowindex is absolute", async () => {
    await mount(<WindowHost start={50} />);
    expect(grid()).toHaveAttribute("aria-rowcount", "121");
    const rows = within(grid()).getAllByRole("row");
    expect(rows).toHaveLength(11);
    expect([
      rows[1]?.getAttribute("aria-rowindex"),
      rows[10]?.getAttribute("aria-rowindex"),
    ]).toEqual(["52", "61"]);
  });

  it("a window: the rows it does not draw are held by spacer rows hidden from AT", async () => {
    await mount(<WindowHost start={50} />);
    const spacers = grid().querySelectorAll("tbody tr.cv-table__spacer");
    expect(spacers.length).toBeGreaterThanOrEqual(2);
    for (const spacer of spacers) expect(spacer).toHaveAttribute("aria-hidden", "true");
  });

  it.each([0, 3, 4])("a window keeps the zebra of the absolute row (offset %i)", async (start) => {
    await mount(<WindowHost start={start} />);
    const first = within(grid()).getAllByRole("row")[1] as HTMLElement;
    expect(first.matches(":nth-child(even)")).toBe(start % 2 === 1);
  });

  it("reports the rows in view as the region scrolls, once per change", async () => {
    const seen: [number, number][] = [];
    await mount(
      <Table<Sym>
        grid
        caption="Alts"
        columns={SYM_COLUMNS}
        rows={LIST.slice(0, 20)}
        rowKey={(s) => s.id}
        rowWindow={{ offset: 0, total: LIST.length }}
        onRowsInView={(first, last) => seen.push([first, last])}
      />,
    );
    const region = document.querySelector(".cv-table__region") as HTMLElement;
    let scrollTop = 0;
    Object.defineProperty(region, "scrollTop", { configurable: true, get: () => scrollTop });
    Object.defineProperty(region, "clientHeight", { configurable: true, get: () => 120 });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      if (this.tagName === "TBODY") return rect(24 - scrollTop, 24 * LIST.length);
      if (this.tagName === "THEAD" || this.tagName === "TR") return rect(0, 24);
      return rect(0, 0);
    });
    scrollTop = 240;
    fireEvent.scroll(region);
    fireEvent.scroll(region);
    expect(seen).toEqual([[10, 13]]);
  });

  it("↓ on the last drawn row asks the host for the next row and lands focus once it is drawn", async () => {
    await mount(<WindowHost />);
    act(() => cellAt(10, 1).focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(rowOfFocus()).toBe("12");
    expect(document.activeElement).toHaveTextContent("110.00");
  });

  it("Ctrl+End reaches the last cell of the whole list, drawn first", async () => {
    await mount(<WindowHost />);
    act(() => cellAt(1, 0).focus());
    await userEvent.keyboard("{Control>}{End}{/Control}");
    expect(rowOfFocus()).toBe("121");
    expect(document.activeElement).toBe(cellAt(120, 2));
  });

  it("the one Tab stop stays on a drawn row when the remembered row leaves the window", async () => {
    await mount(<WindowHost />);
    act(() => cellAt(3, 1).focus());
    await userEvent.click(page.getByRole("button", { name: "Jump" }));
    const stops = grid().querySelectorAll('[tabindex="0"]');
    expect(stops).toHaveLength(1);
    expect(stops[0]?.closest("tr")).toHaveAttribute("aria-rowindex", "62");
    await userEvent.tab();
    expect(document.activeElement).toBe(stops[0]);
  });

  /** A host that draws the row it is asked for only when told to (`draw`), as one that loads its rows would. */
  const DeferredHost = ({
    onDraw,
  }: {
    readonly onDraw: (draw: () => void) => void;
  }): JSX.Element => {
    const [offset, setOffset] = useState(0);
    const [asked, setAsked] = useState(0);
    onDraw(() => setOffset(Math.max(0, Math.min(asked - 15, LIST.length - 20))));
    return (
      <>
        <Table<Sym>
          grid
          caption="Alts"
          columns={SYM_COLUMNS}
          rows={LIST.slice(offset, offset + 20)}
          rowKey={(s) => s.id}
          rowWindow={{ offset, total: LIST.length }}
          onRowsInView={(first) => setAsked(first)}
        />
        <button type="button">After</button>
      </>
    );
  };

  it("a press in the grid drops a key's request for an undrawn row: focus never jumps to it later", async () => {
    let draw = (): void => undefined;
    await mount(<DeferredHost onDraw={(fn) => (draw = fn)} />);
    act(() => cellAt(20, 1).focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellAt(20, 1));
    act(() => {
      fireEvent.mouseDown(cellAt(15, 1));
    });
    act(() => draw());
    expect(grid().querySelector('[data-cv-r="21"]')).not.toBeNull();
    expect(document.activeElement).toBe(cellAt(20, 1));
  });

  it("focus moved in the grid drops a key's request for an undrawn row: focus never jumps to it later", async () => {
    let draw = (): void => undefined;
    await mount(<DeferredHost onDraw={(fn) => (draw = fn)} />);
    act(() => cellAt(20, 1).focus());
    await userEvent.keyboard("{ArrowDown}");
    act(() => cellAt(15, 2).focus());
    act(() => draw());
    expect(grid().querySelector('[data-cv-r="21"]')).not.toBeNull();
    expect(document.activeElement).toBe(cellAt(15, 2));
  });

  it("an undisturbed request still lands focus on its row once the host draws it", async () => {
    let draw = (): void => undefined;
    await mount(<DeferredHost onDraw={(fn) => (draw = fn)} />);
    act(() => cellAt(20, 1).focus());
    await userEvent.keyboard("{ArrowDown}");
    act(() => draw());
    expect(document.activeElement).toBe(cellAt(21, 1));
  });

  it("a cell's echo words show on hover after CMP-016's 300 ms, and go CMP-016's 100 ms grace after the pointer leaves", async () => {
    vi.useFakeTimers();
    try {
      await mount(<CustomHost renderRow={renderRefused} />);
      act(() => {
        fireEvent.pointerOver(cellAt(1, 2));
      });
      act(() => {
        vi.advanceTimersByTime(299);
      });
      expect(echo()).toHaveAttribute("hidden");
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(echo()).toHaveTextContent("Last update 10:31:02 UTC");
      expect(echo()).not.toHaveAttribute("hidden");
      // A pointerout with no related target leaves the table (React's leave): the leave grace starts.
      act(() => {
        fireEvent.pointerOut(cellAt(1, 2));
      });
      act(() => {
        vi.advanceTimersByTime(99);
      });
      expect(echo()).not.toHaveAttribute("hidden");
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(echo()).toHaveAttribute("hidden");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a hover echo stays while the pointer crosses onto it and rests there (WCAG 1.4.13); leaving both hides it after the grace", async () => {
    vi.useFakeTimers();
    try {
      await mount(<CustomHost renderRow={renderRefused} />);
      const cell = cellAt(1, 2);
      act(() => {
        fireEvent.pointerOver(cell);
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      const surface = echo() as HTMLElement;
      expect(surface).not.toHaveAttribute("hidden");
      // The pointer leaves the cell for the echo: React's leave of the table, its enter of the echo.
      act(() => {
        fireEvent.pointerOut(cell, { relatedTarget: surface });
        fireEvent.pointerOver(surface, { relatedTarget: cell });
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(echo()).toBe(surface);
      expect(surface).toHaveTextContent("Last update 10:31:02 UTC");
      // It leaves the echo for the page: the echo goes once the grace has passed.
      act(() => {
        fireEvent.pointerOut(surface);
      });
      act(() => {
        vi.advanceTimersByTime(99);
      });
      expect(echo()).toBe(surface);
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(echo()).toHaveAttribute("hidden");
    } finally {
      vi.useRealTimers();
    }
  });

  it("a hover echo stays when the pointer comes back from it to its cell", async () => {
    vi.useFakeTimers();
    try {
      await mount(<CustomHost renderRow={renderRefused} />);
      const cell = cellAt(1, 2);
      act(() => {
        fireEvent.pointerOver(cell);
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      const surface = echo() as HTMLElement;
      act(() => {
        fireEvent.pointerOut(cell, { relatedTarget: surface });
        fireEvent.pointerOut(surface, { relatedTarget: cell });
        fireEvent.pointerOver(cell, { relatedTarget: surface });
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(echo()).toBe(surface);
    } finally {
      vi.useRealTimers();
    }
  });

  // The leave grace is for a hover echo: keyboard focus on its cell keeps the echo whatever the pointer does (WCAG 2.1.1
  // and 1.4.13 together: the words stay while the cell is focused, the pointer a bystander).
  it.each([
    { where: "onto another cell", move: () => fireEvent.pointerOver(cellAt(2, 1)) },
    { where: "out of the table", move: () => fireEvent.pointerOut(cellAt(1, 2)) },
  ])(
    "a keyboard-focused cell's echo outlives the pointer moving $where: the leave grace never starts",
    async ({ move }) => {
      vi.useFakeTimers();
      try {
        await mount(<CustomHost renderRow={renderRefused} />);
        act(() => cellAt(1, 2).focus());
        expect(echo()).not.toHaveAttribute("hidden");
        act(() => {
          move();
        });
        act(() => {
          vi.advanceTimersByTime(1000);
        });
        expect(echo()).not.toHaveAttribute("hidden");
        expect(echo()).toHaveTextContent("Last update 10:31:02 UTC");
      } finally {
        vi.useRealTimers();
      }
    },
  );

  it("unmounting the table while the echo's leave grace runs clears its timer", async () => {
    vi.useFakeTimers();
    try {
      const Hideable = (): JSX.Element => {
        const [shown, setShown] = useState(true);
        return (
          <>
            <button type="button" onClick={() => setShown(false)}>
              Hide
            </button>
            {shown ? <CustomHost renderRow={renderRefused} /> : null}
          </>
        );
      };
      await mount(<Hideable />);
      const idle = vi.getTimerCount();
      act(() => {
        fireEvent.pointerOver(cellAt(1, 2));
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(echo()).not.toHaveAttribute("hidden");
      act(() => {
        fireEvent.pointerOut(cellAt(1, 2));
      });
      expect(vi.getTimerCount()).toBeGreaterThan(idle); // the leave grace is pending
      act(() => {
        fireEvent.click(page.getByRole("button", { name: "Hide" }));
      });
      expect(page.queryByRole("grid")).toBeNull();
      expect(vi.getTimerCount()).toBeLessThanOrEqual(idle);
    } finally {
      vi.useRealTimers();
    }
  });

  it("renderRow: a custom row takes the grid contract, its first cell the row header", async () => {
    await mount(<CustomHost />);
    expect(within(grid()).getAllByRole("rowheader")).toHaveLength(4);
    expect(within(grid()).getAllByRole("gridcell")).toHaveLength(8);
    expect(within(grid()).getAllByRole("row")[1]).toHaveAttribute("aria-rowindex", "2");
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
  });

  it("renderRow: one Tab stop, then the arrows move by cell through the custom cells", async () => {
    await mount(<CustomHost />);
    page.getByRole("button", { name: "Before" }).focus();
    await userEvent.tab();
    expect(document.activeElement).toBe(cellAt(1, 0));
    await userEvent.keyboard("{ArrowRight}{ArrowDown}");
    expect(document.activeElement).toBe(cellAt(2, 1));
  });

  it("renderRow draws no select or actions column; the row menu opens as a context menu", async () => {
    await mount(
      <CustomHost
        onRowSelect={() => undefined}
        rowActions={(s) => [{ id: "copy", label: `Copy ${s.symbol}`, onSelect: () => undefined }]}
      />,
    );
    expect(grid()).toHaveAttribute("aria-colcount", "3");
    expect(page.queryByRole("checkbox")).toBeNull();
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Shift>}{F10}{/Shift}");
    expect(page.getByRole("menuitem", { name: "Copy S001USDT" })).toHaveFocus();
  });

  it("a merged cell: a native colspan, and one cell to → and ←", async () => {
    await mount(<CustomHost renderRow={renderMerged} />);
    act(() => cellAt(2, 0).focus());
    await userEvent.keyboard("{ArrowRight}");
    const merged = cellAt(2, 1);
    expect(document.activeElement).toBe(merged);
    expect(merged).toHaveAttribute("colspan", "2");
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(merged);
    await userEvent.keyboard("{ArrowLeft}");
    expect(document.activeElement).toBe(cellAt(2, 0));
  });

  it("a merged cell: ↓ onto any column it covers lands on it; ↓ off it keeps its first column", async () => {
    await mount(<CustomHost renderRow={renderMerged} />);
    act(() => cellAt(1, 2).focus());
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellAt(2, 1));
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(cellAt(3, 1));
  });

  it("refuse(): a T2 key changes nothing and shows its reason in an aria-hidden echo on the focused cell", async () => {
    await mount(<CustomHost renderRow={renderRefused} />);
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Enter}");
    expect(echo()).not.toHaveAttribute("hidden");
    expect(echo()).toHaveTextContent("Delisted by the exchange");
    expect(echo()).toHaveAttribute("aria-hidden", "true");
    expect(document.activeElement).toBe(cellAt(2, 1));
  });

  it("refuse(): each press says the reason once, through the gated announcer, never the table's own line", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <CustomHost renderRow={renderRefused} />
      </GatedAnnounceProvider>,
    );
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Enter}{Enter}");
    expect(announce.mock.calls).toEqual([
      ["Delisted by the exchange"],
      ["Delisted by the exchange"],
    ]);
    expect(line()).not.toHaveTextContent("Delisted by the exchange");
  });

  it("refuse(): without a host's announcer the reason is said once in the package's polite region", async () => {
    await mount(<CustomHost renderRow={renderRefused} />);
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Enter}");
    expect(await politeText()).toBe("Delisted by the exchange");
    expect(line().textContent).toBe("");
  });

  it("refuse(): Esc hides the echo and keeps focus; a move hides it too", async () => {
    await mount(<CustomHost renderRow={renderRefused} />);
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Enter}{Escape}");
    expect(echo()).toHaveAttribute("hidden");
    expect(document.activeElement).toBe(cellAt(2, 1));
    await userEvent.keyboard("{Enter}{ArrowLeft}");
    expect(echo()).toHaveAttribute("hidden");
  });

  it("a cell's echo text shows on keyboard focus, aria-hidden, and goes on blur", async () => {
    await mount(<CustomHost renderRow={renderRefused} />);
    act(() => cellAt(1, 1).focus());
    await userEvent.keyboard("{ArrowRight}");
    expect(echo()).toHaveTextContent("Last update 10:31:02 UTC");
    expect(echo()).not.toHaveAttribute("hidden");
    await userEvent.keyboard("{ArrowLeft}");
    expect(echo()).toHaveAttribute("hidden");
  });

  /** Lays `element` out cut: its text `scroll` px wide in a box `client` px wide (jsdom has no layout). */
  const cutTo = (element: Element, scroll: number, client: number): void => {
    Object.defineProperty(element, "scrollWidth", { configurable: true, value: scroll });
    Object.defineProperty(element, "clientWidth", { configurable: true, value: client });
  };

  it("a cut header label is a block of its own; on keyboard focus the echo shows its whole words (E08-D07 §4.1)", async () => {
    await mount(<CustomHost />);
    const header = cellAt(0, 2);
    const label = header.querySelector<HTMLElement>(".cv-table__label") as HTMLElement;
    cutTo(label, 37, 20);
    act(() => cellAt(1, 2).focus());
    await userEvent.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(header);
    expect(echo()).not.toHaveAttribute("hidden");
    expect(echo()).toHaveTextContent("24h %");
    // The header keeps its whole name: the cut is visual.
    expect(header).toHaveAccessibleName("24h %");
  });

  it("a cut sort header's label: its button's focus shows the whole words in the echo", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "chg" ? { ...c, sortable: true } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} onSortChange={() => undefined} />);
    const button = page.getByRole("button", { name: "24h %" });
    cutTo(button.querySelector(".cv-table__label") as HTMLElement, 37, 20);
    act(() => cellAt(1, 2).focus());
    await userEvent.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(button);
    expect(echo()).toHaveTextContent("24h %");
    expect(echo()).not.toHaveAttribute("hidden");
  });

  it("a header label that is not cut shows no echo", async () => {
    await mount(<CustomHost />);
    act(() => cellAt(1, 2).focus());
    await userEvent.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(cellAt(0, 2));
    expect(echo()).toHaveAttribute("hidden");
  });

  it("a cell's `cut` text: the echo shows it on hover while the cell is cut, after CMP-016's 300 ms", async () => {
    vi.useFakeTimers();
    try {
      const renderCut = (s: Sym, grid: TableRowContext): JSX.Element => (
        <tr {...grid.rowProps}>
          <th {...grid.cellProps(0, { header: true, cut: s.symbol })}>{s.symbol}</th>
          <td {...grid.cellProps(1, { numeric: true })}>{s.last.toFixed(2)}</td>
          <td {...grid.cellProps(2, { numeric: true })}>{(s.last / 10).toFixed(2)}</td>
        </tr>
      );
      await mount(<CustomHost renderRow={renderCut} />);
      cutTo(cellAt(2, 0), 90, 60);
      act(() => {
        fireEvent.pointerOver(cellAt(2, 0));
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(echo()).toHaveTextContent("S001USDT");
      expect(echo()).not.toHaveAttribute("hidden");
      // The same cell laid out whole: nothing to echo.
      act(() => {
        fireEvent.pointerOver(cellAt(3, 0));
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(echo()).toHaveAttribute("hidden");
    } finally {
      vi.useRealTimers();
    }
  });

  // A11Y-4702A3-03 (E08-D07 §4.1 pairs every ellipsis with the echo): `scrollWidth` and `clientWidth` are whole
  // pixels, so a text 0.4 px wider than its box reads as no cut there while the ellipsis is still drawn. The line is
  // measured to the fraction against the box's content width. jsdom has no layout and no `Range` geometry: the boxes
  // and the text runs below are what a browser reports (the whole-pixel measures rounded alike, as it rounds them).
  describe("a cut measured to the fraction", () => {
    /** The text runs' widths in px, as `Range` reports them. */
    const runs = new Map<Node, number>();
    const area = (left: number, width: number): DOMRect =>
      ({
        x: left,
        y: 0,
        left,
        right: left + width,
        top: 0,
        bottom: 20,
        width,
        height: 20,
      }) as DOMRect;
    const original = Object.getOwnPropertyDescriptor(Range.prototype, "getClientRects");

    beforeEach(() => {
      runs.clear();
      Object.defineProperty(Range.prototype, "getClientRects", {
        configurable: true,
        writable: true,
        value(this: Range): DOMRect[] {
          const width = runs.get(this.startContainer);
          return width === undefined ? [] : [area(0, width)];
        },
      });
    });
    afterEach(() => {
      if (original === undefined) Reflect.deleteProperty(Range.prototype, "getClientRects");
      else Object.defineProperty(Range.prototype, "getClientRects", original);
    });

    /** Lays `element` out `width` px wide, `padding` px of it padding, the whole-pixel measures rounded alike. */
    const boxed = (element: HTMLElement, width: number, padding = 0): void => {
      Object.defineProperty(element, "scrollWidth", {
        configurable: true,
        value: Math.round(width),
      });
      Object.defineProperty(element, "clientWidth", {
        configurable: true,
        value: Math.round(width),
      });
      element.getBoundingClientRect = () => area(0, width);
      if (padding > 0) element.style.padding = `0 ${padding / 2}px`;
    };

    /** A header label `text` px wide in a 100 px box, then focus on its header, as ↑ from the cell under it moves it. */
    const focusHeader = async (text: number): Promise<void> => {
      await mount(<CustomHost />);
      const label = cellAt(0, 2).querySelector<HTMLElement>(".cv-table__label") as HTMLElement;
      boxed(label, 100);
      runs.set(label.firstChild as Node, text);
      act(() => cellAt(1, 2).focus());
      await userEvent.keyboard("{ArrowUp}");
      expect(document.activeElement).toBe(cellAt(0, 2));
    };

    it("a header label 0.4 px wider than its box shows its whole words in the echo", async () => {
      await focusHeader(100.4);
      expect(echo()).not.toHaveAttribute("hidden");
      expect(echo()).toHaveTextContent("24h %");
    });

    it.each([100, 100.01])(
      "a header label %f px wide in a 100 px box is not cut: one layout step is rounding",
      async (text) => {
        await focusHeader(text);
        expect(echo()).toHaveAttribute("hidden");
      },
    );

    /** Rows whose symbol cell is `cut`, with an optional note after the symbol that takes no room (absolute). */
    const renderCut =
      (note?: string) =>
      (s: Sym, grid: TableRowContext): JSX.Element => (
        <tr {...grid.rowProps}>
          <th {...grid.cellProps(0, { header: true, cut: s.symbol })}>
            <span>{s.symbol}</span>
            {note === undefined ? null : <span style={{ position: "absolute" }}>{note}</span>}
          </th>
          <td {...grid.cellProps(1, { numeric: true })}>{s.last.toFixed(2)}</td>
          <td {...grid.cellProps(2, { numeric: true })}>{(s.last / 10).toFixed(2)}</td>
        </tr>
      );
    /** Focus on the symbol cell of the first row, as ← from its value moves it. */
    const focusSymbol = async (): Promise<void> => {
      act(() => cellAt(1, 1).focus());
      await userEvent.keyboard("{ArrowLeft}");
      expect(document.activeElement).toBe(cellAt(1, 0));
    };

    it("a symbol cell's padding is no room for its text: 100.4 px in a 116 px cell with 16 px of padding", async () => {
      await mount(<CustomHost renderRow={renderCut()} />);
      const cell = cellAt(1, 0);
      boxed(cell, 116, 16);
      runs.set(cell.querySelector("span")?.firstChild as Node, 100.4);
      await focusSymbol();
      expect(echo()).not.toHaveAttribute("hidden");
      expect(echo()).toHaveTextContent("S000USDT");
    });

    it("a visually hidden note in the cell takes no room in its line", async () => {
      await mount(<CustomHost renderRow={renderCut("Last update 10:31:02 UTC")} />);
      const cell = cellAt(1, 0);
      const [symbol, note] = cell.querySelectorAll("span");
      boxed(cell, 60);
      runs.set(symbol?.firstChild as Node, 60);
      runs.set(note?.firstChild as Node, 250);
      await focusSymbol();
      expect(echo()).toHaveAttribute("hidden");
    });
  });

  /** A host that edits its list as SCR-100 does through CMP-161's keys: `Del` removes a row, `Alt+↑/↓` moves it. */
  const EditHost = (): JSX.Element => {
    const [list, setList] = useState(LIST.slice(0, 4));
    const renderEditable = (s: Sym, grid: TableRowContext): JSX.Element => (
      <tr
        {...grid.rowProps}
        onKeyDown={(event) => {
          const down = event.key === "ArrowDown";
          if (event.key === "Delete") {
            event.preventDefault();
            setList((all) => all.filter((x) => x.id !== s.id));
          } else if (event.altKey && (down || event.key === "ArrowUp")) {
            event.preventDefault();
            setList((all) => {
              const from = all.findIndex((x) => x.id === s.id);
              const to = from + (down ? 1 : -1);
              if (to < 0 || to >= all.length) return all;
              const rest = all.filter((x) => x.id !== s.id);
              return [...rest.slice(0, to), s, ...rest.slice(to)];
            });
          }
        }}
      >
        <th {...grid.cellProps(0, { header: true })}>{s.symbol}</th>
        <td {...grid.cellProps(1, { numeric: true })}>{s.last.toFixed(2)}</td>
        <td {...grid.cellProps(2, { numeric: true })}>{(s.last / 10).toFixed(2)}</td>
      </tr>
    );
    return (
      <>
        <button type="button">Before</button>
        <Table<Sym>
          grid
          caption="Majors"
          columns={SYM_COLUMNS}
          rows={list}
          rowKey={(s) => s.id}
          renderRow={renderEditable}
        />
        <button type="button">After</button>
      </>
    );
  };
  /** The row header's text of the row that holds focus. */
  const focusedSymbol = (): string | null | undefined =>
    document.activeElement?.closest("tr")?.querySelector("th")?.textContent;

  it("Del on a middle row: focus moves to the same cell of the next row (E08-D07 §6.3)", async () => {
    await mount(<EditHost />);
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Delete}");
    expect(document.activeElement).toBe(cellAt(2, 1));
    expect(focusedSymbol()).toBe("S002USDT");
  });

  it("Del on the last row: focus moves to the same cell of the previous row", async () => {
    await mount(<EditHost />);
    act(() => cellAt(4, 2).focus());
    await userEvent.keyboard("{Delete}");
    expect(document.activeElement).toBe(cellAt(3, 2));
    expect(focusedSymbol()).toBe("S002USDT");
  });

  it("a reorder that moves the focused row's node: focus stays on the moved symbol, which keeps the Tab stop", async () => {
    await mount(<EditHost />);
    act(() => cellAt(1, 1).focus());
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(focusedSymbol()).toBe("S000USDT");
    expect(document.activeElement).toBe(cellAt(2, 1));
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    expect(cellAt(2, 1)).toHaveAttribute("tabindex", "0");
  });

  it("a reorder that moves another row's node: the focused symbol keeps focus and the Tab stop follows it", async () => {
    await mount(<EditHost />);
    act(() => cellAt(3, 2).focus());
    await userEvent.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(focusedSymbol()).toBe("S002USDT");
    expect(document.activeElement).toBe(cellAt(2, 2));
    expect(grid().querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    expect(cellAt(2, 2)).toHaveAttribute("tabindex", "0");
  });

  it("a row removed while focus is outside the grid takes nothing back into it", async () => {
    await mount(<EditHost />);
    act(() => cellAt(2, 1).focus());
    const after = page.getByRole("button", { name: "After" });
    await userEvent.tab();
    expect(document.activeElement).toBe(after);
    act(() => {
      fireEvent.keyDown(cellAt(2, 1), { key: "Delete" });
    });
    expect(document.activeElement).toBe(after);
  });

  it("a row removed after a click away from the grid takes nothing back into it: focus stays on the page", async () => {
    await mount(<EditHost />);
    act(() => cellAt(2, 1).focus());
    await userEvent.click(document.body);
    expect(document.activeElement).toBe(document.body);
    act(() => {
      fireEvent.keyDown(cellAt(2, 1), { key: "Delete" });
    });
    expect(document.activeElement).toBe(document.body);
  });

  /**
   * A windowed host that also edits its list (SCR-100 past 60 rows): `Del` removes a row, so the list shrinks;
   * `scrollTo` draws another window of it, as the region scrolling does, and the list keeps its length.
   */
  const WindowEditHost = ({
    onScroll,
  }: {
    readonly onScroll: (scrollTo: (offset: number) => void) => void;
  }): JSX.Element => {
    const [offset, setOffset] = useState(0);
    const [list, setList] = useState(LIST.slice(0, 30));
    onScroll(setOffset);
    return (
      <>
        <button type="button">Before</button>
        <Table<Sym>
          grid
          caption="Alts"
          columns={SYM_COLUMNS}
          rows={list.slice(offset, offset + 10)}
          rowKey={(s) => s.id}
          rowWindow={{ offset, total: list.length }}
          onRowsInView={() => undefined}
          renderRow={(s, grid) => (
            <tr
              {...grid.rowProps}
              onKeyDown={(event) => {
                if (event.key !== "Delete") return;
                event.preventDefault();
                setList((all) => all.filter((x) => x.id !== s.id));
              }}
            >
              <th {...grid.cellProps(0, { header: true })}>{s.symbol}</th>
              <td {...grid.cellProps(1, { numeric: true })}>{s.last.toFixed(2)}</td>
              <td {...grid.cellProps(2, { numeric: true })}>{(s.last / 10).toFixed(2)}</td>
            </tr>
          )}
        />
        <button type="button">After</button>
      </>
    );
  };

  it("a windowed list gives focus to the same cell of the next row when a removal shrinks it", async () => {
    await mount(<WindowEditHost onScroll={() => undefined} />);
    act(() => cellAt(3, 1).focus());
    await userEvent.keyboard("{Delete}");
    expect(focusedSymbol()).toBe("S003USDT");
    expect(document.activeElement).toBe(cellAt(3, 1));
  });

  it("a windowed list takes no focus back when the focused row only scrolls out of the window", async () => {
    let scrollTo: (offset: number) => void = () => undefined;
    await mount(<WindowEditHost onScroll={(fn) => (scrollTo = fn)} />);
    act(() => cellAt(3, 1).focus());
    expect(document.activeElement).toBe(cellAt(3, 1));
    act(() => scrollTo(15));
    expect(grid().querySelector('[data-cv-r="3"]')).toBeNull();
    expect(document.activeElement).toBe(document.body);
  });

  it("a T2 sort header keeps its button, label and aria-sort; aria-disabled, the lock, described by the host's note", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(
      <>
        <CustomHost columns={columns} onSortChange={() => undefined} sortReasonId="sort-note" />
        <p id="sort-note">{LIVE_SORT}</p>
      </>,
    );
    const button = page.getByRole("button", { name: "Not available Last" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(LIVE_SORT);
    expect(page.getByRole("columnheader", { name: "Not available Last" })).toHaveAttribute(
      "aria-sort",
      "none",
    );
  });

  it("a T2 sort header's lock leads its label, named Not available (E09-D09 §2.2, G-T2.1d)", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} onSortChange={() => undefined} />);
    const button = page.getByRole("button", { name: "Not available Last" });
    const lock = within(button).getByRole("img", { name: "Not available" });
    expect(button.firstElementChild).toContainElement(lock);
  });

  it("a press on a T2 sort header sorts nothing and re-shows its reason in the echo, said once", async () => {
    const onSortChange = vi.fn();
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <CustomHost columns={columns} onSortChange={onSortChange} />
      </GatedAnnounceProvider>,
    );
    const button = page.getByRole("button", { name: "Not available Last" });
    act(() => button.focus());
    await userEvent.keyboard("{Enter}");
    await userEvent.click(button);
    expect(onSortChange).not.toHaveBeenCalled();
    expect(echo()).toHaveTextContent(LIVE_SORT);
    expect(announce.mock.calls).toEqual([[LIVE_SORT], [LIVE_SORT]]);
    expect(line()).not.toHaveTextContent(LIVE_SORT);
  });

  // G-T2.3 (E09-D09 §9.3; the orchestrator's design read on #5146): a held Enter repeats its keydown, and each repeat
  // clicks a native button; the T2 sort header swallows the repeats, so the reason is said once per press.
  it("a held Enter on a T2 sort header sorts nothing and says its reason once, not per repeat", async () => {
    const onSortChange = vi.fn();
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <CustomHost columns={columns} onSortChange={onSortChange} />
      </GatedAnnounceProvider>,
    );
    const button = page.getByRole("button", { name: "Not available Last" });
    act(() => button.focus());
    holdEnter(button, 2);
    expect(announce.mock.calls).toEqual([[LIVE_SORT]]);
    holdEnter(button, 0);
    expect(announce.mock.calls).toEqual([[LIVE_SORT], [LIVE_SORT]]);
    expect(onSortChange).not.toHaveBeenCalled();
  });

  // An enabled sort header keeps the native repeat: only a T2 header swallows a held Enter's repeats (CR-4702AI-02).
  it("a held Enter on an enabled sort header keeps the native repeat: each repeat presses it", async () => {
    const onSortChange = vi.fn();
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} onSortChange={onSortChange} />);
    const button = page.getByRole("button", { name: "Last" });
    act(() => button.focus());
    holdEnter(button, 2);
    expect(onSortChange).toHaveBeenCalledTimes(3);
  });

  // G-T2.2 (E09-D09 §2.2, §11): the T2 header is the button table.css draws in text.tertiary (table-css.test.ts pins
  // the rule), the lock inside it taking the same colour.
  it("a T2 sort header is the .cv-table__sort[aria-disabled] button table.css draws in text.tertiary, its lock inside", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} onSortChange={() => undefined} />);
    const button = page.getByRole("button", { name: "Not available Last" });
    expect(button.matches('.cv-table__sort[aria-disabled="true"]')).toBe(true);
    expect(button.querySelector(".cv-table__lock svg")).not.toBeNull();
    expect(
      find(loadCss("table.css").normal, '.cv-table__sort[aria-disabled="true"]', "color"),
    ).toContain("color: var(--color-text-tertiary)");
  });

  it("a T2 sort header without a host note is described by its own reason", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} onSortChange={() => undefined} />);
    expect(page.getByRole("button", { name: "Not available Last" })).toHaveAccessibleDescription(
      LIVE_SORT,
    );
  });

  it("headerStatus: a glyph after the label and its word in the header's name", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "chg" ? { ...c, headerStatus: { icon: "warning", label: "stale" } } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} />);
    const header = page.getByRole("columnheader", { name: "24h % stale" });
    expect(header.querySelector(".cv-table__header-status svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("widthEm sets a column's width on its <col>, in em of the table's font", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "symbol" ? { ...c, widthEm: 7.5 } : c,
    ) as readonly TableColumn<Sym>[];
    await mount(<CustomHost columns={columns} />);
    const cols = grid().querySelectorAll<HTMLElement>("colgroup > col");
    expect([...cols].map((col) => col.style.width)).toEqual(["7.5em", "", ""]);
  });

  it("a text column aligned to the end marks its header and cells numeric", async () => {
    const columns: readonly TableColumn<Sym>[] = [
      ...SYM_COLUMNS.slice(0, 1),
      { id: "code", header: "Code", cell: (s) => s.id, align: "end" },
    ];
    await mount(
      <Table<Sym> caption="Codes" columns={columns} rows={LIST.slice(0, 2)} rowKey={(s) => s.id} />,
    );
    expect(page.getByRole("columnheader", { name: "Code" })).toHaveAttribute("data-numeric", "");
    expect(page.getByRole("cell", { name: "s0" })).toHaveAttribute("data-numeric", "");
  });

  it("announce: the table renders no live region and hands each line to the host's", async () => {
    const announce = vi.fn<(text: string) => void>();
    const SortingHost = (): JSX.Element => {
      const [sort, setSort] = useState<TableSort | undefined>(undefined);
      return (
        <CustomHost
          columns={
            SYM_COLUMNS.map((c) =>
              c.id === "symbol" ? { ...c, sortable: true } : c,
            ) as readonly TableColumn<Sym>[]
          }
          sort={sort}
          onSortChange={setSort}
          announce={announce}
        />
      );
    };
    await mount(<SortingHost />);
    expect(document.querySelector('[role="status"]')).toBeNull();
    await userEvent.click(page.getByRole("button", { name: "Symbol" }));
    // The line lands two effect passes after the click (the sort settles, then the line is set): wait for it.
    await waitFor(() => expect(announce.mock.calls).toEqual([["Sorted by Symbol, ascending"]]));
  });

  it("announce: a T2 key's reason goes to the gated announcer, not to the host's table lines", async () => {
    const lines = vi.fn<(text: string) => void>();
    const gated = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={gated}>
        <CustomHost renderRow={renderRefused} announce={lines} />
      </GatedAnnounceProvider>,
    );
    act(() => cellAt(2, 1).focus());
    await userEvent.keyboard("{Enter}");
    expect(gated.mock.calls).toEqual([["Delisted by the exchange"]]);
    expect(lines).not.toHaveBeenCalled();
  });

  it("axe: a windowed grid of custom rows with a merged cell and a T2 header", async () => {
    const columns: readonly TableColumn<Sym>[] = SYM_COLUMNS.map((c) =>
      c.id === "last" ? { ...c, sortable: true, sortDisabledReason: LIVE_SORT } : c,
    ) as readonly TableColumn<Sym>[];
    const host = await mount(
      <WindowHost renderRow={renderMerged} columns={columns} onSortChange={() => undefined} />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

// The orchestrator's design read on #5146 (item 5): E08-D07 §4.1 pairs every cut with the echo, in table mode too. A
// table-mode table has the same one CMP-016 echo, under the same rules as grid mode: a cut header label's or a cut
// cell's whole words after CMP-016's 300 ms hover, at once on a sort button's keyboard focus, gone CMP-016's 100 ms
// grace after the pointer leaves, and on Esc. Its static cells take no focus, so hover is their only way in.
describe("Table (CMP-049), table mode: the echo for a cut header or cell", () => {
  const page = within(document.body);
  /** The shown echo: none, or its node `hidden`, when nothing shows. */
  const shown = (): HTMLElement | null =>
    document.querySelector<HTMLElement>('.cv-table__echo[data-cmp="CMP-016"]:not([hidden])');
  /** Lays `element` out cut: its text `scroll` px wide in a box `client` px wide (jsdom has no layout). */
  const cutTo = (element: Element | null, scroll: number, client: number): void => {
    if (element === null) throw new Error("nothing to cut");
    Object.defineProperty(element, "scrollWidth", { configurable: true, value: scroll });
    Object.defineProperty(element, "clientWidth", { configurable: true, value: client });
  };
  const labelOf = (header: HTMLElement): Element | null => header.querySelector(".cv-table__label");

  it("a cut header label shows its whole words after CMP-016's 300 ms hover, and goes 100 ms after the pointer leaves", async () => {
    vi.useFakeTimers();
    try {
      await mount(<Host />);
      expect(page.queryByRole("grid")).toBeNull();
      const header = page.getByRole("columnheader", { name: "Accounts" });
      cutTo(labelOf(header), 37, 20);
      act(() => {
        fireEvent.pointerOver(header);
      });
      act(() => {
        vi.advanceTimersByTime(299);
      });
      expect(shown()).toBeNull();
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(shown()).toHaveTextContent("Accounts");
      expect(shown()).toHaveAttribute("aria-hidden", "true");
      act(() => {
        fireEvent.pointerOut(header);
      });
      act(() => {
        vi.advanceTimersByTime(99);
      });
      expect(shown()).toHaveTextContent("Accounts");
      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(shown()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a plain table mounts no echo node until one shows, and has none after it goes (CR-4702AI-02)", async () => {
    vi.useFakeTimers();
    try {
      await mount(<Host />);
      const node = (): Element | null => document.querySelector(".cv-table__echo");
      expect(node()).toBeNull();
      const header = page.getByRole("columnheader", { name: "Accounts" });
      cutTo(labelOf(header), 37, 20);
      act(() => {
        fireEvent.pointerOver(header);
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(node()).not.toBeNull();
      act(() => {
        fireEvent.pointerOut(header);
      });
      act(() => {
        vi.advanceTimersByTime(100);
      });
      expect(node()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a cut sort header's label shows its whole words at once on its button's keyboard focus; Esc hides it, focus kept", async () => {
    await mount(<Host />);
    const button = page.getByRole("button", { name: "Name" });
    cutTo(labelOf(button), 37, 20);
    await userEvent.tab();
    expect(button).toHaveFocus();
    expect(shown()).toHaveTextContent("Name");
    await userEvent.keyboard("{Escape}");
    expect(shown()).toBeNull();
    expect(button).toHaveFocus();
  });

  it("focus moving on from a cut header's button takes its echo away", async () => {
    await mount(<Host />);
    const name = page.getByRole("button", { name: "Name" });
    cutTo(labelOf(name), 37, 20);
    await userEvent.tab();
    expect(shown()).toHaveTextContent("Name");
    await userEvent.tab();
    expect(page.getByRole("button", { name: "PnL" })).toHaveFocus();
    expect(shown()).toBeNull();
  });

  it("a hover echo stays while the pointer crosses onto it and rests there (WCAG 1.4.13)", async () => {
    vi.useFakeTimers();
    try {
      await mount(<Host />);
      const header = page.getByRole("columnheader", { name: "Accounts" });
      cutTo(labelOf(header), 37, 20);
      act(() => {
        fireEvent.pointerOver(header);
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      const surface = shown() as HTMLElement;
      expect(surface).toHaveTextContent("Accounts");
      // The pointer leaves the header for the echo: React's leave of the table, its enter of the echo.
      act(() => {
        fireEvent.pointerOut(header, { relatedTarget: surface });
        fireEvent.pointerOver(surface, { relatedTarget: header });
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(shown()).toBe(surface);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a header label that is not cut shows no echo, on hover or on keyboard focus", async () => {
    vi.useFakeTimers();
    try {
      await mount(<Host />);
      act(() => {
        fireEvent.pointerOver(page.getByRole("columnheader", { name: "Accounts" }));
      });
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(shown()).toBeNull();
      act(() => page.getByRole("button", { name: "Name" }).focus());
      expect(shown()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a custom row's cut cell (`cut`) shows its whole words after CMP-016's 300 ms hover", async () => {
    vi.useFakeTimers();
    try {
      await mount(
        <Table<User>
          caption={CAPTION}
          columns={COLUMNS}
          rows={USERS}
          rowKey={(u) => u.id}
          renderRow={(u, grid) => (
            <tr {...grid.rowProps}>
              <th {...grid.cellProps(0, { header: true, cut: u.name })}>{u.name}</th>
              <td {...grid.cellProps(1, { numeric: true })}>{u.accounts}</td>
              <td {...grid.cellProps(2, { numeric: true })}>{u.pnl}</td>
            </tr>
          )}
        />,
      );
      expect(page.queryByRole("grid")).toBeNull();
      const alex = page.getByRole("rowheader", { name: "alex" });
      cutTo(alex, 90, 60);
      act(() => {
        fireEvent.pointerOver(alex);
      });
      act(() => {
        vi.advanceTimersByTime(300);
      });
      expect(shown()).toHaveTextContent("alex");
    } finally {
      vi.useRealTimers();
    }
  });
});

// Each story's play in jsdom (the storybook project runs them in Chromium, with axe): E08-D07's three; the rest predate this harness.
describe("Table stories", () => {
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      if (!["MergedCell", "SortUnavailable", "WindowedRows"].includes(name)) continue;
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });

  // The orchestrator's design read on #5146 (item 6): host text renders in the design-system font, never the serif.
  it("SortUnavailable's host note renders in the design-system font", async () => {
    const { SortUnavailable } = composeStories(stories);
    const host = await mount(<SortUnavailable />);
    const note = host.querySelector<HTMLElement>("#sort-note");
    expect(note?.closest<HTMLElement>('[style*="font-family"]')?.style.fontFamily).toContain(
      "var(--font-family-ui)",
    );
  });
});
