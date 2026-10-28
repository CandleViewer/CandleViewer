// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  EmptyState,
  Table,
  type MenuItem,
  type TableColumn,
  type TableProps,
  type TableSort,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

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
    expect(status()).toHaveTextContent("1 selected");
    await press(" ");
    expect(sam).toHaveAttribute("aria-selected", "false");
    expect(status()).toHaveTextContent("0 selected");
  });

  it("Space on a row's box toggles it once (natively), not twice", async () => {
    await mount(<GridHost />);
    act(() => target(1, 0).focus());
    await press(" ");
    expect(page.getByRole("checkbox", { name: "Select alex" })).toBeChecked();
    expect(status()).toHaveTextContent("1 selected");
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
    expect(status()).toHaveTextContent("3 selected");
    await userEvent.click(all);
    expect(all).not.toBeChecked();
    expect(all).not.toBePartiallyChecked();
    expect(status()).toHaveTextContent("0 selected");
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
