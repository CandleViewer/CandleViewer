// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import {
  AUDIT_DIFF_COPY,
  AuditDiff,
  AuditRow,
  AuditRowDiff,
  Table,
  auditColumns,
  auditDiffModel,
  auditGridRowKey,
  auditGridRows,
  type AuditGridRow,
  type AuditRowProps,
} from "../src/components/index.js";
import { AUDIT_MARKERS } from "../src/components/auditDiffModel.js";
import { seriousViolations } from "./axe.js";
import { holdEnter } from "./heldEnter.js";
import { mount } from "./theme/mount.js";

type Entry = AuditRowProps["entry"];

/** E42-D04's worked example (§1): alex's order on LIVE, a flag write, the failed tamper check's records. */
const ALEX = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
const ORDER: Entry = {
  id: 1204118,
  ts: "2026-10-22T14:01:50.212409+00:00",
  actor_user_id: ALEX,
  actor_username: "alex",
  action: "orders.submit",
  subject_type: "order",
  subject_id: "0c000000-0000-4000-8000-000000000001",
  subject_label: "BTCUSDT",
  outcome: "success",
  severity: "info",
  reason: "validated",
  environment: "live",
  ip: "100.84.12.9",
  detail: { before: null, after: { symbol: "BTCUSDT", side: "buy", note: "x".repeat(130) } },
  entry_hash: "3c9a5e2f1b",
  prev_hash: "7d1e0b44aa",
};
const FLAG: Entry = {
  ...ORDER,
  id: 1204117,
  ts: "2026-10-22T14:01:40.551203+00:00",
  actor_user_id: null,
  actor_username: "basiltt",
  action: "flags.change",
  subject_type: "feature_flag",
  subject_id: "trading.one_click",
  subject_label: null,
  severity: "warning",
  reason: null,
  detail: {
    before: { value: false, overrides: {}, description: "One-click" },
    after: { value: true, overrides: { [ALEX]: true }, description: "One-click", phase: "outcome" },
  },
};
const CRITICAL: Entry = {
  ...ORDER,
  id: 1204112,
  action: "security.key_policy_violation",
  actor_user_id: null,
  actor_username: "system:key-selfcheck",
  outcome: "failure",
  severity: "critical",
  detail: { before: null, after: { rule: "withdrawal_permission" } },
};

/** SCR-135's grid as the page holds it: expanded rows, the selected row and the drawer's opener. */
function Grid({
  entries,
  onOpen = () => undefined,
  onRowFocus,
  initialExpanded = [],
  selectedId,
  view,
  afterBreakId,
}: {
  readonly entries: readonly Entry[];
  readonly onOpen?: (id: number) => void;
  readonly onRowFocus?: (id: number) => void;
  readonly initialExpanded?: readonly number[];
  readonly selectedId?: number;
  readonly view?: "raw" | "own";
  readonly afterBreakId?: number;
}): JSX.Element {
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set(initialExpanded));
  const toggle = (id: number, open: boolean): void =>
    setExpanded((now) => {
      const next = new Set(now);
      if (open) next.add(id);
      else next.delete(id);
      return next;
    });
  return (
    <>
      <button type="button">Before</button>
      <Table<AuditGridRow>
        grid
        caption="Audit log, newest first. All times UTC. Role at the time is not recorded yet."
        columns={auditColumns()}
        rows={auditGridRows(entries, expanded)}
        rowKey={auditGridRowKey}
        renderRow={(row, grid) =>
          row.kind === "entry" ? (
            <AuditRow
              variant="row"
              grid={grid}
              entry={row.entry}
              diffId={`diff-${row.entry.id}`}
              expanded={expanded.has(row.entry.id)}
              onExpandedChange={(open) => toggle(row.entry.id, open)}
              onOpen={() => onOpen(row.entry.id)}
              selected={row.entry.id === selectedId}
              {...(view === undefined ? {} : { view })}
              {...(onRowFocus === undefined ? {} : { onRowFocus: () => onRowFocus(row.entry.id) })}
            />
          ) : (
            <AuditRowDiff
              grid={grid}
              entry={row.entry}
              id={`diff-${row.entry.id}`}
              onExpandedChange={(open) => toggle(row.entry.id, open)}
              onOpen={() => onOpen(row.entry.id)}
              {...(afterBreakId === undefined ? {} : { afterBreakId })}
            />
          )
        }
      />
      <button type="button">After</button>
    </>
  );
}

