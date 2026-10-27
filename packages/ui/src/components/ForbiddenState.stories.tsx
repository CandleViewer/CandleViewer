import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, within } from "storybook/test";
import { ForbiddenState } from "./ForbiddenState.js";

const REF = "urn:cv:req:0b9c1e52-7d4a-4f8e-9a61-2c3d4e5f6a7b";

/** CMP-089 (SCR-154). Theme and density come from the toolbars. */
const meta: Meta<typeof ForbiddenState> = {
  title: "Organisms/ForbiddenState",
  component: ForbiddenState,
  args: {
    capability: "see the journal",
    homeHref: "/terminal",
    onCopyDetails: fn(),
  },
};
export default meta;
type Story = StoryObj<typeof ForbiddenState>;

/** never-had, permission scope, with the Ref of a received 403 body. */
export const Default: Story = {
  args: { refId: REF },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 1 })).toHaveTextContent(
      "You don't have access to this",
    );
    await expect(canvas.getByText(`Ref ${REF}`)).toBeVisible();
  },
};

/** The step-3 pre-check landing: no request was sent, so no Ref line (D09 §5.1). */
export const NoRef: Story = {};

/** The session had it until just now; a `permission_change`-driven replacement carries no Ref. */
export const Withdrawn: Story = { args: { variant: "withdrawn" } };

/** `rbac.account`: the account id the client's own route carried, in mono. */
export const AccountVariant: Story = {
  args: { scope: "account", accountId: "acc_7f3e91c2", refId: REF },
};
