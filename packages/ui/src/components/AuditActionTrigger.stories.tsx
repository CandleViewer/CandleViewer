import type { Meta, StoryObj } from "@storybook/react-vite";
import type { JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { AuditActionTrigger } from "./AuditActionTrigger.js";
import { Button } from "./Button.js";
import { RbacGate } from "./RbacGate.js";

const EXPORT = "Recorded · needs your confirmation — Audit log exported (admin.audit_export)";
const VERIFY = "Recorded in the audit log · admin.audit_verify";

/** SCR-135's two audited controls (E42-D04 §4): the header's Signed export… and the footer's Run tamper check. */
function Controls({ gated }: { readonly gated: boolean }): JSX.Element {
  const exportButton = (
    <AuditActionTrigger marker={{ codes: ["admin.audit_export"], confirm: true }} align="end">
      <Button onClick={fn()}>Signed export…</Button>
    </AuditActionTrigger>
  );
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: "var(--space-stack-lg)",
        maxWidth: "59rem",
        color: "var(--color-text-primary)",
      }}
    >
      <div style={{ alignSelf: "flex-end" }}>
        {gated ? (
          // My activity (AL-25): a Manager sees the control, disabled with its reason (D09 §3.2's verb).
          <RbacGate
            allowed={false}
            reason="rbac.owner_only"
            fills={{ verb: "export the audit log" }}
          >
            {exportButton}
          </RbacGate>
        ) : (
          exportButton
        )}
      </div>
      <AuditActionTrigger
        marker={{ codes: ["admin.audit_verify"] }}
        {...(gated ? { disabledReason: "Paused by a rate limit." } : {})}
      >
        <Button onClick={fn()}>Run tamper check</Button>
      </AuditActionTrigger>
    </div>
  );
}

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof Controls> = {
  title: "Molecules/AuditActionTrigger",
  component: Controls,
  args: { gated: false },
};
export default meta;
type Story = StoryObj<typeof Controls>;

const description = (el: HTMLElement): string =>
  (el.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" | ");

/** Enabled: each control is described by the marker under it, which says what its endpoint records. */
export const Marker: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const signed = canvas.getByRole("button", { name: "Signed export…" });
    const verify = canvas.getByRole("button", { name: "Run tamper check" });
    await expect(description(signed)).toBe(EXPORT);
    await expect(description(verify)).toBe(VERIFY);
    await expect(signed).not.toHaveAttribute("aria-disabled");
  },
};

/**
 * T2 (E42-D04 §12.1): each control keeps its label and its stop, the lock leading it; its reason shows under it and
 * alone describes it, and the marker stays visible. A press does nothing but say the reason once.
 */
export const MarkerOnDisabledControl: Story = {
  args: { gated: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const signed = canvas.getByRole("button", { name: "Not available Signed export…" });
    const verify = canvas.getByRole("button", { name: "Not available Run tamper check" });
    await expect(signed).toHaveAttribute("aria-disabled", "true");
    await expect(description(signed)).toBe("Only the owner can export the audit log.");
    await expect(description(verify)).toBe("Paused by a rate limit.");
    await expect(canvas.getByText(EXPORT)).toBeVisible();
    await expect(canvas.getByText(VERIFY)).toBeVisible();
    await userEvent.tab();
    await expect(signed).toHaveFocus();
  },
};
