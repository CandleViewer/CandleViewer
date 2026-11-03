/**
 * E42-S08 (#1137) §10: a [Re-read] that answers the same rows draws no row again, even when its
 * slices' read time (`generated_at`, never more than 5 s old) moved, as it does on every real
 * re-read: the store keeps each field that reads the same, and the counters and the grid are
 * memoised on them (no per-answer render, as SCR-120's `overviewRerender`). `kindLabel` is wrapped
 * here to count the rows drawn (each counter row, each grid row and each rowless line calls it
 * once); the module mock is this file's alone.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as Kinds from "../../../../src/features/admin/statecharts/kinds";
import { InShellProvider } from "../../../../src/features/app-shell/ScreenRoot";
import { InspectorPage } from "../../../../src/features/admin/statecharts/InspectorPage";
import { inspector } from "../../../../src/features/admin/statecharts/inspectorStore";
import { WORLD_LIST } from "./fixtures";

const drawn = vi.hoisted(() => ({ labels: 0 }));
vi.mock("../../../../src/features/admin/statecharts/kinds", async (importOriginal) => {
  const real = await importOriginal<typeof Kinds>();
  return {
    ...real,
    kindLabel: (kind: string): string => {
      drawn.labels += 1;
      return real.kindLabel(kind);
    },
  };
});

let body: unknown = WORLD_LIST;

afterEach(() => {
  inspector.reset();
  vi.unstubAllGlobals();
});

/** `WORLD_LIST` as a re-read serves it at `at`: only the slices' read time moved. */
const readAt = (at: string) => ({
  ...WORLD_LIST,
  snapshots: { ...WORLD_LIST.snapshots, generated_at: at },
  metrics: { ...WORLD_LIST.metrics, generated_at: at },
});

describe("a re-read renders only what changed (§10)", () => {
  it("test_rerender_a_reread_that_moves_only_generated_at_draws_no_row", async () => {
    const requests: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        requests.push(String(input));
        return new Response(JSON.stringify(body), {
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    render(
      <MemoryRouter initialEntries={["/admin/statecharts"]}>
        <InShellProvider>
          <main>
            <InspectorPage />
          </main>
        </InShellProvider>
      </MemoryRouter>,
    );
    const grid = await screen.findByRole("grid", { name: "Machines" });
    await waitFor(() => expect(grid.querySelectorAll("tr[data-machine-row]")).toHaveLength(2));
    await act(async () => undefined);
    const settled = drawn.labels;
    expect(settled).toBeGreaterThan(0);
    body = readAt("2026-10-15T18:00:09Z");
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    await waitFor(() => expect(requests).toHaveLength(2));
    // "as of" moves with the read, and not one row is drawn again: the rows read the same.
    expect(await screen.findByText("All times UTC · as of 18:00:09")).toBeInTheDocument();
    await act(async () => undefined);
    expect(drawn.labels).toBe(settled);
    body = { ...WORLD_LIST, items: [WORLD_LIST.items[1]] };
    fireEvent.click(screen.getByRole("button", { name: "Re-read" }));
    await waitFor(() => expect(grid.querySelectorAll("tr[data-machine-row]")).toHaveLength(1));
    expect(drawn.labels).toBeGreaterThan(settled);
  });
});
