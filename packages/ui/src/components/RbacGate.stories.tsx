import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { Button } from "./Button.js";
import { RbacGate, type RbacGateProps } from "./RbacGate.js";
import { Toggle } from "./Toggle.js";

/** The gate has no look of its own: each story is one wrapped Button, T1 or T2 (E09-D09 §2.2). */
const meta: Meta<typeof RbacGate> = {
  title: "Molecules/RbacGate",
  component: RbacGate,
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