const page = within(document.body);
const gridEl = (): HTMLElement => page.getByRole("grid");
const rowOf = (id: number): HTMLElement => {
  const row = gridEl().querySelector<HTMLElement>(`tr[data-entry="${id}"]`);
  if (row === null) throw new Error(`no row ${id}`);
  return row;
};
const cells = (row: HTMLElement): HTMLElement[] =>
  [...row.children].filter((el): el is HTMLElement => el instanceof HTMLElement);
const expander = (id: number): HTMLElement =>
  within(rowOf(id)).getByRole("button", { name: `Record ${id.toLocaleString("en-US")}` });
const press = async (el: HTMLElement, key: string, init: KeyboardEventInit = {}): Promise<void> => {
  await act(async () => {
    el.dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
    );
  });
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("auditColumns and auditGridRows (E42-D04 §4 Columns, AL-3)", () => {
  it("names the nine columns after the 24 px expander, at their 1280 widths in em (944 px)", () => {
    const columns = auditColumns();
    expect(columns.map((c) => c.header)).toEqual([
      "Details",
      "Time",
      "Actor",
      "Role",
      "Action",
      "Target",
      "Environment",
      "IP",
      "Severity",
      "Result",
    ]);
    // Refitted to the pinned Inter and CMP-049's 8 px cell padding (A-5520-09): "Success" and the
    // "Environment" header fit whole; Target and IP give the room back, so the grid stays 944 px.
    expect(columns.map((c) => c.widthEm)).toEqual([1.5, 6.5, 9, 3.5, 8, 8, 5.75, 6.25, 6, 4.5]);
    expect(columns.reduce((sum, c) => sum + (c.widthEm ?? 0), 0) * 16).toBe(944);
    expect(columns.find((c) => c.id === "time")?.order).toBe("descending");
    expect(columns.filter((c) => c.order !== undefined)).toHaveLength(1);
  });

  it("hands out one column list, not a new array per call (a host may pass it on every render)", () => {
    expect(auditColumns()).toBe(auditColumns());
  });

  it("puts each expanded entry's diff row right under it, keyed apart", () => {
    const rows = auditGridRows([ORDER, FLAG, CRITICAL], new Set([FLAG.id]));
    expect(rows.map((r) => `${r.kind}:${r.entry.id}`)).toEqual([
      `entry:${ORDER.id}`,
      `entry:${FLAG.id}`,
      `diff:${FLAG.id}`,
      `entry:${CRITICAL.id}`,
    ]);
    expect(new Set(rows.map(auditGridRowKey)).size).toBe(4);
  });
});

