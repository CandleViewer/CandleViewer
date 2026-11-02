import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import {
  AuditRow,
  AuditRowDiff,
  AuditRowList,
  auditColumns,
  auditGridRowKey,
  auditGridRows,
  type AuditGridRow,
  type AuditRowProps,
} from "./AuditRow.js";
import { AUDIT_MARKERS } from "./auditDiffModel.js";
import { Table } from "./Table.js";

type Entry = AuditRowProps["entry"];

/** The user ids of E42-D03's worked example: Owner basiltt and manager alex. */
const BASILTT = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001";
const ALEX = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";

/**
 * E42-D03's worked example (2026-10-22). Each actor label is the one its writer records. A compact row never
 * reads the hashes, the IP or the `detail` diff, so they stay null or empty; the first row's IP is set to show
 * it never shows.
 */
const entry = (id: number, ts: string, action: string, fields: Partial<Entry> = {}): Entry => ({
  id,
  ts,
  action,
  actor_user_id: BASILTT,
  actor_username: "basiltt",
  subject_type: null,
  subject_id: null,
  outcome: "success",
  severity: "info",
  detail: {},
  entry_hash: null,
  prev_hash: null,
  ...fields,
});

const AREA = entry(1204120, "2026-10-22T14:02:11.204816+00:00", "admin.area_entered", {
  subject_type: "admin_route",
  subject_id: "/admin/overview",
  ip: "100.84.12.9",
});
/** OMS records name the actor by role, `user:<role>` (`21`'s `actor_label`). */
const ORDER = entry(1204119, "2026-10-22T14:01:50.114Z", "orders.submit", {
  actor_user_id: ALEX,
  actor_username: "user:manager",
  subject_type: "order",
  subject_label: "BTCUSDT",
});
const FLAG = entry(1204118, "2026-10-22T14:01:40.551203+00:00", "flags.change", {
  subject_type: "feature_flag",
  subject_id: "trading.one_click",
});
/** `rbac.denied` records its actor's user id as the label, not the username (E42-D04 AL-25). */
const DENIED = entry(1204117, "2026-10-22T13:59:12.007311+00:00", "rbac.denied", {
  actor_user_id: ALEX,
  actor_username: ALEX,
  outcome: "denied",
  severity: "warning",
  reason: "missing_permission:users:write:none",
});
const ELIDED = entry(1204116, "2026-10-22T13:58:03.900412+00:00", "admin.audit_export", {
  subject_type: "job",
  subject_id: "0c000000-0000-4000-8000-000000000002",
  detail: { before: null, after: null, elided: ["after"] },
});
const CRITICAL = entry(
  1204112,
  "2026-10-22T13:50:41.310925+00:00",
  "security.key_policy_violation",
  {
    actor_user_id: null,
    actor_username: "system:key-selfcheck",
    subject_label: "sub_002",
    outcome: "failure",
    severity: "critical",
  },
);
const ERROR = entry(1204111, "2026-10-22T04:00:12.552030+00:00", "backup.run", {
  actor_user_id: null,
  actor_username: "system:backups",
  subject_label: "pg_basebackup",
  outcome: "failure",
  severity: "error",
});
/** A tamper check's write-ahead record (`reason: started`), written before the run has an outcome. */
const STARTED = entry(1204115, "2026-10-22T13:55:00.120044+00:00", "admin.audit_verify", {
  reason: "started",
  detail: { before: null, after: { from_id: 1, to_id: 1204114 } },
});
/** A flag write's intent record (`detail.after.phase: intent`), written before the store answers. */
const INTENT = entry(1204114, "2026-10-22T13:54:31.802117+00:00", "flags.change", {
  subject_type: "feature_flag",
  subject_id: "trading.one_click",
  detail: { before: { value: false }, after: { value: true, phase: "intent" } },
});
/** System actors, by the labels their writers record (`admin/flags/maintenance.py`, `audit/writer.py`). */
const MAINTENANCE = entry(1204110, "2026-10-22T03:58:00.004113+00:00", "maintenance.enabled", {
  actor_user_id: null,
  actor_username: "system:maintenance",
  subject_type: "feature_flag",
  subject_id: "maintenance.mode",
  severity: "warning",
});
const LANE = entry(1204001, "2026-10-22T00:00:03.017502+00:00", "audit.lane_started", {
  actor_user_id: null,
  actor_username: "system:audit-lane",
  subject_type: "audit_lane",
});

