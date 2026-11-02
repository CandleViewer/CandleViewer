import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { AuditRow, AuditRowList, type AuditRowProps } from "./AuditRow.js";

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
