/**
 * SCR-006 step-up dialog states (E09-D06), RTL + axe. apps/web has no Storybook (the repo's one
 * Storybook builds `packages/ui` only), so every state the stories would show is rendered and
 * axe-checked here: default, typed confirmation, submitting, error, Not sent, unknown outcome and
 * expired.
 */
import { createRequire } from "node:module";
import { useState, type JSX } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  STEP_UP_EXPIRED,
  STEP_UP_EXPIRY_WARNING,
  STEP_UP_LOCKED,
  STEP_UP_NOT_SENT,
  STEP_UP_READ_ONLY,
  StepUpDialog,
  StepUpNotice,
  stepUpOutcomePending,
  type StepUpDialogProps,
} from "../../../src/features/stepUp/StepUpDialog";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function seriousViolations(): Promise<unknown[]> {
  // jsdom has no canvas; contrast is checked by the Playwright axe run.
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

// The `action_summary` / `target` of the `Forbidden` examples `stepUpRequired` and
// `stepUpRequiredTypedConfirmation` (docs/plan/22-api-openapi.yaml).
const KILL_SWITCH = "Release kill switch, scope global";
const ROTATE = "Rotate API key for account 'sub_002' (live, UID 1001234)";
const TYPED = "Type sub_002 to confirm (case-sensitive)";

const base: StepUpDialogProps = {
  actionSummary: KILL_SWITCH,
  target: null,
  onSubmit: () => undefined,
  onCancel: () => undefined,
};

const STATES: readonly [string, JSX.Element][] = [
  ["default (code-only)", <StepUpDialog key="d" {...base} />],
  [
    "typed confirmation (code+confirmation)",
    <StepUpDialog key="t" {...base} actionSummary={ROTATE} target="sub_002" />,
  ],
  ["submitting", <StepUpDialog key="s" {...base} submitting />],
  [
    "error (failure-1-of-3)",
    <StepUpDialog key="e" {...base} failure={{ message: "Incorrect code.", seq: 1 }} />,
  ],
  ["Not sent", <StepUpNotice key="n" message={STEP_UP_NOT_SENT} />],
  ["unknown outcome", <StepUpNotice key="u" message={stepUpOutcomePending("Orders")} />],
  ["expired", <StepUpNotice key="x" message={STEP_UP_EXPIRED} assertive onRenew={() => {}} />],
  ["locked (third failure)", <StepUpNotice key="l" message={STEP_UP_LOCKED} assertive />],
  ["read-only session", <StepUpNotice key="r" message={STEP_UP_READ_ONLY} assertive />],
  [
    "expiry warning",
    <StepUpDialog key="w" {...base} warning={STEP_UP_EXPIRY_WARNING} onRenew={() => {}} />,
  ],
];

describe("StepUpDialog (SCR-006, E09-D06)", () => {
  it.each(STATES)("%s has no serious or critical axe violations", async (_name, ui) => {
    render(ui);
    expect(await seriousViolations()).toEqual([]);
  });

  it("is a modal alertdialog described by the summary alone, focus on the password", () => {
    render(<StepUpDialog {...base} />);
    const dialog = screen.getByRole("alertdialog", { name: "Confirm with two-factor" });
    expect(dialog).toHaveAccessibleDescription(KILL_SWITCH);
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText(/^Action:/)).toBeInTheDocument();
    expect(screen.queryByText(/^Why:/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  it("leaves the description out when the challenge carries no summary", () => {
    render(<StepUpDialog {...base} actionSummary={null} />);
    expect(screen.getByRole("alertdialog")).not.toHaveAttribute("aria-describedby");
    expect(screen.queryByText(/^Action:/)).not.toBeInTheDocument();
  });

  it("enables Confirm only for a six-digit code and the exact target, then submits", () => {
    const onSubmit = vi.fn();
    render(<StepUpDialog {...base} actionSummary={ROTATE} target="sub_002" onSubmit={onSubmit} />);
    const confirm = screen.getByRole("button", { name: "Confirm" });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "12345" } });
    fireEvent.change(screen.getByLabelText(TYPED), { target: { value: "sub_002" } });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(confirm);
    expect(onSubmit).not.toHaveBeenCalled(); // aria-disabled still never sends
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    expect(confirm).toHaveAttribute("aria-disabled", "false");
    fireEvent.change(screen.getByLabelText(TYPED), { target: { value: "Sub_002" } });
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(confirm);
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(TYPED), { target: { value: "sub_002" } });
    fireEvent.click(confirm);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({ password: "pw", code: "123456" });
  });

  it("states the code format on the code field (A11Y-F-0011)", () => {
    render(<StepUpDialog {...base} />);
    expect(screen.getByLabelText("Authenticator code")).toHaveAccessibleDescription(
      "6-digit code from your authenticator app",
    );
  });

  it.each([
    ["the password", "", "123456", "sub_002", "Password", "Enter your password."],
    [
      "the code",
      "pw",
      "12345",
      "sub_002",
      "Authenticator code",
      /Enter the 6-digit code from your authenticator app\./,
    ],
    [
      "the target",
      "pw",
      "123456",
      "Sub_002",
      TYPED,
      "Type sub_002 exactly to confirm (case-sensitive).",
    ],
  ])(
    "an incomplete submit names %s in text, marks and focuses it, sends nothing (A11Y-F-0011)",
    async (_what, password, code, typed, label, text) => {
      const onSubmit = vi.fn();
      render(
        <StepUpDialog {...base} actionSummary={ROTATE} target="sub_002" onSubmit={onSubmit} />,
      );
      fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
      fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: code } });
      fireEvent.change(screen.getByLabelText(TYPED), { target: { value: typed } });
      // Enter in a field submits the form: an aria-disabled default button does not block it
      fireEvent.submit(screen.getByLabelText(TYPED));
      expect(onSubmit).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent(text);
      const field = screen.getByLabelText(label);
      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(text);
      expect(field).toHaveFocus();
      expect(await seriousViolations()).toEqual([]);
    },
  );

  it("shows the expiry warning and the renewal inside the dialog (A11Y-F-0010)", () => {
    const onRenew = vi.fn();
    const { rerender } = render(<StepUpDialog {...base} onRenew={onRenew} />);
    expect(screen.queryByRole("button", { name: "Request a new confirmation" })).toBeNull();
    rerender(<StepUpDialog {...base} onRenew={onRenew} warning={STEP_UP_EXPIRY_WARNING} />);
    // fixed text that stays true while shown: no seconds count that goes stale
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This confirmation expires in less than 30 seconds. Nothing is sent if it expires.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Request a new confirmation" }));
    expect(onRenew).toHaveBeenCalledTimes(1);
  });

  it("offers no renewal while a step-up is on the wire (A11Y-F-0010)", () => {
    const onRenew = vi.fn();
    render(
      <StepUpDialog {...base} submitting onRenew={onRenew} warning={STEP_UP_EXPIRY_WARNING} />,
    );
    const renew = screen.getByRole("button", { name: "Request a new confirmation" });
    expect(renew).toBeDisabled();
    fireEvent.click(renew);
    expect(onRenew).not.toHaveBeenCalled();
  });

  it("an empty password on a Confirm click is explained, not left to the browser (A11Y-F-0011)", () => {
    const onSubmit = vi.fn();
    render(<StepUpDialog {...base} onSubmit={onSubmit} />);
    // no native validation bubble may pre-empt the explained, focused message
    expect(screen.getByRole("alertdialog").querySelector("form")).toHaveAttribute("novalidate");
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your password.");
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  it("editing the named field clears its message and mark (A11Y-F-0011)", () => {
    render(<StepUpDialog {...base} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(password, { target: { value: "pw" } });
    expect(password).not.toHaveAttribute("aria-invalid");
    expect(password).not.toHaveAccessibleDescription();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("never submits while submitting", () => {
    const onSubmit = vi.fn();
    render(<StepUpDialog {...base} submitting onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.submit(screen.getByRole("button", { name: "Confirm" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveAttribute("aria-busy", "true");
  });

  it("clears both fields and refocuses the password on a refused credential only", () => {
    let fail: (credentials?: boolean) => void = () => undefined;
    function Harness(): JSX.Element {
      const [state, setState] = useState({ seq: 0, credentials: true });
      fail = (credentials = true) => setState((s) => ({ seq: s.seq + 1, credentials }));
      const failure =
        state.seq === 0
          ? null
          : {
              message: state.credentials ? "Incorrect code." : "Cannot reach the server.",
              seq: state.seq,
              credentials: state.credentials,
            };
      return <StepUpDialog {...base} failure={failure} />;
    }
    render(<Harness />);
    const password = screen.getByLabelText("Password");
    const code = screen.getByLabelText("Authenticator code");
    fireEvent.change(password, { target: { value: "pw" } });
    fireEvent.change(code, { target: { value: "123456" } });
    screen.getByRole("button", { name: "Cancel" }).focus();
    act(() => fail());
    expect(screen.getByRole("alert")).toHaveTextContent("Incorrect code.");
    expect(code).toHaveAttribute("aria-invalid", "true");
    expect(code).toHaveValue("");
    expect(password).toHaveValue("");
    expect(password).toHaveFocus();
    fireEvent.change(password, { target: { value: "pw2" } });
    fireEvent.change(code, { target: { value: "654321" } });
    act(() => fail(false));
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot reach the server.");
    expect(code).not.toHaveAttribute("aria-invalid");
    expect(code).toHaveValue("654321");
    expect(password).toHaveValue("pw2");
  });

  it("a press on the scrim neither cancels nor lets focus leave the dialog (A11Y-F-0013)", () => {
    const onCancel = vi.fn();
    render(<StepUpDialog {...base} onCancel={onCancel} />);
    const scrim = screen.getByRole("alertdialog").parentElement as HTMLElement;
    // a browser moves focus to body on a press over a non-focusable element unless it is prevented
    expect(fireEvent.mouseDown(scrim)).toBe(false);
    fireEvent.click(scrim);
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(fireEvent.mouseDown(screen.getByLabelText("Password"))).toBe(true);
  });

  it("cancels on Esc and cycles Tab inside the dialog", () => {
    const onCancel = vi.fn();
    render(<StepUpDialog {...base} onCancel={onCancel} />);
    const dialog = screen.getByRole("alertdialog");
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    // Confirm is aria-disabled, so it stays a tab stop (A11Y-F-0011)
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(screen.getByLabelText("Password")).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Tab" }); // not on the last stop: the browser moves focus
    fireEvent.keyDown(dialog, { key: "Enter" });
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("points the unknown outcome at where the read-back shows it", () => {
    expect(stepUpOutcomePending("Orders")).toBe("Outcome pending, see Orders");
  });
});
