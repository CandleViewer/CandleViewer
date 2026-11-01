import type { Meta, StoryObj } from "@storybook/react-vite";
import type { CSSProperties } from "react";
import { expect, userEvent, within } from "storybook/test";
import { ADMIN_COPY, AdminLayout, type AdminStripItem } from "./AdminLayout.js";

/** A frozen server clock: the grace line shows the same count on every run (visual regression). */
const T0 = Date.UTC(2026, 9, 22, 14, 2, 11);
const GRACE = { grace: { classLabel: "user changes", expiresAt: T0 + 134_000 }, now: () => T0 };

/** An overview item `ago` minutes old: a warning unless `more` says otherwise. */
const item = (
  id: string,
  label: string,
  href: string,
  ago: number,
  more: Partial<AdminStripItem> = {},
): AdminStripItem => ({
  id,
  label,
  href,
  kind: "other",
  severity: "warning",
  at: T0 - ago * 6e4,
  ...more,
});
const LIVE = { env: "live" } as const;
const CRITICAL = { severity: "critical" } as const;

/** OV-3's five items (E42-D03 §6 and the §14 `strip.*` words), given out of order. */
const OV3 = [
  item("tier", "Tier not recorded → Record tier", "/admin/accounts", 4),
  item("drift", "Attention: clock drift 2.3 s — order entry halted → Health", "/admin/health", 5),
  item("expiry", "1 key expires within 30 days → Accounts and keys", "/admin/keys", 1, LIVE),
  item("mfa", "1 active user without two-factor → Users", "/admin/users", 3),
  item("invalid", "1 key rejected by Bybit → Accounts and keys", "/admin/keys", 2, LIVE),
];

/** §14's `strip.withdrawal` (OV-9), `strip.break_glass` (OV-10) and `strip.tamper` (OV-5). */
const WITHDRAWAL =
  "Attention: key …7F2A on sub_001 has withdrawal permission — remove it on Bybit → Accounts and keys";
const BREAK_GLASS = "Attention: break-glass recovery was used — review it → Incidents";
const TAMPER = "Tamper check FAILED → Open audit log";

/** OV-9, OV-10 and OV-5 lead whatever their age; then a warning; then `strip.backup_old` as info. */
const PRECEDENCE = [
  item("backup", "Last backup 3 days ago → Backups", "/admin/backups", 0, { severity: "info" }),
  item("mfa", "1 active user without two-factor → Users", "/admin/users", 1),
  item("tamper", TAMPER, "/admin/audit", 20, { ...CRITICAL, kind: "tamper" }),
  item("withdrawal", WITHDRAWAL, "/admin/keys", 90, { ...LIVE, ...CRITICAL, kind: "withdrawal" }),
  item("break-glass", BREAK_GLASS, "/admin/health", 60, { ...CRITICAL, kind: "break_glass" }),
];

/** The DS body type on the wrapper, which the band and strip refine; 59rem is D1's 944 px at 1280. */
const FRAME: CSSProperties = {
  maxWidth: "59rem",
  color: "var(--color-text-primary)",
  font: "var(--type-ui-body-font-weight) var(--type-ui-body-font-size) / var(--type-ui-body-line-height) var(--type-ui-body-font-family)",
};
/** The route content: the page's CMP-088 `h1` (PageHeader is E42-S01's next slice). */
const H1: CSSProperties = {
  margin: 0,
  font: "var(--type-ui-heading-md-font-weight) var(--type-ui-heading-md-font-size) / var(--type-ui-heading-md-line-height) var(--type-ui-heading-md-font-family)",
};
const OVERVIEW = { routeLabel: "Overview", children: <h1 style={H1}>Overview</h1> };