/** The rows in an Audit tile's width (275 px at 1280, board 09) on its `surface.raised` fill. */
function Tile({ rows }: { rows: readonly Entry[] }): JSX.Element {
  return (
    <div
      style={{
        maxWidth: "17.25rem",
        padding: "var(--space-inset-sm)",
        background: "var(--color-surface-raised)",
        color: "var(--color-text-primary)",
        font: "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)",
      }}
    >
      <AuditRowList aria-label="Latest audit entries">
        {rows.map((row) => (
          <AuditRow key={row.id} entry={row} variant="compact" href={`#audit-${row.id}`} />
        ))}
      </AuditRowList>
    </div>
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Tile> = {
  title: "Molecules/AuditRow",
  component: Tile,
  args: { rows: [AREA, ORDER, FLAG] },
};
export default meta;
type Story = StoryObj<typeof Tile>;

const links = (canvas: HTMLElement): HTMLElement[] => within(canvas).getAllByRole("link");

/** The Audit tile's three latest entries (D9): a list of links, each read in words. */
export const Compact: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getAllByRole("listitem")).toHaveLength(3);
    await expect(links(canvasElement)[0]).toHaveAccessibleName(
      "2026-10-22 14:02:11 UTC · basiltt · Area entered (admin.area_entered) · /admin/overview · Success · Info",
    );
    await expect(canvasElement).not.toHaveTextContent("100.84.12.9");
  },
};

/**
 * A denial reads "Denied" (D27: denials are `rbac.denied`) and its actor is the user id the denial records; an
 * entry with no subject leaves it out.
 */
export const CompactDenied: Story = {
  args: { rows: [DENIED] },
  play: async ({ canvasElement }) => {
    await expect(links(canvasElement)[0]).toHaveAccessibleName(
      `2026-10-22 13:59:12 UTC · ${ALEX} · rbac.denied · Denied · Warning`,
    );
  },
};

/** An entry whose state the server withheld (`detail.elided`): a compact row shows no detail, so it reads as any. */
export const CompactElided: Story = {
  args: { rows: [ELIDED] },
  play: async ({ canvasElement }) => {
    await expect(links(canvasElement)[0]).toHaveAccessibleName(
      /^2026-10-22 13:58:03 UTC · basiltt · Audit log exported \(admin\.audit_export\) · /,
    );
    await expect(canvasElement).not.toHaveTextContent(/withheld/i);
  },
};

/** D3: a write-ahead record reads "Started" or "Intent", never "Success", though it was written as one. */
export const CompactWriteAhead: Story = {
  args: { rows: [STARTED, INTENT] },
  play: async ({ canvasElement }) => {
    const [started, intent] = links(canvasElement);
    await expect(started).toHaveAccessibleName(
      "2026-10-22 13:55:00 UTC · basiltt · admin.audit_verify · Started · Info",
    );
    await expect(intent).toHaveAccessibleName(
      "2026-10-22 13:54:31 UTC · basiltt · Flag changed (flags.change) · trading.one_click · Intent · Info",
    );
  },
};

/** A system actor reads as its writer recorded it; a code with no label reads as itself. */
export const CompactSystemActor: Story = {
  args: { rows: [MAINTENANCE, LANE] },
  play: async ({ canvasElement }) => {
    const [maintenance, lane] = links(canvasElement);
    await expect(maintenance).toHaveAccessibleName(
      "2026-10-22 03:58:00 UTC · system:maintenance · Maintenance on (maintenance.enabled) · maintenance.mode · Success · Warning",
    );
    await expect(lane).toHaveAccessibleName(
      "2026-10-22 00:00:03 UTC · system:audit-lane · audit.lane_started · Success · Info",
    );
  },
};

/** D2: critical and error are high (octagon, semibold word, the danger rule); warning takes the triangle. */
export const CompactHighSeverity: Story = {
  args: { rows: [CRITICAL, ERROR, DENIED, AREA] },
  play: async ({ canvasElement }) => {
    const words = links(canvasElement).map((link) => link.textContent?.split(" · ").at(-1));
    await expect(words).toEqual(["Critical", "Error", "Warning", "Info"]);
  },
};

