// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import {
  EmptyState,
  Table,
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

  it("captionHidden hides the caption visually and still names the table", async () => {
    const host = await mount(base({ captionHidden: true }));
    expect(within(host).getByText(CAPTION)).toHaveClass("cv-visually-hidden");
    expect(within(host).getByRole("table", { name: CAPTION })).toBeInTheDocument();
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
