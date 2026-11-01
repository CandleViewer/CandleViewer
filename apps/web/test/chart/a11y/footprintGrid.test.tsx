import { describe, expect, it } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useCompositeGrid } from "../../../src/chart/a11y/useCompositeGrid";
import { FootprintCellContent } from "../../../src/chart/a11y/marks";
import {
  footprintCellSentence,
  type FootprintCellFields,
} from "../../../src/chart/a11y/orderflowFormat";

/** A footprint surrogate as E18-S11 would host it: price levels are rows, bars are columns. */
function cellAt(row: number, col: number): FootprintCellFields {
  const delta = ((row + col) % 5) - 2;
  return {
    price: String(64020 - row),
    bid: String(10 + row),
    ask: String(10 + row + delta),
    delta: String(delta),
    imbalance: delta === 2 ? "ask" : delta === -2 ? "bid" : null,
  };
}

function Footprint({ rows, cols }: { rows: number; cols: number }): JSX.Element {
  const grid = useCompositeGrid({ rows, cols, page: "col", homeEnd: "col", windowRows: 12 });
  const drawn: JSX.Element[] = [];
  for (let r = grid.window.first; r <= grid.window.last; r++) {
    drawn.push(
      <div key={r} {...grid.rowProps(r)}>
        {Array.from({ length: cols }, (_, c) => (
          <div
            key={c}
            {...grid.cellProps(r, c)}
            aria-label={`bar ${c + 1}, ${footprintCellSentence(cellAt(r, c))}`}
          >
            <FootprintCellContent cell={cellAt(r, c)} />
          </div>
        ))}
      </div>,
    );
  }
  return (
    <div {...grid.gridProps} aria-label="Footprint">
      {drawn}
    </div>
  );
}

const focused = (): HTMLElement => document.activeElement as HTMLElement;
const press = (key: string): void => {
  fireEvent.keyDown(focused(), { key });
};

describe("footprint grid on the shared pattern (E18-S11's wording)", () => {
  it("arrows move price and time, PageUp/PageDown by bar, Home/End to the bar's first and last cell", () => {
    render(<Footprint rows={30} cols={6} />);
    const grid = screen.getByRole("grid", { name: "Footprint" });
    expect(grid).toHaveAttribute("aria-colcount", "6");
    act(() =>
      screen
        .getAllByRole("gridcell")
        .find((c) => c.tabIndex === 0)
        ?.focus(),
    );
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,020, /);
    press("ArrowDown");
    expect(focused()).toHaveAccessibleName(/^bar 1, 64,019, /);
    press("PageDown");
    expect(focused()).toHaveAccessibleName(/^bar 2, 64,019, /);
    press("ArrowRight");
    expect(focused()).toHaveAccessibleName(/^bar 3, 64,019, /);
    press("PageUp");
    expect(focused()).toHaveAccessibleName(/^bar 2, 64,019, /);
    press("End");
    expect(focused()).toHaveAccessibleName(/^bar 2, 63,991, /);
    expect(screen.getAllByRole("row").length).toBeLessThanOrEqual(12);
    press("Home");
    expect(focused()).toHaveAccessibleName(/^bar 2, 64,020, /);
    press("ArrowLeft");
    expect(focused().getAttribute("aria-colindex")).toBe("1");
    expect(screen.getAllByRole("gridcell").filter((c) => c.tabIndex === 0)).toEqual([focused()]);
  });

  it("Gherkin 3: a flagged cell says its imbalance as a word and draws the dashed pattern", () => {
    render(<Footprint rows={5} cols={5} />);
    const flagged = screen.getAllByRole("gridcell", { name: /ask imbalance$/ })[0] as HTMLElement;
    expect(flagged.querySelector("[data-cv-pattern='dashed']")).not.toBeNull();
    expect(flagged.textContent).toContain("Ask imbalance");
    const plain = screen.getAllByRole("gridcell", { name: /no imbalance$/ })[0] as HTMLElement;
    expect(plain.querySelector("[data-cv-pattern]")).toBeNull();
  });

  it("Gherkin 4: delta −2 and +2 render an explicit sign and glyph", () => {
    render(<Footprint rows={5} cols={5} />);
    const minus = screen.getAllByRole("gridcell", { name: /delta −2,/ })[0] as HTMLElement;
    const plus = screen.getAllByRole("gridcell", { name: /delta \+2,/ })[0] as HTMLElement;
    expect(minus.textContent).toContain("▼−2");
    expect(plus.textContent).toContain("▲+2");
  });
});
