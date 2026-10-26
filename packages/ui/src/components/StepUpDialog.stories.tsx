import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import {
  STEP_UP_NOT_SENT,
  StepUpDialog,
  StepUpNotice,
  stepUpOutcomePending,
} from "./StepUpDialog.js";

// The `action_summary` / `target` of the `Forbidden` examples `stepUpRequired` and
// `stepUpRequiredTypedConfirmation` (docs/plan/22-api-openapi.yaml).
const KILL_SWITCH = "Release kill switch, scope global";
const ROTATE = "Rotate API key for account 'sub_002' (live, UID 1001234)";

const meta: Meta<typeof StepUpDialog> = {
  title: "Organisms/StepUpDialog",
  component: StepUpDialog,
  args: {
    actionSummary: KILL_SWITCH,
    target: null,
    submitting: false,
    failure: null,
    onSubmit: fn(),
    onCancel: fn(),
  },
};
export default meta;
type Story = StoryObj<typeof StepUpDialog>;

/** E09-D06 `code-only`: password + code; the summary is the accessible description. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement).getByRole("alertdialog");
    await expect(dialog).toHaveAccessibleDescription(KILL_SWITCH);
    await expect(within(dialog).getByLabelText("Password")).toHaveFocus();
  },
};

/** E09-D06 `code+confirmation`: Confirm waits for the exact, case-sensitive `target`. */
export const TypedConfirmation: Story = {
  args: { actionSummary: ROTATE, target: "sub_002" },
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement);
    await userEvent.type(dialog.getByLabelText("Password"), "correct horse");
    await userEvent.type(dialog.getByLabelText("Authenticator code"), "123456");
    await userEvent.type(
      dialog.getByLabelText("Type sub_002 to confirm (case-sensitive)"),
      "SUB_002",
    );
    await expect(dialog.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await userEvent.clear(dialog.getByLabelText("Type sub_002 to confirm (case-sensitive)"));
    await userEvent.type(
      dialog.getByLabelText("Type sub_002 to confirm (case-sensitive)"),
      "sub_002",
    );
    await expect(dialog.getByRole("button", { name: "Confirm" })).toBeEnabled();
  },
};

/** The step-up, then the held request's re-send, are on the wire. */
export const Submitting: Story = { args: { submitting: true } };

/** A refused factor: one generic, assertive message; the code field is cleared. */
export const Failure: Story = {
  name: "Error",
  args: { failure: { message: "Invalid password or code.", seq: 1 } },
};

/** E09-D06 §2 item 7: cancel, a class mismatch or a stale challenge dropped the held request. */
export const NotSent: Story = { render: () => <StepUpNotice message={STEP_UP_NOT_SENT} /> };

/** E09-D06 §2 item 4: the re-send got no answer; the outcome is read back, never "Not sent". */
export const UnknownOutcome: Story = {
  render: () => <StepUpNotice message={stepUpOutcomePending("Orders")} />,
};

/** `challenge_expires_at` passed with the dialog open: the held request is dropped unsent. */
export const Expired: Story = { render: () => <StepUpNotice message={STEP_UP_NOT_SENT} /> };
