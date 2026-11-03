/**
 * E42-S04 (#1135), the build plan's §9: page 1's 30 s re-read (D5) must not re-render a row whose
 * data did not change. CMP-049 memoises no row, so the grid itself is memoised on stable props; this
 * file wraps CMP-173 to count each row's renders (the module mock is this file's alone).
 */
import { createElement, type JSX } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Ui from "@candleviewer/ui";
import { clearAnnouncements } from "../../../../src/features/app-shell/announcer";
import { auditIntegrity } from "../../../../src/features/admin/audit/integrity";
import { REREAD_MS } from "../../../../src/features/admin/audit/auditPageStore";
import { resetShellState } from "../../../../src/shell/bootstrap/store";
import { T0, entries, entry } from "./fixtures";
import { flush, mountAuditPage, pagesOf, sessionAs } from "./harness";

// The page renders CMP-049's grid, CMP-174 and the shell's announcer from the ui sources: a busy
// host can take seconds over a mount, as with SCR-120's page tests.
vi.setConfig({ testTimeout: 30_000 });

const renders = vi.hoisted(() => new Map<number, number>());
vi.mock("@candleviewer/ui", async (importOriginal) => {
  const ui = await importOriginal<typeof Ui>();
  function CountedRow(props: Ui.AuditRowProps | Ui.AuditRowGridProps): JSX.Element {
    if (props.variant === "row")
      renders.set(props.entry.id, (renders.get(props.entry.id) ?? 0) + 1);
    return createElement(ui.AuditRow, props);
  }
  return { ...ui, AuditRow: CountedRow };
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  renders.clear();
  clearAnnouncements();
  auditIntegrity.reset();
  sessionAs("owner");
});

afterEach(() => {
  auditIntegrity.reset();
  resetShellState();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("SCR-135's re-read renders only what changed (§9)", () => {
  it("test_rerender_unchanged_reread_renders_no_row_and_new_rows_only_the_pill", async () => {
    const page1 = entries(5);
    const page = await mountAuditPage({
      routes: { audit: pagesOf(page1, page1, [entry({ id: 1_204_301 }), ...page1]) },
    });
    const settled = new Map(renders);
    expect(settled.size).toBe(5);
    await flush(REREAD_MS); // the same rows: not one row renders again
    expect(page.reads()).toHaveLength(2);
    expect(renders).toEqual(settled);
    await flush(REREAD_MS); // a newer row: the pill appears; the rows shown stay as they were
    expect(page.reads()).toHaveLength(3);
    expect(renders).toEqual(settled);
    page.unmount();
  });
});
