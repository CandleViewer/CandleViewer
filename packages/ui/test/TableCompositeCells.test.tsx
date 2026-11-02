// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Table, type TableColumn, type TableRowContext } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

/** A list whose second row is a detail row: one cell over every column holding two buttons (E42-D04 AL-3). */
type Row = { readonly id: string; readonly kind: "item" | "detail" };
const ROWS: readonly Row[] = [
  { id: "a", kind: "item" },
  { id: "a-detail", kind: "detail" },
  { id: "b", kind: "item" },
];
const COLUMNS: readonly TableColumn<Row>[] = [
  { id: "open", header: "Open", cell: () => "" },
  { id: "time", header: "Time", cell: (r) => r.id, order: "descending" },
  { id: "name", header: "Name", cell: (r) => r.id },
];

const onCopy = vi.fn();
const onMore = vi.fn();

const renderRow = (row: Row, grid: TableRowContext): JSX.Element =>
  row.kind === "item" ? (
    <tr {...grid.rowProps} data-row={row.id}>
      <td {...grid.cellProps(0, { widget: true })}>
        <button type="button" tabIndex={grid.tabIndexOf(0)} aria-expanded="false">
          Toggle {row.id}
        </button>
      </td>
      <td {...grid.cellProps(1)}>{row.id} time</td>
      <td {...grid.cellProps(2)}>{row.id} name</td>
    </tr>
  ) : (
    <tr {...grid.rowProps} data-row={row.id}>
      <td {...grid.cellProps(0, { span: COLUMNS.length, composite: true })}>
        Detail{" "}
        <button type="button" onClick={onCopy}>
          Copy
        </button>{" "}
        <button type="button" onClick={onMore}>
          More
        </button>
      </td>
    </tr>
  );

function Host(): JSX.Element {
  return (
    <>
      <button type="button">Before</button>
      <Table<Row>
        grid
        caption="Entries"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        renderRow={renderRow}
      />
      <button type="button">After</button>
    </>
  );
}

const page = within(document.body);
const row = (id: string): HTMLElement => {
  const el = document.querySelector<HTMLElement>(`tr[data-row="${id}"]`);
  if (el === null) throw new Error(`no row ${id}`);
  return el;
};
const press = async (el: Element, key: string, init: KeyboardEventInit = {}): Promise<void> => {
  await act(async () => {
    el.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
    );
  });
};
const button = (name: string): HTMLElement => page.getByRole("button", { name });

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  onCopy.mockReset();
  onMore.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("Table (CMP-049): a column's fixed order (E42-D04 D6)", () => {
  it("states the order with aria-sort and its arrow, and offers no button to change it", async () => {
    await mount(<Host />);
    const headers = page.getAllByRole("columnheader");
    const time = headers.find((h) => h.textContent?.startsWith("Time"));
    expect(time).toHaveAttribute("aria-sort", "descending");
    expect(time?.querySelector("button")).toBeNull();
    expect(time?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(headers.filter((h) => h.hasAttribute("aria-sort"))).toEqual([time]);
  });
});

describe("Table (CMP-049): a custom row's widget cell", () => {
  it("lends its tab stop to its one control; the arrows land on the control", async () => {
    await mount(<Host />);
    const cell = row("a").children[0] as HTMLElement;
    expect(cell).not.toHaveAttribute("tabindex");
    expect(cell).toHaveAttribute("data-cv-widget");
    await userEvent.tab();
    await userEvent.tab();
    expect(button("Toggle a")).toHaveFocus();
    expect(button("Toggle a")).toHaveAttribute("tabindex", "0");
    expect(button("Toggle b")).toHaveAttribute("tabindex", "-1");
    await press(button("Toggle a"), "ArrowRight");
    expect(row("a").children[1]).toHaveFocus();
    await press(row("a").children[1] as HTMLElement, "ArrowLeft");
    expect(button("Toggle a")).toHaveFocus();
  });
});

describe("Table (CMP-049): a custom row's composite cell", () => {
  it("keeps its own stop; its controls leave the Tab order while the grid roves", async () => {
    await mount(<Host />);
    const cell = row("a-detail").children[0] as HTMLElement;
    expect(cell).toHaveAttribute("colspan", "3");
    expect(cell).toHaveAttribute("data-cv-composite");
    expect(cell).toHaveAttribute("tabindex", "-1");
    expect(button("Copy")).toHaveAttribute("tabindex", "-1");
    expect(button("More")).toHaveAttribute("tabindex", "-1");
  });

  it("→ walks into its controls and between them, ← walks back to the cell; the ends stay", async () => {
    await mount(<Host />);
    await press(button("Toggle a"), "ArrowDown");
    const cell = row("a-detail").children[0] as HTMLElement;
    expect(cell).toHaveFocus();
    await press(cell, "ArrowRight");
    expect(button("Copy")).toHaveFocus();
    await press(button("Copy"), "ArrowRight");
    expect(button("More")).toHaveFocus();
    await press(button("More"), "ArrowRight");
    expect(button("More")).toHaveFocus();
    await press(button("More"), "ArrowLeft");
    await press(button("Copy"), "ArrowLeft");
    expect(cell).toHaveFocus();
  });

  it("↑ and ↓ from a control leave the row as from the cell; Esc returns to the cell", async () => {
    await mount(<Host />);
    await press(button("Toggle a"), "ArrowDown");
    const cell = row("a-detail").children[0] as HTMLElement;
    await press(cell, "ArrowRight");
    await press(button("Copy"), "ArrowDown");
    expect(button("Toggle b")).toHaveFocus();
    await press(button("Toggle b"), "ArrowUp");
    await press(cell, "ArrowRight");
    await press(button("Copy"), "ArrowUp");
    expect(button("Toggle a")).toHaveFocus();
    await press(button("Toggle a"), "ArrowDown");
    await press(cell, "ArrowRight");
    await press(button("Copy"), "Escape");
    expect(cell).toHaveFocus();
  });

  it("a control's own keys stay its own: Enter and Space act on it", async () => {
    await mount(<Host />);
    await press(button("Toggle a"), "ArrowDown");
    await press(row("a-detail").children[0] as HTMLElement, "ArrowRight");
    await userEvent.keyboard("{Enter}");
    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(button("Copy")).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(onCopy).toHaveBeenCalledTimes(2);
    expect(button("Copy")).toHaveFocus();
    expect(button("Toggle a")).toHaveAttribute("aria-expanded", "false");
  });

  // C-5520-05: a disclosure inside the cell mounts its controls later, while focus is already in the cell and the
  // table itself does not render again; they leave the Tab order too, so the grid keeps one Tab stop.
  it("a control that mounts later inside it leaves the Tab order too", async () => {
    function More(): JSX.Element {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" aria-expanded={open} onClick={() => setOpen(true)}>
            Show more
          </button>
          {open ? <button type="button">Late</button> : null}
        </>
      );
    }
    await mount(
      <Table<Row>
        grid
        caption="Entries"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        renderRow={(r, grid) =>
          r.kind === "detail" ? (
            <tr {...grid.rowProps} data-row={r.id}>
              <td {...grid.cellProps(0, { span: COLUMNS.length, composite: true })}>
                <More />
              </td>
            </tr>
          ) : (
            renderRow(r, grid)
          )
        }
      />,
    );
    const cell = row("a-detail").children[0] as HTMLElement;
    await act(async () => cell.focus());
    await press(cell, "ArrowRight");
    expect(button("Show more")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    const late = button("Late");
    await waitFor(() => expect(late).toHaveAttribute("tabindex", "-1"));
    await press(button("Show more"), "ArrowRight");
    expect(late).toHaveFocus();
  });
});
