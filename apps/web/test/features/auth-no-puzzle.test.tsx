/**
 * E47-S05 (#1319), Gherkin "Authentication needs no puzzle" (WCAG 3.3.8, Accessible Authentication):
 * login, change-password and step-up let a password manager fill and a user paste every credential
 * field, carry the autocomplete hint a manager keys on, and contain no cognitive test.
 */
import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoginScreen } from "../../src/features/auth/LoginScreen";
import { ChangePasswordScreen } from "../../src/features/auth/ChangePasswordScreen";
import { StepUpDialog } from "../../src/features/stepUp/StepUpDialog";

/** What a cognitive test looks like in markup or copy: a captcha, a puzzle, a sum, an image to read. */
const PUZZLE_COPY =
  /captcha|recaptcha|puzzle|verify you are human|not a robot|solve|what is \d|\d\s*[+\-x*]\s*\d\s*=|select all (the )?(images|squares)|drag the|slide to/iu;
const PUZZLE_MARKUP =
  "img, canvas, iframe, svg[role=img], audio, video, [class*=captcha i], [id*=captcha i]";

const STEP_UP = {
  actionSummary: "Release kill switch, scope global",
  target: null,
  onSubmit: () => undefined,
  onCancel: () => undefined,
};

/** True when nothing cancelled the paste (a handler calling `preventDefault` makes this false). */
const pasteAllowed = (field: HTMLElement, text: string): boolean =>
  fireEvent.paste(field, { clipboardData: { getData: () => text } });

function expectNoPuzzle(root: HTMLElement): void {
  expect(root.textContent ?? "").not.toMatch(PUZZLE_COPY);
  expect(root.querySelectorAll(PUZZLE_MARKUP)).toHaveLength(0);
}

/** The attributes a manager or the browser would act on, for one credential field. */
function expectFillable(field: HTMLElement, autocomplete: string): void {
  expect(field).toHaveAttribute("autocomplete", autocomplete);
  expect(field).not.toHaveAttribute("onpaste");
  expect(field).not.toHaveAttribute("disabled");
  expect(field).not.toHaveAttribute("readonly");
}

describe("the guard can fail", () => {
  it("sees a paste handler that cancels the paste, and a puzzle", () => {
    render(
      <form>
        <input aria-label="blocked" onPaste={(e) => e.preventDefault()} />
        <p>What is 3 + 4 = ?</p>
        <img alt="" src="data:," />
      </form>,
    );
    expect(pasteAllowed(screen.getByLabelText("blocked"), "x")).toBe(false);
    expect(document.body.textContent).toMatch(PUZZLE_COPY);
    expect(document.querySelectorAll(PUZZLE_MARKUP)).toHaveLength(1);
  });
});

describe("LoginScreen (SCR-001)", () => {
  it("allows paste into the username and password, with manager-friendly hints", () => {
    render(<LoginScreen />);
    const id = screen.getByLabelText("Username or email");
    const pw = screen.getByLabelText("Password");
    expectFillable(id, "username");
    expectFillable(pw, "current-password");
    expect(pw).toHaveAttribute("type", "password");
    expect(pw).not.toHaveAttribute("maxlength");
    expect(pasteAllowed(id, "ann@example.test")).toBe(true);
    expect(pasteAllowed(pw, "correct horse battery staple")).toBe(true);
    // A manager sets the value programmatically and fires input; the form takes it as typed.
    fireEvent.change(pw, { target: { value: "from-manager" } });
    expect(pw).toHaveValue("from-manager");
  });

  it("can reveal the password to check a paste, and contains no cognitive test", () => {
    const { container } = render(<LoginScreen />);
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    expectNoPuzzle(container);
  });
});

describe("ChangePasswordScreen (SCR-004)", () => {
  it("allows paste into the current and both new password fields, and has no puzzle", () => {
    const { container } = render(<ChangePasswordScreen />);
    const fields = container.querySelectorAll<HTMLInputElement>("input[type=password]");
    expect(fields).toHaveLength(3);
    const hints = [...fields].map((f) => f.getAttribute("autocomplete"));
    expect(hints).toEqual(["current-password", "new-password", "new-password"]);
    for (const f of fields) {
      expectFillable(f, f.getAttribute("autocomplete") ?? "");
      expect(pasteAllowed(f, "pasted-secret")).toBe(true);
    }
    expectNoPuzzle(container);
  });
});

describe("StepUpDialog (SCR-006)", () => {
  it("allows paste into the password and the one-time code, with the hints managers key on", () => {
    const { container } = render(<StepUpDialog {...STEP_UP} />);
    const dialog = screen.getByRole("alertdialog");
    const pw = within(dialog).getByLabelText("Password");
    const code = within(dialog).getByLabelText("Authenticator code");
    expectFillable(pw, "current-password");
    expectFillable(code, "one-time-code");
    expect(code).toHaveAttribute("inputmode", "numeric");
    expect(pw).not.toHaveAttribute("maxlength");
    expect(pasteAllowed(pw, "correct horse")).toBe(true);
    expect(pasteAllowed(code, "123456")).toBe(true);
    fireEvent.change(code, { target: { value: "123456" } });
    expect(code).toHaveValue("123456");
    expectNoPuzzle(container);
  });

  it("allows paste into the typed confirmation: copying the target is the whole task", () => {
    const { container } = render(
      <StepUpDialog {...STEP_UP} actionSummary="Rotate API key" target="sub_002" />,
    );
    const typed = screen.getByLabelText(/Type sub_002 to confirm/u);
    expect(typed).not.toHaveAttribute("readonly");
    expect(pasteAllowed(typed, "sub_002")).toBe(true);
    fireEvent.change(typed, { target: { value: "sub_002" } });
    expect(typed).toHaveValue("sub_002");
    expectNoPuzzle(container);
  });
});
