import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Callout } from "./Callout.js";
import { FormField } from "./FormField.js";
import { IconButton } from "./IconButton.js";
import { RbacGate, type RbacGateProps } from "./RbacGate.js";
import { formatRbacReason } from "./rbacReasons.js";
import { TextInput } from "./TextInput.js";
import { Toggle } from "./Toggle.js";

/** The gate has no look of its own: each story is one wrapped Button, T1 or T2 (E09-D09 §2.2). */
const meta: Meta<typeof RbacGate> = {
  title: "Molecules/RbacGate",
  component: RbacGate,
  parameters: {
    docs: {
      description: {
        component:
          "RbacGate is a UI affordance, not an authorisation control: the server enforces RBAC on every " +
          "route and subscription (C-12.4); the gate renders what it is told.",
      },
    },
  },
};
export default meta;
type Story = StoryObj<typeof RbacGate>;

/** One denied gate's props, without the child; distributes so each key keeps its own fills. */
type DeniedGate = RbacGateProps extends infer P
  ? P extends { allowed: false }
    ? Omit<P, "children">
    : never
  : never;

/** Denied: the button keeps its role and name, is `aria-disabled` (never `disabled`) and described by the reason. */
const denied = (gate: DeniedGate): Story => {
  const onClick = fn();
  return {
    render: () => (
      <RbacGate {...gate}>
        <Button onClick={onClick}>Place order</Button>
      </RbacGate>
    ),
    play: async ({ canvasElement }) => {
      const control = within(canvasElement).getByRole("button", { name: "Place order" });
      await expect(control).toHaveAttribute("aria-disabled", "true");
      await expect(control).not.toHaveAttribute("disabled");
      await expect(control).toHaveAccessibleDescription(/\.$/);
      await userEvent.click(control);
      await expect(control).toHaveFocus();
      await expect(onClick).not.toHaveBeenCalled();
      // One polite announcement of the reason (D09 2.2), set a microtask after the click.
      const region = within(canvasElement.ownerDocument.body).getByRole("status");
      await waitFor(() => expect(region).toHaveTextContent(/\.$/));
    },
  };
};

export const Allowed: Story = {
  render: () => (
    <RbacGate allowed>
      <Button>Place order</Button>
    </RbacGate>
  ),
  play: async ({ canvasElement }) => {
    const control = within(canvasElement).getByRole("button", { name: "Place order" });
    await expect(control).not.toHaveAttribute("aria-disabled");
    await expect(control).not.toHaveAccessibleDescription();
  },
};

export const DeniedPermission: Story = {
  name: "Denied(Permission)",
  ...denied({ allowed: false, reason: "rbac.permission", fills: { verb: "place orders" } }),
};

export const DeniedOwnerOnly: Story = {
  name: "Denied(OwnerOnly)",
  ...denied({ allowed: false, reason: "rbac.owner_only", fills: { verb: "change recording" } }),
};

export const DeniedAccount: Story = {
  name: "Denied(Account)",
  ...denied({ allowed: false, reason: "rbac.account" }),
};

export const DeniedAccountReadOnly: Story = {
  name: "Denied(AccountReadOnly)",
  ...denied({ allowed: false, reason: "rbac.account_read_only" }),
};

export const DeniedEnv: Story = {
  name: "Denied(Env)",
  ...denied({ allowed: false, reason: "rbac.env" }),
};

/** A step-2 refusal today; T2 only once the session carries `read_only_until` (E09-D09 §3.1, CG-2). */
export const DeniedReadOnly: Story = {
  name: "Denied(ReadOnly)",
  ...denied({ allowed: false, reason: "rbac.read_only" }),
};

export const DeniedViewAs: Story = {
  name: "Denied(ViewAs)",
  ...denied({ allowed: false, reason: "rbac.view_as", fills: { user: "alex" } }),
};

/** 2a inline, the default form, on two atoms: the reason is each atom's own described-by node. */
export const FormInline: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-inset-sm)", justifyItems: "start" }}>
      <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }} form="inline">
        <Button>Save layout</Button>
      </RbacGate>
      <RbacGate allowed={false} reason="rbac.owner_only" fills={{ verb: "change settings" }}>
        <Toggle label="Sound alerts" />
      </RbacGate>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Save layout" })).toHaveAccessibleDescription(
      "Read-only while viewing as alex.",
    );
    await expect(canvas.getByRole("switch", { name: "Sound alerts" })).toHaveAccessibleDescription(
      "Only the owner can change settings.",
    );
  },
};

const OWNER_ONLY = formatRbacReason("rbac.owner_only", { verb: "change account settings" });

/**
 * 2b tooltip, for icon-only controls: the lock badges the icon, the reason node is visually hidden, and CMP-016
 * echoes it on hover and focus (a duplicate, never the only copy). `Esc` closes the echo only.
 */
export const FormTooltip: Story = {
  render: () => (
    <RbacGate
      form="tooltip"
      allowed={false}
      reason="rbac.owner_only"
      fills={{ verb: "change account settings" }}
    >
      <IconButton icon="settings" label="Account settings" />
    </RbacGate>
  ),
  play: async ({ canvasElement }) => {
    const control = within(canvasElement).getByRole("button", { name: "Account settings" });
    await expect(control).toHaveAttribute("aria-disabled", "true");
    await expect(control).toHaveAccessibleDescription(
      "Only the owner can change account settings.",
    );
    await userEvent.tab();
    await expect(control).toHaveFocus();
    const echo = canvasElement.ownerDocument.querySelector<HTMLElement>(".cv-tooltip");
    await waitFor(() => expect(echo?.hidden).toBe(false));
    await expect(echo).toHaveTextContent("Only the owner can change account settings.");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(echo?.hidden).toBe(true));
    await expect(control).toHaveFocus();
  },
};

/**
 * One notice, many pointers (E42-D03): a CMP-028 with no live role carries the sentence once, and each gated
 * control points `aria-describedby` at it; the controls render no reason node and no echo of their own.
 */
export const FormNotice: Story = {
  render: () => (
    <div style={{ display: "grid", gap: "var(--space-inset-sm)", maxWidth: "24rem" }}>
      <Callout id="account-settings-notice" title={OWNER_ONLY} live="off" />
      <RbacGate
        form="notice"
        noticeId="account-settings-notice"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "change account settings" }}
      >
        <FormField label="Display name">
          <TextInput defaultValue="Main account" />
        </FormField>
      </RbacGate>
      <RbacGate
        form="notice"
        noticeId="account-settings-notice"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "change account settings" }}
      >
        <Toggle label="Sound alerts" />
      </RbacGate>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const controls = [
      canvas.getByRole("textbox", { name: "Display name" }),
      canvas.getByRole("switch", { name: "Sound alerts" }),
    ];
    for (const control of controls) {
      await expect(control).toHaveAttribute("aria-disabled", "true");
      await expect(control).toHaveAttribute("aria-describedby", "account-settings-notice");
      await expect(control).toHaveAccessibleDescription(OWNER_ONLY);
    }
    await expect(canvas.getAllByText(OWNER_ONLY)).toHaveLength(1);
  },
};