/** The pointer on a row: the row's text underlines. */
export const Hover: Story = {
  play: async ({ canvasElement }) => userEvent.hover(links(canvasElement)[0] as HTMLElement),
};

/** Tab from the page start: each row is one stop, with CMP-039's ring. */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    const [first, second] = links(canvasElement);
    await userEvent.tab();
    await expect(first).toHaveFocus();
    await expect(first?.matches(":focus-visible")).toBe(true);
    await userEvent.tab();
    await expect(second).toHaveFocus();
  },
};

/** Long values wrap inside the tile, between fields and inside a long one; nothing truncates. */
export const LongText: Story = {
  args: {
    rows: [
      {
        ...CRITICAL,
        actor_username: "deleted-user-3f9a1c2b7e04",
        subject_label: "sub_002 · Managed account for the APAC desk, Business KYC tier",
      },
    ],
  },
  play: async ({ canvasElement }) => {
    const link = links(canvasElement)[0] as HTMLElement;
    await expect(link.scrollWidth).toBeLessThanOrEqual(link.clientWidth);
  },
};

/*
 * The grid row (E42-D04 §4 Columns, AL-2, AL-3; §6's diff): SCR-135's CMP-049 grid at 1280, as the page draws it, with
 * the rows the stories name expanded. The worked example's later rows (§1): alex's order on LIVE, the flag write and
 * its intent, the failed tamper check's records, a refused flag write, a withheld state and the break at 1,204,118.
 */
const ORDER_LIVE = entry(1204118, "2026-10-22T14:01:50.212409+00:00", "orders.submit", {
  actor_user_id: ALEX,
  actor_username: "alex",
  subject_type: "order",
  subject_id: "0c000000-0000-4000-8000-000000000001",
  subject_label: "BTCUSDT",
  environment: "live",
  ip: "100.84.12.9",
  reason: "validated",
  detail: {
    before: null,
    after: { symbol: "BTCUSDT", side: "buy", qty: "0.250", price: "64010.0" },
  },
  entry_hash: "3c9a5e2f1b",
  prev_hash: "7d1e0b44aa",
});
/** Its own id: the compact rows' denial (`DENIED`, 1,204,117) shares the grid stories (A-5520-05). */
const FLAG_WRITE = entry(1204113, "2026-10-22T14:01:40.551203+00:00", "flags.change", {
  subject_type: "feature_flag",
  subject_id: "trading.one_click",
  severity: "warning",
  environment: "live",
  ip: "100.84.12.9",
  detail: {
    before: {
      value: false,
      overrides: {},
      description: "One-click trading; requires an explicit arm.",
    },
    after: {
      value: true,
      overrides: { [ALEX]: true },
      description: "One-click trading; requires an explicit arm.",
      phase: "outcome",
    },
  },
  entry_hash: "4b1d9a0c2e",
  prev_hash: "3c9a5e2f1b",
});
const FLAG_REFUSED = entry(1204116, "2026-10-22T14:00:02.118034+00:00", "flags.change", {
  subject_type: "feature_flag",
  subject_id: "trading.one_click",
  outcome: "failure",
  severity: "warning",
  reason: "credential_in_reason",
  environment: "live",
  detail: {
    before: { value: false },
    after: {
      value: true,
      overrides: null,
      reason: AUDIT_MARKERS.credential,
      evidence_url: null,
      result: "credential_in_reason",
    },
  },
  entry_hash: "5e2a0b1c3d",
  prev_hash: "4b1d9a0c2e",
});
const FLAG_INTENT = {
  ...INTENT,
  environment: "live" as const,
  entry_hash: "6f3b1c2d4e",
  prev_hash: "5e2a0b1c3d",
};
const VERIFY_FAILED = entry(1204121, "2026-10-22T14:05:07.004211+00:00", "admin.audit_verify", {
  outcome: "failure",
  severity: "critical",
  detail: {
    before: null,
    after: {
      from_id: 204119,
      to_id: 1204118,
      verified: false,
      first_bad_id: 1204118,
      kind: "prev_hash_mismatch",
    },
  },
  entry_hash: "8a1c2b3d4e",
  prev_hash: "7f0b1c2d3e",
});
const VERIFY_STARTED = { ...STARTED, entry_hash: "7f0b1c2d3e", prev_hash: "6f3b1c2d4e" };
const KEY_IMPORT = entry(1204105, "2026-10-22T11:12:40.330117+00:00", "api_key.import", {
  actor_user_id: null,
  actor_username: "system:key-selfcheck",
  subject_type: "exchange_account",
  subject_label: "sub_002",
  outcome: "failure",
  severity: "critical",
  environment: "live",
  detail: {
    before: null,
    after: {
      rules: ["withdrawal_permission"],
      key_id_masked: "ab12…9f",
      api_secret: AUDIT_MARKERS.secret,
      passphrase: "unredacted",
      reason: AUDIT_MARKERS.credential,
    },
  },
  entry_hash: "9b2c3d4e5f",
  prev_hash: "8a1c2b3d4e",
});
const EXPORT_WITHHELD = {
  ...ELIDED,
  environment: "live" as const,
  entry_hash: "0c1d2e3f4a",
  prev_hash: "9b2c3d4e5f",
};
const PROJECTED: Entry = {
  ...ORDER_LIVE,
  id: 1204104,
  environment: null,
  ip: null,
  reason: null,
  subject_label: null,
  detail: {},
  entry_hash: null,
  prev_hash: null,
};
const DELETED = entry(1203990, "2026-10-21T09:40:00.000000+00:00", "orders.submit", {
  actor_user_id: null,
  actor_username: "deleted-user-3f9a1c2b7e04",
  subject_type: "order",
  subject_label: "ETHUSDT",
  environment: "demo",
  entry_hash: "1d2e3f4a5b",
  prev_hash: "0c1d2e3f4a",
});

