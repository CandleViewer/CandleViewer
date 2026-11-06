import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { AuditFilterBar, type AuditFilterBarProps, type AuditFilters } from "./AuditFilterBar.js";

/** E42-D04's worked example: the Owner basiltt and the managers alex and bea, seen on the loaded pages. */
const ACTORS = [
  { id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001", label: "basiltt" },
  { id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002", label: "alex" },
  { id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0003", label: "bea" },
  { id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0004", label: "deleted-user-3f9a1c2b7e04" },
];
/** The labelled codes (D02, D03) and others seen on the page, by their codes alone (CG-3). */
const ACTIONS = [
  { code: "orders.submit", label: "Order submitted" },
  { code: "admin.audit_read", label: "Audit log viewed" },
  { code: "admin.audit_export", label: "Audit log exported" },
  { code: "flags.change", label: "Flag changed" },
  { code: "maintenance.enabled", label: "Maintenance on" },
  { code: "maintenance.disabled", label: "Maintenance off" },
  { code: "admin.area_entered", label: "Area entered" },
  { code: "rbac.denied" },
  { code: "security.key_policy_violation" },
];
const LIMITED = "Paused by a rate limit.";
const LIMITED_LINE =
  "Too many requests — try again at 14:03:12 UTC (in 45 s). Run tamper check and opening records still work.";

type Host = Omit<AuditFilterBarProps, "filters" | "onChange" | "actorOptions" | "actionOptions"> & {
  readonly initial?: AuditFilters;
  readonly onChange?: (filters: AuditFilters) => void;
  /** SCR-135's `audit.limited` line under the page header and its one notice (AL-16). */
  readonly limitedLine?: boolean;
};

/** SCR-135's bar in its 944 px content column at 1280 (E42-D03 D1), controlled as the page holds it. */
function Bar({ initial = {}, onChange, limitedLine = false, ...props }: Host): JSX.Element {
  const [filters, setFilters] = useState<AuditFilters>(initial);
  return (
    <div style={{ maxWidth: "59rem", color: "var(--color-text-primary)" }}>
      {limitedLine ? (
        <p style={{ margin: "0 0 var(--space-stack-sm)" }}>
          {LIMITED_LINE} <span id="audit-limited">{LIMITED}</span>
        </p>
      ) : null}
      <AuditFilterBar
        {...props}
        filters={filters}
        actorOptions={ACTORS}
        actionOptions={ACTIONS}
        onChange={(next) => {
          setFilters(next);
          onChange?.(next);
        }}
      />
    </div>
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Bar> = {
  title: "Molecules/AuditFilterBar",
  component: Bar,
};
export default meta;
type Story = StoryObj<typeof Bar>;

const bar = (canvas: HTMLElement): HTMLElement =>
  within(canvas).getByRole("search", { name: "Filter the audit log" });

/** `n` ch of `el`'s own font, in px; 0 where nothing is laid out (jsdom), so the size checks hold in a browser. */
const ch = (el: HTMLElement, n: number): number => {
  const probe = document.createElement("span");
  probe.style.cssText = `position: absolute; display: inline-block; visibility: hidden; inline-size: ${n}ch`;
  probe.style.font = getComputedStyle(el).font;
  document.body.append(probe);
  const width = probe.getBoundingClientRect().width;
  probe.remove();
  return width;
};

/** Nothing applied: every control under its visible label, From and To in UTC. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const form = within(bar(canvasElement));
    await expect(form.getByRole("combobox", { name: "Action" })).toHaveValue("");
    await expect(form.getByLabelText("From")).toHaveAccessibleDescription(/UTC/);
    await expect(form.getByRole("button", { name: "Clear filters" })).toBeVisible();
  },
};

/** A deep link's set (AL-6): the window, an actor, two actions as chips, one severity; as text in the controls. */
export const Applied: Story = {
  args: {
    onChange: fn(),
    initial: {
      from: "2026-10-22T14:00:00Z",
      to: "2026-10-22T15:00:00Z",
      actor_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001",
      action: ["flags.change", "rbac.denied"],
      severity: "warning",
    },
  },
  play: async ({ canvasElement, args }) => {
    const form = within(bar(canvasElement));
    await expect(form.getByRole("combobox", { name: "Actor" })).toHaveValue("basiltt");
    await expect(form.getByRole("combobox", { name: "Severity" })).toHaveTextContent("Warning");
    // From and To show the applied day whole: each date well is at least 8ch wide (A-5520-02; WCAG 1.4.10).
    for (const name of ["From", "To"]) {
      const date = form.getByLabelText(name);
      await expect(date).toHaveValue("2026-10-22");
      await expect(date.clientWidth, name).toBeGreaterThanOrEqual(ch(date, 8));
    }
    const remove = form.getByRole("button", { name: "Remove Flag changed (flags.change)" });
    await userEvent.click(remove);
    await expect(args.onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ action: ["rbac.denied"] }),
    );
  },
};

/**
 * My activity (AL-25): Actor reads "you"; Actor, IP, Search and Environment stay, each disabled with its
 * `rbac.owner_only` reason under it, and none of them is sent.
 */
export const OwnView: Story = {
  args: { view: "own" },
  play: async ({ canvasElement }) => {
    const form = within(bar(canvasElement));
    const actor = form.getByRole("combobox", { name: "Actor" });
    await expect(actor).toHaveValue("you");
    await expect(actor).toHaveAttribute("aria-disabled", "true");
    await expect(form.getByText("Only the owner can filter by IP address.")).toBeVisible();
    await expect(form.getByText("Only the owner can search the audit log.")).toBeVisible();
    await expect(form.getByText("Only the owner can filter by environment.")).toBeVisible();
  },
};

/** A `422` (AL-17): the errors under To and IP, linked and not live; focus is on To, the first. */
export const Invalid: Story = {
  args: {
    initial: { from: "2026-10-22T15:00:00Z", to: "2026-10-22T14:00:00Z", ip: "100.84.12.0/24" },
    errors: { to: "From must be earlier than To.", ip: "Enter one IP address, not a range." },
  },
  play: async ({ canvasElement }) => {
    const form = within(bar(canvasElement));
    const to = form.getByLabelText("To");
    await expect(to).toHaveFocus();
    await expect(to).toHaveAttribute("aria-invalid", "true");
    await expect(to).toHaveAccessibleDescription(/From must be earlier than To\./);
    await expect(form.getByLabelText("IP")).toHaveAttribute("aria-invalid", "true");
  },
};

/** D7: Environment filters the loaded page only, and says so in its value. */
export const EnvironmentFacet: Story = {
  args: { initial: { environment: "live", severity: "error" } },
  play: async ({ canvasElement }) => {
    const env = within(bar(canvasElement)).getByRole("combobox", { name: "Environment" });
    await expect(env).toHaveTextContent("LIVE (this page only)");
  },
};

/** AL-16: a `429` gates every control behind the one notice beside SCR-158's line; nothing applies. */
export const RateLimited: Story = {
  args: {
    limitedLine: true,
    blockedReason: LIMITED,
    blockedReasonId: "audit-limited",
    initial: { action: ["rbac.denied"], severity: "warning" },
  },
  play: async ({ canvasElement }) => {
    const form = within(bar(canvasElement));
    for (const name of ["Actor", "Action", "Severity", "Environment"]) {
      const control = form.getByRole("combobox", { name });
      await expect(control).toHaveAttribute("aria-disabled", "true");
      await expect(control).toHaveAttribute("aria-describedby", "audit-limited");
    }
    await expect(form.getByRole("button", { name: /Clear filters$/ })).toHaveAttribute(
      "aria-describedby",
      "audit-limited",
    );
  },
};

/** Tab from the page start: From's date is the bar's first stop, with CMP-039's ring. */
export const FocusVisible: Story = {
  play: async ({ canvasElement }) => {
    const from = within(bar(canvasElement)).getByLabelText("From");
    await userEvent.tab();
    await expect(from).toHaveFocus();
    await expect(from.matches(":focus-visible")).toBe(true);
  },
};

/** Long words: a purged user's pseudonym, codes without a label, a long subject; chips wrap, nothing sideways. */
export const LongText: Story = {
  args: {
    initial: {
      actor_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0004",
      action: [
        "security.key_policy_violation",
        "maintenance.enabled",
        "admin.audit_export",
        "orders.submit",
        "rbac.denied",
      ],
      subject_type: "exchange_account",
      subject_id: "sub_002 · Managed account for the APAC desk, Business KYC tier",
    },
  },
  play: async ({ canvasElement }) => {
    const form = bar(canvasElement);
    await expect(within(form).getByRole("combobox", { name: "Actor" })).toHaveValue(
      "deleted-user-3f9a1c2b7e04",
    );
    await expect(within(form).getAllByRole("button", { name: /^Remove / })).toHaveLength(5);
    await expect(form.scrollWidth).toBeLessThanOrEqual(form.clientWidth);
  },
};