/** Theme and density come from the toolbars; the layout itself forces comfortable density. */
const meta: Meta<typeof AdminLayout> = {
  title: "Organisms/AdminLayout",
  component: AdminLayout,
  args: {
    routeLabel: "Users",
    strip: [],
    footer: ADMIN_COPY.footerAreaEntered,
    children: <h1 style={H1}>Users</h1>,
  },
  decorators: [
    (Story) => (
      <div style={FRAME}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof AdminLayout>;

const region = (canvas: HTMLElement, name: string): HTMLElement =>
  within(canvas).getByRole("region", { name });
const names = (canvas: HTMLElement): string[] =>
  within(region(canvas, "Needs your action"))
    .getAllByRole("link")
    .map((link) => link.textContent ?? "");
const FIRST = /^Attention: 1 key expires/;

/** SH-6 (PerActionOnly, StripEmpty): the band's label only and `strip.none` on one line. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const band = region(canvasElement, "Admin area");
    await expect(band).toHaveTextContent("◆ Admin area · Users");
    await expect(band.querySelector("a, button, input, [tabindex]")).toBeNull();
    await expect(region(canvasElement, "Needs your action")).toHaveTextContent(
      ADMIN_COPY.stripNone,
    );
  },
};

/** SH-5 (PerActionGrace): "Still trusted for user changes · 2:14" on the frozen server clock. */
export const WithGrace: Story = {
  args: GRACE,
  play: async ({ canvasElement }) => {
    const band = region(canvasElement, "Admin area");
    await expect(band).toHaveTextContent("Still trusted for user changes · 2:14");
    await expect(within(band).getAllByRole("status")).toHaveLength(1);
  },
};

/** OV-3: "Needs your action (5)", wrapping; all warnings, so newest first. */
export const StripWithItems: Story = {
  args: { ...OVERVIEW, strip: OV3 },
  play: async ({ canvasElement }) => {
    await expect(names(canvasElement)).toEqual([
      "Attention: 1 key expires within 30 days → Accounts and keys LIVE",
      "Attention: 1 key rejected by Bybit → Accounts and keys LIVE",
      "Attention: 1 active user without two-factor → Users",
      "Attention: Tier not recorded → Record tier",
      "Attention: clock drift 2.3 s — order entry halted → Health",
    ]);
  },
};

/** Withdrawal, break-glass and tamper first (§4), in the critical tone; then a warning, then info. */
export const StripPrecedence: Story = {
  args: { ...OVERVIEW, strip: PRECEDENCE },
  play: async ({ canvasElement }) => {
    const lead = names(canvasElement).map((name) => name.split(" ").slice(0, 3).join(" "));
    await expect(lead).toEqual([
      ...["Attention: key …7F2A", "Attention: break-glass recovery", "Attention: Tamper check"],
      ...["Attention: 1 active", "Last backup 3"],
    ]);
  },
};

/**
 * 200 % text at 1280 (`05` §5): the band and the strip wrap, no item is truncated, and nothing
 * overflows the strip's box: a trailing margin once did, by 8 px (A11Y-5287-02).
 */
export const LongText: Story = {
  args: { ...OVERVIEW, ...GRACE, strip: PRECEDENCE },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "20rem" }}>
        <Story />
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const strip = region(canvasElement, "Needs your action");
    await expect(strip.scrollWidth).toBeLessThanOrEqual(strip.clientWidth + 1);
    const band = region(canvasElement, "Admin area");
    await expect(band.scrollWidth).toBeLessThanOrEqual(band.clientWidth + 1);
  },
};

export const Hover: Story = {
  ...StripWithItems,
  play: async ({ canvasElement }) => {
    await userEvent.hover(within(canvasElement).getByRole("link", { name: FIRST }));
  },
};

/** The band has no stop: the first Tab lands on the strip's first link, CMP-039's ring round the pill. */
export const FocusVisible: Story = {
  args: { strip: OV3 },
  play: async ({ canvasElement }) => {
    await userEvent.tab();
    const first = within(canvasElement).getByRole("link", { name: FIRST });
    await expect(first).toHaveFocus();
    await expect(first.matches(":focus-visible")).toBe(true);
    await expect(getComputedStyle(first).outlineStyle).toBe("solid");
  },
};