/**
 * SCR-135's grid, its expanded and selected rows held as the page holds them; stacked, it stays a grid of cards
 * (AL-28, `reflow="grid"`). `width` is the content column, 59rem (944 px at 1280) unless a story narrows it.
 */
function Grid({
  entries,
  expanded = [],
  selectedId,
  view,
  afterBreakId,
  width = "59rem",
}: {
  readonly entries: readonly Entry[];
  readonly expanded?: readonly number[];
  readonly selectedId?: number;
  readonly view?: "raw" | "own";
  readonly afterBreakId?: number;
  readonly width?: string;
}): JSX.Element {
  // Entry ids key the rows and name the diff rows: a story that repeats one draws a broken grid (A-5520-05).
  const ids = entries.map((one) => one.id);
  if (new Set(ids).size !== ids.length)
    throw new Error(`Grid: duplicate entry ids in ${ids.join(", ")}`);
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set(expanded));
  const toggle = (id: number, next: boolean): void =>
    setOpen((now) => {
      const set = new Set(now);
      if (next) set.add(id);
      else set.delete(id);
      return set;
    });
  return (
    <div style={{ maxWidth: width, color: "var(--color-text-primary)" }}>
      <Table<AuditGridRow>
        grid
        reflow="grid"
        caption="Audit log, newest first. All times UTC. Role at the time is not recorded yet."
        columns={auditColumns()}
        rows={auditGridRows(entries, open)}
        rowKey={auditGridRowKey}
        renderRow={(row, grid) =>
          row.kind === "entry" ? (
            <AuditRow
              variant="row"
              grid={grid}
              entry={row.entry}
              diffId={`audit-diff-${row.entry.id}`}
              expanded={open.has(row.entry.id)}
              onExpandedChange={(next) => toggle(row.entry.id, next)}
              onOpen={() => undefined}
              selected={row.entry.id === selectedId}
              {...(view === undefined ? {} : { view })}
            />
          ) : (
            <AuditRowDiff
              grid={grid}
              entry={row.entry}
              id={`audit-diff-${row.entry.id}`}
              onExpandedChange={(next) => toggle(row.entry.id, next)}
              {...(afterBreakId === undefined ? {} : { afterBreakId })}
            />
          )
        }
      />
    </div>
  );
}

const gridOf = (canvas: HTMLElement): HTMLElement => within(canvas).getByRole("grid");
const rowOf = (canvas: HTMLElement, id: number): HTMLElement => {
  const row = canvas.querySelector<HTMLElement>(`tr[data-entry="${id}"]`);
  if (row === null) throw new Error(`no row ${id}`);
  return row;
};
const diffOf = (canvas: HTMLElement, id: number): HTMLElement => {
  const row = canvas.querySelector<HTMLElement>(`#audit-diff-${id}`);
  if (row === null) throw new Error(`no diff row ${id}`);
  return row;
};
/** Laid out (a browser): jsdom lays nothing out, so the plays' size checks hold only where a box has a width. */
const laidOut = (el: HTMLElement): boolean => el.getBoundingClientRect().width > 0;