describe("AuditRow (CMP-173), the grid row", () => {
  it("draws the cells in order: expander, time, actor, role, action, target, environment, IP, severity, result", async () => {
    await mount(<Grid entries={[ORDER]} />);
    const row = rowOf(ORDER.id);
    expect(row).toHaveAttribute("data-cmp", "CMP-173");
    expect(row).toHaveAttribute("data-variant", "row");
    expect(row).toHaveAttribute("aria-rowindex", "2");
    const [toggle, time, actor, role, action, target, env, ip, severity, result] = cells(row);
    expect(within(toggle as HTMLElement).getByRole("button")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(within(toggle as HTMLElement).getByRole("button")).not.toHaveAttribute("aria-controls");
    expect(time?.querySelector("time")).toHaveAttribute("datetime", "2026-10-22T14:01:50.212Z");
    expect(time).toHaveTextContent("2026-10-22 14:01:50.212");
    expect(actor).toHaveTextContent("alex");
    // The role at the time is not recorded (CG-1): "—" where it is narrow, the words for assistive technology.
    expect(role?.querySelector(".cv-visually-hidden, .cv-audit-row__long")).toHaveTextContent(
      "not recorded",
    );
    expect(action).toHaveTextContent("Order submitted");
    expect(action).toHaveTextContent("orders.submit");
    expect(target).toHaveTextContent("order · BTCUSDT");
    expect(env).toHaveTextContent("LIVE");
    // The chip keys on its own attribute, never the shell badge's `data-env` (CI-5520-01).
    expect(env?.querySelector(".cv-audit-row__env")).toHaveAttribute("data-audit-env", "live");
    expect(env?.querySelector("[data-env]")).toBeNull();
    expect(ip).toHaveTextContent("100.84.12.9");
    expect(severity).toHaveTextContent("Info");
    expect(result).toHaveTextContent("Success");
  });

  it("is one tab stop on the expander; the arrows move by cell and by row", async () => {
    await mount(<Grid entries={[ORDER, FLAG]} />);
    await userEvent.tab();
    await userEvent.tab();
    expect(expander(ORDER.id)).toHaveFocus();
    await press(expander(ORDER.id), "ArrowRight");
    expect(cells(rowOf(ORDER.id))[1]).toHaveFocus();
    await press(cells(rowOf(ORDER.id))[1] as HTMLElement, "ArrowDown");
    expect(cells(rowOf(FLAG.id))[1]).toHaveFocus();
    await press(cells(rowOf(FLAG.id))[1] as HTMLElement, "ArrowLeft");
    expect(expander(FLAG.id)).toHaveFocus();
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
  });

  it("Space expands from any cell, once per press; the diff row follows, the expander controlling it", async () => {
    await mount(<Grid entries={[ORDER, FLAG]} />);
    const cell = cells(rowOf(FLAG.id))[2] as HTMLElement;
    await act(async () => cell.focus());
    await press(cell, " ");
    await press(cell, " ", { repeat: true });
    const button = expander(FLAG.id);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("aria-controls", `diff-${FLAG.id}`);
    const diff = document.getElementById(`diff-${FLAG.id}`);
    expect(diff?.tagName).toBe("TR");
    expect(diff).toHaveAttribute("aria-rowindex", "4");
    expect(rowOf(FLAG.id).nextElementSibling).toBe(diff);
    await press(cell, " ");
    expect(expander(FLAG.id)).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(`diff-${FLAG.id}`)).toBeNull();
  });

  it("the expander toggles on a press; Enter on any cell opens the record, once per press", async () => {
    const onOpen = vi.fn();
    await mount(<Grid entries={[ORDER]} onOpen={onOpen} />);
    await userEvent.click(expander(ORDER.id));
    expect(expander(ORDER.id)).toHaveAttribute("aria-expanded", "true");
    expect(onOpen).not.toHaveBeenCalled();
    holdEnter(expander(ORDER.id), 3);
    expect(onOpen.mock.calls).toEqual([[ORDER.id]]);
    // Enter opened the record; it did not toggle the row.
    expect(expander(ORDER.id)).toHaveAttribute("aria-expanded", "true");
    await press(cells(rowOf(ORDER.id))[4] as HTMLElement, "Enter");
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("a press on a cell opens the record; one ending a text selection does not", async () => {
    const onOpen = vi.fn();
    await mount(<Grid entries={[ORDER]} onOpen={onOpen} />);
    await userEvent.click(cells(rowOf(ORDER.id))[3] as HTMLElement);
    expect(onOpen).toHaveBeenCalledTimes(1);
    vi.spyOn(document, "getSelection").mockReturnValue({
      isCollapsed: false,
      toString: () => "alex",
    } as unknown as Selection);
    await act(async () => void fireEvent.click(cells(rowOf(ORDER.id))[2] as HTMLElement));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("D2: error and critical are high (the octagon, hidden), warning the triangle; the words carry it", async () => {
    await mount(<Grid entries={[CRITICAL, FLAG, ORDER]} />);
    const glyph = (id: number): string | undefined =>
      cells(rowOf(id))[8]?.querySelector<HTMLElement>("[data-glyph]")?.dataset["glyph"];
    expect([glyph(CRITICAL.id), glyph(FLAG.id), glyph(ORDER.id)]).toEqual([
      "danger",
      "warning",
      undefined,
    ]);
    expect(rowOf(CRITICAL.id)).toHaveAttribute("data-severity", "critical");
    expect(cells(rowOf(CRITICAL.id))[8]?.querySelector("svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(cells(rowOf(CRITICAL.id))[8]).toHaveTextContent("Critical");
  });

  it("D3: a write-ahead record reads Started or Intent, never Success", async () => {
    const started: Entry = {
      ...ORDER,
      id: 1204115,
      action: "admin.audit_verify",
      reason: "started",
    };
    const intent: Entry = {
      ...FLAG,
      id: 1204114,
      detail: { before: {}, after: { value: true, phase: "intent" } },
    };
    await mount(<Grid entries={[started, intent]} />);
    expect(cells(rowOf(started.id))[9]).toHaveTextContent("Started");
    expect(cells(rowOf(intent.id))[9]).toHaveTextContent("Intent");
  });

  it("a system actor reads as recorded; a deleted user's pseudonym is cut to 4 hex, its whole words kept", async () => {
    const deleted: Entry = { ...ORDER, id: 1204100, actor_username: "deleted-user-3f9a1c2b7e04" };
    await mount(<Grid entries={[CRITICAL, deleted]} />);
    expect(cells(rowOf(CRITICAL.id))[2]).toHaveTextContent("system:key-selfcheck");
    const actor = cells(rowOf(deleted.id))[2] as HTMLElement;
    expect(actor.querySelector("[aria-hidden='true']")).toHaveTextContent("deleted-user-3f9a…");
    expect(actor.querySelector(".cv-visually-hidden")).toHaveTextContent(
      "deleted-user-3f9a1c2b7e04",
    );
    expect(actor).toHaveAttribute("data-cv-echo", "deleted-user-3f9a1c2b7e04");
    expect(actor.querySelector("a")).toBeNull();
  });

  it("the own view: Environment and IP read 'not shown in your view'; the diff 'Not shown in your view'", async () => {
    const projected: Entry = {
      ...ORDER,
      environment: null,
      ip: null,
      detail: {},
      entry_hash: null,
      prev_hash: null,
    };
    await mount(<Grid entries={[projected]} view="own" initialExpanded={[projected.id]} />);
    expect(cells(rowOf(projected.id))[6]).toHaveTextContent("not shown in your view");
    expect(cells(rowOf(projected.id))[7]).toHaveTextContent("not shown in your view");
    expect(document.getElementById(`diff-${projected.id}`)).toHaveTextContent(
      AUDIT_DIFF_COPY.hidden,
    );
  });

  it("an Owner's empty environment and IP read '—'", async () => {
    await mount(<Grid entries={[{ ...ORDER, environment: null, ip: null }]} />);
    expect(cells(rowOf(ORDER.id))[6]).toHaveTextContent("—");
    expect(cells(rowOf(ORDER.id))[7]).toHaveTextContent("—");
  });

  it("an absent actor, target, environment or IP: the dash is hidden, 'not recorded' read beside it", async () => {
    const bare: Entry = {
      ...ORDER,
      actor_username: null,
      subject_type: null,
      subject_id: null,
      subject_label: null,
      environment: null,
      ip: null,
    };
    await mount(<Grid entries={[bare]} />);
    for (const index of [2, 5, 6, 7]) {
      const cell = cells(rowOf(bare.id))[index] as HTMLElement;
      expect(cell.querySelector("[aria-hidden='true']"), `cell ${index}`).toHaveTextContent("—");
      expect(cell.querySelector(".cv-visually-hidden"), `cell ${index}`).toHaveTextContent(
        "not recorded",
      );
    }
  });

  it("onRowFocus: focus entering a row hands the host its record (D14)", async () => {
    const onRowFocus = vi.fn();
    await mount(<Grid entries={[ORDER, FLAG]} onRowFocus={onRowFocus} />);
    await act(async () => (cells(rowOf(ORDER.id))[1] as HTMLElement).focus());
    await press(cells(rowOf(ORDER.id))[1] as HTMLElement, "ArrowDown");
    expect(cells(rowOf(FLAG.id))[1]).toHaveFocus();
    expect(onRowFocus).toHaveBeenCalledWith(ORDER.id);
    expect(onRowFocus).toHaveBeenLastCalledWith(FLAG.id);
  });

  it("D14: the selected row is aria-selected with the check glyph before the chevron", async () => {
    await mount(<Grid entries={[ORDER, FLAG]} selectedId={FLAG.id} />);
    expect(rowOf(FLAG.id)).toHaveAttribute("aria-selected", "true");
    expect(rowOf(ORDER.id)).not.toHaveAttribute("aria-selected");
    const glyphs = [
      ...(cells(rowOf(FLAG.id))[0]?.querySelectorAll<HTMLElement>("[data-glyph]") ?? []),
    ];
    expect(glyphs.map((g) => g.dataset["glyph"])).toEqual(["check", "chevron-right"]);
  });

  it("has no control to edit, delete, archive, correct, repair or re-hash a record", async () => {
    await mount(<Grid entries={[ORDER, FLAG, CRITICAL]} initialExpanded={[FLAG.id, ORDER.id]} />);
    const names = page.queryAllByRole("button").map((b) => b.textContent ?? "");
    expect(names.join(" | ")).not.toMatch(/edit|delete|archive|correct|repair|re-hash/i);
  });

  it("has no serious or critical axe violation, a row expanded and one selected", async () => {
    const host = await mount(
      <Grid entries={[ORDER, FLAG, CRITICAL]} initialExpanded={[FLAG.id]} selectedId={ORDER.id} />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("AuditRowDiff (CMP-173's diff row, AL-3)", () => {
  it("is one full-width cell; → walks its Copy and disclosures, ← returns, ↓ leaves for the next row", async () => {
    await mount(<Grid entries={[ORDER, FLAG]} initialExpanded={[ORDER.id]} />);
    const diff = document.getElementById(`diff-${ORDER.id}`) as HTMLElement;
    const [cell] = cells(diff);
    expect(cells(diff)).toHaveLength(1);
    expect(cell).toHaveAttribute("colspan", "10");
    await act(async () => cell?.focus());
    const full = within(cell as HTMLElement).getByRole("button", {
      name: "Show full value of note (After)",
    });
    expect(full).toHaveAttribute("tabindex", "-1");
    await press(cell as HTMLElement, "ArrowRight");
    expect(full).toHaveFocus();
    await press(full, "ArrowLeft");
    expect(cell).toHaveFocus();
    await press(cell as HTMLElement, "ArrowRight");
    await press(full, "ArrowDown");
    expect(cells(rowOf(FLAG.id))[0]?.querySelector("button")).toHaveFocus();
  });

  it("Enter on the diff row opens its entry's record, once per press", async () => {
    const onOpen = vi.fn();
    await mount(<Grid entries={[ORDER]} initialExpanded={[ORDER.id]} onOpen={onOpen} />);
    const cell = cells(
      document.getElementById(`diff-${ORDER.id}`) as HTMLElement,
    )[0] as HTMLElement;
    await act(async () => cell.focus());
    await press(cell, "Enter");
    await press(cell, "Enter", { repeat: true });
    expect(onOpen.mock.calls).toEqual([[ORDER.id]]);
    expect(document.getElementById(`diff-${ORDER.id}`)).not.toBeNull();
  });

  it("Space on the diff row collapses it and leaves focus on its entry's expander", async () => {
    await mount(<Grid entries={[ORDER]} initialExpanded={[ORDER.id]} />);
    const cell = cells(
      document.getElementById(`diff-${ORDER.id}`) as HTMLElement,
    )[0] as HTMLElement;
    await act(async () => cell.focus());
    await press(cell, " ");
    expect(document.getElementById(`diff-${ORDER.id}`)).toBeNull();
    expect(expander(ORDER.id)).toHaveFocus();
  });

  it("AD-5: an entry at or after the break says so in its expanded row, in the danger treatment", async () => {
    const after: Entry = { ...ORDER, id: 1204118 };
    const before: Entry = { ...FLAG, id: 1204000 };
    await mount(
      <Grid
        entries={[after, before]}
        initialExpanded={[after.id, before.id]}
        afterBreakId={1204118}
      />,
    );
    const line = "Not verified — at or after the break at entry 1,204,118.";
    expect(document.getElementById(`diff-${after.id}`)).toHaveTextContent(line);
    expect(document.getElementById(`diff-${before.id}`)).not.toHaveTextContent(line);
    // Never in the collapsed row: the incident banner covers the whole log.
    expect(rowOf(after.id)).not.toHaveTextContent("Not verified");
  });
});

describe("AuditDiff (CMP-173's diff part, E42-D04 §6)", () => {
  const full = (entry: Entry): Promise<HTMLElement> =>
    mount(<AuditDiff model={auditDiffModel(entry)} form="full" />);

  it("full: a dl per changed field, its path the term, a nested dl with Before and After", async () => {
    const host = await full(FLAG);
    const [value] = host.querySelectorAll(".cv-audit-diff__field");
    expect(value?.querySelector("dt")).toHaveTextContent("Changed value");
    const terms = [...(value?.querySelectorAll("dd dt") ?? [])].map((t) => t.textContent);
    expect(terms).toEqual(["Before", "After"]);
    expect(value?.querySelector("dd")).toHaveTextContent("BeforeOFFAfterON");
    expect(host).toHaveTextContent(`Added overrides › ${ALEX}`);
    expect(host.querySelector("dl")?.tagName).toBe("DL");
  });

  it("folds the unchanged fields into a disclosure that shows them on a press", async () => {
    const host = await full(FLAG);
    const toggle = within(host).getByRole("button", { name: "1 unchanged field" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(host).not.toHaveTextContent("One-click");
    // Collapsed, the list it controls is hidden, never an empty list in the tree (A-5520-15).
    const list = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(list).toHaveAttribute("hidden");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(list).not.toHaveAttribute("hidden");
    expect(list).toHaveTextContent("One-click");
  });

  it("cuts a long value at 120 characters and shows it whole on a press of Show full value", async () => {
    const host = await full(ORDER);
    expect(host).not.toHaveTextContent("x".repeat(121));
    expect(host).toHaveTextContent("x".repeat(120));
    await userEvent.click(
      within(host).getByRole("button", { name: "Show full value of note (After)" }),
    );
    expect(host).toHaveTextContent("x".repeat(130));
  });

  it("request: the head, Requested never After, no status word; the request's facts", async () => {
    const refused: Entry = {
      ...FLAG,
      outcome: "failure",
      reason: "credential_in_reason",
      detail: {
        before: { value: false },
        after: {
          value: true,
          overrides: null,
          reason: AUDIT_MARKERS.credential,
          result: "credential_in_reason",
        },
      },
    };
    const host = await full(refused);
    expect(host).toHaveTextContent("Not applied — credential_in_reason");
    expect(host).toHaveTextContent("Requested");
    expect([...host.querySelectorAll("dt")].map((t) => t.textContent)).not.toContain("After");
    expect(host).not.toHaveTextContent(/Changed|Added|Removed/);
    expect(host).toHaveTextContent("not sent — the existing overrides stay");
    expect(host).toHaveTextContent("Redacted — it held a credential");
  });

  it("the redacted kinds show their words and no value; a hashed value its first 8 hex", async () => {
    const entry: Entry = {
      ...ORDER,
      detail: {
        before: null,
        after: {
          note: AUDIT_MARKERS.secret,
          password: "unredacted",
          email: `${AUDIT_MARKERS.personal}a3f1c2d4e5b60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90`,
          body: AUDIT_MARKERS.oversize,
        },
      },
    };
    const host = await full(entry);
    for (const words of [
      AUDIT_DIFF_COPY.secret,
      AUDIT_DIFF_COPY.secret_named,
      "Personal data, hashed · a3f1c2d4…",
      AUDIT_DIFF_COPY.oversize,
    ]) {
      expect(host).toHaveTextContent(words);
    }
    expect(host).not.toHaveTextContent("unredacted");
    expect(host.textContent).not.toContain("redacted:");
    expect(host.textContent).not.toContain("hashed:pii");
    expect(host.textContent).not.toContain("e5b60718293a4b5c6d7e8f90");
  });

  it("a fingerprint and an identifier: in mono with Copy; the identifier with its note", async () => {
    const entry: Entry = {
      ...ORDER,
      detail: {
        before: null,
        after: { key_id_masked: "ab12…9f", key_id: "cv-audit-export-v2:0011223344556677" },
      },
    };
    const host = await full(entry);
    expect(within(host).getByRole("button", { name: "Copy key_id_masked (After)" })).toBeVisible();
    expect(within(host).getByRole("button", { name: "Copy key_id (After)" })).toBeVisible();
    expect(host).toHaveTextContent(AUDIT_DIFF_COPY.key_id_note);
  });

  it("names each Show full value and Copy by its field and side, never two alike (WCAG 2.4.6)", async () => {
    const entry: Entry = {
      ...FLAG,
      detail: {
        before: { note: "a".repeat(130), sha256: "a".repeat(64) },
        after: { note: "b".repeat(130), sha256: "b".repeat(64) },
      },
    };
    const host = await full(entry);
    for (const name of [
      "Show full value of note (Before)",
      "Show full value of note (After)",
      "Copy sha256 (Before)",
      "Copy sha256 (After)",
    ]) {
      expect(within(host).getAllByRole("button", { name }), name).toHaveLength(1);
    }
    // The visible words lead the name (WCAG 2.5.3).
    for (const button of within(host).getAllByRole("button", { name: /^Show full value of / })) {
      expect(button).toHaveTextContent(AUDIT_DIFF_COPY.full);
    }
    // A recorded key is data: replacement patterns in it stay as written.
    const odd = await full({
      ...ORDER,
      detail: { before: null, after: { "a$&b": "x".repeat(130) } },
    });
    expect(
      within(odd).getByRole("button", { name: "Show full value of a$&b (After)" }),
    ).toBeVisible();
  });

  it("a withheld state reads Withheld once under Before while After lists the served fields", async () => {
    const entry: Entry = {
      ...FLAG,
      detail: { before: null, after: { value: true }, elided: ["before"] },
    };
    const host = await full(entry);
    expect(within(host).getAllByText(AUDIT_DIFF_COPY.withheld)).toHaveLength(1);
    expect(host).toHaveTextContent("ON");
    expect(host).not.toHaveTextContent(/Changed|Added|Removed/);
  });

  it("withheld beside a request: the second term is Requested, never After, and its facts stay (§6)", async () => {
    const refused: Entry = {
      ...FLAG,
      outcome: "failure",
      reason: "credential_in_reason",
      detail: {
        before: null,
        after: { value: true, reason: AUDIT_MARKERS.credential, result: "credential_in_reason" },
        elided: ["before"],
      },
    };
    const host = await full(refused);
    expect(host).toHaveTextContent("Not applied — credential_in_reason");
    expect(within(host).getAllByText(AUDIT_DIFF_COPY.withheld)).toHaveLength(1);
    const terms = [...host.querySelectorAll("dt")].map((t) => t.textContent);
    expect(terms).not.toContain("After");
    expect(terms).toEqual(
      expect.arrayContaining(["Before", "Requested", "value", "reason", "result"]),
    );
    expect(host).toHaveTextContent(AUDIT_DIFF_COPY.credential);
  });

  it("withheld beside a result: the result's fields stay, as values (§6)", async () => {
    const verify: Entry = {
      ...ORDER,
      action: "admin.audit_verify",
      subject_type: null,
      outcome: "failure",
      detail: {
        before: null,
        after: { from_id: 204119, to_id: 1204118, verified: false },
        elided: ["before"],
      },
    };
    const host = await full(verify);
    expect(host).toHaveTextContent(AUDIT_DIFF_COPY.result);
    expect(within(host).getAllByText(AUDIT_DIFF_COPY.withheld)).toHaveLength(1);
    const terms = [...host.querySelectorAll("dt")].map((t) => t.textContent);
    expect(terms).toEqual(expect.arrayContaining(["from_id", "to_id", "verified"]));
    expect(host).toHaveTextContent("1,204,118");
  });

  it("a result: Recorded result, no earlier state, its fields as values; a write-ahead one Started", async () => {
    const verify: Entry = {
      ...ORDER,
      action: "admin.audit_verify",
      subject_type: null,
      outcome: "failure",
      detail: { before: null, after: { from_id: 204119, to_id: 1204118, verified: false } },
    };
    const host = await mount(
      <>
        <AuditDiff model={auditDiffModel(verify)} form="full" />
        <AuditDiff
          model={auditDiffModel({ ...verify, reason: "started", outcome: "success" })}
          form="full"
        />
      </>,
    );
    const [done, started] = [...host.querySelectorAll<HTMLElement>(".cv-audit-diff")];
    expect(done).toHaveTextContent(AUDIT_DIFF_COPY.result);
    expect(done).toHaveTextContent(AUDIT_DIFF_COPY.no_before);
    expect(done).toHaveTextContent("1,204,118");
    expect(started).toHaveTextContent(AUDIT_DIFF_COPY.head_started);
  });

  it("inline: one line per field, the arrow hidden, read as 'changed from OFF to ON'", async () => {
    const refused = auditDiffModel({
      ...FLAG,
      outcome: "failure",
      reason: "credential_in_reason",
      detail: { before: { value: false }, after: { value: true } },
    });
    const host = await mount(
      <>
        <AuditDiff model={auditDiffModel(FLAG)} form="inline" />
        <AuditDiff model={refused} form="inline" />
      </>,
    );
    const [state, request] = [...host.querySelectorAll<HTMLElement>(".cv-audit-diff")];
    const line = within(state as HTMLElement).getAllByRole("listitem")[0] as HTMLElement;
    expect(line.querySelector("[aria-hidden='true']")).toHaveTextContent("OFF → ON");
    expect(line).toHaveTextContent("changed from OFF to ON");
    expect(request).toHaveTextContent("value: requested ON (stored OFF)");
  });

  it("has no serious or critical axe violation in either form", async () => {
    const host = await mount(
      <>
        <AuditDiff model={auditDiffModel(FLAG)} form="full" />
        <AuditDiff model={auditDiffModel(FLAG)} form="inline" />
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});