/** No served value under a redacted name, no marker and no full hash ever shows (C-2.7; AL-4, AD-3). */
const showsNoRedactedValue = async (canvas: HTMLElement): Promise<void> => {
  await expect(canvas).not.toHaveTextContent("unredacted");
  await expect(canvas.textContent ?? "").not.toMatch(/<redacted:|<hashed:pii>/);
};

/** AL-2's grid: one row per entry under the nine headers; Time states newest first; no row is expanded. */
export const Default: Story = {
  render: () => <Grid entries={[ORDER_LIVE, FLAG_WRITE, FLAG_REFUSED, DENIED]} />,
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    const time = within(grid).getByRole("columnheader", { name: /^Time/ });
    await expect(time).toHaveAttribute("aria-sort", "descending");
    await expect(within(grid).getAllByRole("button", { name: /^Record / })).toHaveLength(4);
    await expect(rowOf(canvasElement, ORDER_LIVE.id)).toHaveTextContent("Order submitted");
    await showsNoRedactedValue(canvasElement);
  },
};

/** AL-3: Space expands the row; its diff row follows, a dl per field with Before and After, unchanged fields folded. */
export const ExpandedDiff: Story = {
  render: () => <Grid entries={[ORDER_LIVE, FLAG_WRITE, DENIED]} expanded={[FLAG_WRITE.id]} />,
  play: async ({ canvasElement }) => {
    const toggle = within(rowOf(canvasElement, FLAG_WRITE.id)).getByRole("button");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveAttribute("aria-controls", `audit-diff-${FLAG_WRITE.id}`);
    const diff = diffOf(canvasElement, FLAG_WRITE.id);
    await expect(diff).toHaveTextContent("Changed value");
    await expect(diff).toHaveTextContent("BeforeOFFAfterON");
    await expect(within(diff).getByRole("button", { name: "1 unchanged field" })).toBeVisible();
  },
};

/** A system actor's row reads as its writer recorded it; a code with no label reads as itself. */
export const SystemActor: Story = {
  render: () => <Grid entries={[MAINTENANCE, LANE]} />,
  play: async ({ canvasElement }) => {
    await expect(rowOf(canvasElement, MAINTENANCE.id)).toHaveTextContent("system:maintenance");
    await expect(rowOf(canvasElement, LANE.id)).toHaveTextContent("audit.lane_started");
  },
};

/**
 * D2: critical and error are high (the octagon, semibold, the danger rule); warning takes the triangle. Every
 * expander is a 24 x 24 target, the high rule drawn over its column, not taken from it (WCAG 2.5.8).
 */
export const HighSeverity: Story = {
  render: () => <Grid entries={[VERIFY_FAILED, CRITICAL, ERROR, FLAG_WRITE, ORDER_LIVE]} />,
  play: async ({ canvasElement }) => {
    await expect(rowOf(canvasElement, VERIFY_FAILED.id)).toHaveAttribute(
      "data-severity",
      "critical",
    );
    await expect(rowOf(canvasElement, ERROR.id)).toHaveTextContent("Error");
    await expect(rowOf(canvasElement, FLAG_WRITE.id)).toHaveTextContent("Warning");
    const toggles = within(gridOf(canvasElement)).getAllByRole("button", { name: /^Record / });
    await expect(toggles).toHaveLength(5);
    if (laidOut(gridOf(canvasElement))) {
      for (const toggle of toggles) {
        const box = toggle.getBoundingClientRect();
        await expect(box.width, toggle.getAttribute("aria-label") ?? "").toBeGreaterThanOrEqual(24);
        await expect(box.height).toBeGreaterThanOrEqual(24);
      }
    }
  },
};

/** §6: a nested path keeps its keys, "overrides › {user}", added beside the changed value. */
export const ExpandedNested: Story = {
  render: () => <Grid entries={[FLAG_WRITE]} expanded={[FLAG_WRITE.id]} />,
  play: async ({ canvasElement }) => {
    await expect(diffOf(canvasElement, FLAG_WRITE.id)).toHaveTextContent(
      `Added overrides › ${ALEX}`,
    );
  },
};

/**
 * AL-4, AD-3: a secret, a credential and a value under a secret-named field show their words alone, never a value,
 * a marker or a hash; a fingerprint keeps its Copy.
 */
export const ExpandedSecret: Story = {
  render: () => <Grid entries={[KEY_IMPORT]} expanded={[KEY_IMPORT.id]} />,
  play: async ({ canvasElement }) => {
    const diff = diffOf(canvasElement, KEY_IMPORT.id);
    await expect(diff).toHaveTextContent("Secret — never recorded");
    await expect(diff).toHaveTextContent("Hidden — secret-named field");
    await expect(diff).toHaveTextContent("Redacted — it held a credential");
    await expect(within(diff).getByRole("button", { name: "Copy key_id_masked" })).toBeVisible();
    await showsNoRedactedValue(canvasElement);
  },
};

/** §6: a state withheld by the server reads "Withheld" once under its term, its pair's fields listed, no status word. */
export const ExpandedWithheld: Story = {
  render: () => (
    <Grid
      entries={[
        {
          ...FLAG_WRITE,
          id: 1204099,
          detail: { before: null, after: { value: true }, elided: ["before"] },
        },
        EXPORT_WITHHELD,
      ]}
      expanded={[1204099, EXPORT_WITHHELD.id]}
    />
  ),
  play: async ({ canvasElement }) => {
    await expect(diffOf(canvasElement, 1204099)).toHaveTextContent(
      "Withheld — too large to show here",
    );
    await expect(diffOf(canvasElement, 1204099)).not.toHaveTextContent(/Changed|Added|Removed/);
  },
};

/** §6's request shape: a refused write and an intent head their blocks; the second term is Requested, never After. */
export const ExpandedRequested: Story = {
  render: () => (
    <Grid entries={[FLAG_REFUSED, FLAG_INTENT]} expanded={[FLAG_REFUSED.id, FLAG_INTENT.id]} />
  ),
  play: async ({ canvasElement }) => {
    const refused = diffOf(canvasElement, FLAG_REFUSED.id);
    await expect(refused).toHaveTextContent("Not applied — credential_in_reason");
    await expect(refused).toHaveTextContent("Requested");
    await expect(refused).toHaveTextContent("not sent — the existing overrides stay");
    await expect(diffOf(canvasElement, FLAG_INTENT.id)).toHaveTextContent(
      "Intent — the outcome is a separate record",
    );
    await showsNoRedactedValue(canvasElement);
  },
};

/** D3: a write-ahead record's result reads Started or Intent, never Success; the started check's diff heads so. */
export const WriteAhead: Story = {
  render: () => <Grid entries={[VERIFY_STARTED, FLAG_INTENT]} expanded={[VERIFY_STARTED.id]} />,
  play: async ({ canvasElement }) => {
    await expect(rowOf(canvasElement, VERIFY_STARTED.id)).toHaveTextContent("Started");
    await expect(rowOf(canvasElement, FLAG_INTENT.id)).toHaveTextContent("Intent");
    await expect(diffOf(canvasElement, VERIFY_STARTED.id)).toHaveTextContent(
      "Started — the result is a separate record",
    );
  },
};

/** AL-25: a Manager's projection, its nulled Environment and IP "not shown in your view", its diff hidden. */
export const OwnProjection: Story = {
  render: () => <Grid entries={[PROJECTED]} expanded={[PROJECTED.id]} view="own" />,
  play: async ({ canvasElement }) => {
    await expect(rowOf(canvasElement, PROJECTED.id)).toHaveTextContent("not shown in your view");
    await expect(diffOf(canvasElement, PROJECTED.id)).toHaveTextContent("Not shown in your view");
  },
};

/** CG-33: a purged user's pseudonym, cut to 4 hex in the grid with its whole words kept; never a link. */
export const DeletedActor: Story = {
  render: () => <Grid entries={[DELETED]} />,
  play: async ({ canvasElement }) => {
    const row = rowOf(canvasElement, DELETED.id);
    await expect(row).toHaveTextContent("deleted-user-3f9a…");
    await expect(within(row).queryByRole("link")).toBeNull();
  },
};

/** AD-5: an entry at or after the break says so in its expanded row, in the danger treatment; an older one does not. */
export const AfterBreak: Story = {
  render: () => (
    <Grid
      entries={[VERIFY_FAILED, ORDER_LIVE, FLAG_WRITE]}
      expanded={[ORDER_LIVE.id, FLAG_WRITE.id]}
      selectedId={ORDER_LIVE.id}
      afterBreakId={1204118}
    />
  ),
  play: async ({ canvasElement }) => {
    const line = "Not verified — at or after the break at entry 1,204,118.";
    await expect(diffOf(canvasElement, ORDER_LIVE.id)).toHaveTextContent(line);
    await expect(diffOf(canvasElement, FLAG_WRITE.id)).not.toHaveTextContent(line);
    await expect(rowOf(canvasElement, ORDER_LIVE.id)).toHaveAttribute("aria-selected", "true");
  },
};

/**
 * AL-28 at 400 % (a 20rem content column): the rows stack into cards that stay a grid (`reflow="grid"`), and Role and
 * Action keep their room on the card's line, never zero width; nothing scrolls sideways.
 */
export const Reflow: Story = {
  render: () => <Grid entries={[ORDER_LIVE, FLAG_WRITE]} width="20rem" />,
  play: async ({ canvasElement }) => {
    const grid = gridOf(canvasElement);
    await expect(rowOf(canvasElement, ORDER_LIVE.id)).toHaveTextContent("Order submitted");
    await expect(within(grid).getAllByRole("gridcell").length).toBeGreaterThan(0);
    if (laidOut(grid)) {
      const table = canvasElement.querySelector<HTMLElement>(".cv-table");
      await waitFor(() => expect(table).toHaveAttribute("data-layout", "stacked"));
      for (const id of [ORDER_LIVE.id, FLAG_WRITE.id]) {
        for (const fit of rowOf(canvasElement, id).querySelectorAll<HTMLElement>(
          ".cv-audit-row__fit",
        )) {
          await expect(fit.getBoundingClientRect().width, fit.dataset["fit"]).toBeGreaterThan(0);
        }
      }
      const region = canvasElement.querySelector<HTMLElement>(".cv-table__region");
      await expect(region?.scrollWidth).toBeLessThanOrEqual(region?.clientWidth ?? 0);
    }
  },
};

/** The pointer on a row: CMP-049's surface.hover under every cell. */
export const RowHover: Story = {
  render: () => <Grid entries={[ORDER_LIVE, FLAG_WRITE, DENIED]} />,
  play: async ({ canvasElement }) => {
    await userEvent.hover(rowOf(canvasElement, FLAG_WRITE.id));
    await expect(rowOf(canvasElement, FLAG_WRITE.id)).toHaveTextContent("Flag changed");
  },
};

/** Tab into the grid: its one stop is the first expander, with CMP-039's ring; → moves the ring to the Time cell. */
export const RowFocusVisible: Story = {
  render: () => <Grid entries={[ORDER_LIVE, FLAG_WRITE, DENIED]} />,
  play: async ({ canvasElement }) => {
    const toggle = within(rowOf(canvasElement, ORDER_LIVE.id)).getByRole("button");
    await userEvent.tab();
    await expect(toggle).toHaveFocus();
    await expect(toggle.matches(":focus-visible")).toBe(true);
    await userEvent.keyboard("{ArrowRight}");
    await expect(rowOf(canvasElement, ORDER_LIVE.id).children[1]).toHaveFocus();
  },
};

/** Long values wrap inside their cells, between words or anywhere in a long one; no cell clips or truncates. */
export const RowLongText: Story = {
  render: () => (
    <Grid
      entries={[
        {
          ...CRITICAL,
          actor_username: "system:key-selfcheck",
          subject_type: "exchange_account",
          subject_label: "sub_002 · Managed account for the APAC desk, Business KYC tier",
          environment: "testnet",
          ip: "2001:db8:85a3::8a2e:370:7334",
        },
        { ...DELETED, id: 1203989, action: "security.key_policy_violation" },
      ]}
    />
  ),
  play: async ({ canvasElement }) => {
    const row = rowOf(canvasElement, CRITICAL.id);
    await expect(row).toHaveTextContent("Business KYC tier");
    for (const cell of row.querySelectorAll<HTMLElement>("td")) {
      await expect(cell.scrollWidth).toBeLessThanOrEqual(cell.clientWidth);
    }
  },
};
