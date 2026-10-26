// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act, useState, type JSX } from "react";
import { composeStories } from "@storybook/react-vite";
import { describe, expect, it, vi } from "vitest";
import { StepUpDialog, stepUpOutcomePending } from "../src/components/index.js";
import * as stories from "../src/components/StepUpDialog.stories.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const { Default, TypedConfirmation, Submitting, Failure, NotSent, UnknownOutcome, Expired } =
  composeStories(stories);

/** Sets a controlled input's value the way a keystroke does, so React sees the change. */
function type(input: Element | null, value: string): void {
  if (!(input instanceof HTMLInputElement)) throw new Error("not an input");
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

const byLabel = (host: HTMLElement, text: string): HTMLInputElement | null => {
  const label = Array.from(host.querySelectorAll("label")).find((l) => l.textContent === text);
  return label ? host.querySelector<HTMLInputElement>(`[id="${label.htmlFor}"]`) : null;
};
const button = (host: HTMLElement, name: string): HTMLButtonElement | undefined =>
  Array.from(host.querySelectorAll("button")).find((b) => b.textContent === name);

describe("StepUpDialog (SCR-006, E09-D06)", () => {
  it.each([
    ["Default", Default],
    ["TypedConfirmation", TypedConfirmation],
    ["Submitting", Submitting],
    ["Error", Failure],
    ["NotSent", NotSent],
    ["UnknownOutcome", UnknownOutcome],
    ["Expired", Expired],
  ])("%s has no serious or critical axe violations", async (_name, Story) => {
    const host = await mount(<Story />);
    const { violations } = await axe.run(host, { rules: { "color-contrast": { enabled: false } } });
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("is an alertdialog described by the summary alone, with focus on the password", async () => {
    const host = await mount(<Default />);
    const dialog = host.querySelector('[role="alertdialog"]');
    const description = document.getElementById(dialog?.getAttribute("aria-describedby") ?? "");
    expect(description?.textContent).toBe("Release kill switch, scope global");
    expect(dialog?.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(byLabel(host, "Password"));
  });

  it("leaves the description out when the challenge carries no summary", async () => {
    const host = await mount(
      <StepUpDialog actionSummary={null} target={null} onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(host.querySelector('[role="alertdialog"]')?.hasAttribute("aria-describedby")).toBe(
      false,
    );
    expect(host.textContent).not.toContain("Action:");
  });

  it("enables Confirm only for a six-digit code and the exact target, then submits", async () => {
    const onSubmit = vi.fn();
    const host = await mount(
      <StepUpDialog actionSummary="x" target="sub_002" onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    const confirm = button(host, "Confirm");
    await act(async () => {
      type(byLabel(host, "Password"), "pw");
      type(byLabel(host, "Authenticator code"), "12345");
      type(byLabel(host, "Type sub_002 to confirm (case-sensitive)"), "sub_002");
    });
    expect(confirm?.disabled).toBe(true);
    await act(async () => type(byLabel(host, "Authenticator code"), "123456"));
    expect(confirm?.disabled).toBe(false);
    await act(async () =>
      type(byLabel(host, "Type sub_002 to confirm (case-sensitive)"), "Sub_002"),
    );
    expect(confirm?.disabled).toBe(true);
    await act(async () =>
      type(byLabel(host, "Type sub_002 to confirm (case-sensitive)"), "sub_002"),
    );
    await act(async () => confirm?.click());
    expect(onSubmit).toHaveBeenCalledWith({ password: "pw", code: "123456" });
  });

  it("never submits while submitting", async () => {
    const onSubmit = vi.fn();
    const host = await mount(
      <StepUpDialog
        actionSummary="x"
        target={null}
        submitting
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    await act(async () => {
      type(byLabel(host, "Password"), "pw");
      type(byLabel(host, "Authenticator code"), "123456");
    });
    await act(async () => host.querySelector("form")?.requestSubmit());
    expect(onSubmit).not.toHaveBeenCalled();
    expect(host.querySelector('[role="alertdialog"]')?.getAttribute("aria-busy")).toBe("true");
  });

  it("announces a failure assertively and clears the code on each new failure", async () => {
    let fail: () => void = () => undefined;
    function Harness(): JSX.Element {
      const [seq, setSeq] = useState(0);
      fail = () => setSeq((n) => n + 1);
      const failure = seq === 0 ? null : { message: "Invalid password or code.", seq };
      return (
        <StepUpDialog
          actionSummary="x"
          target={null}
          failure={failure}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
        />
      );
    }
    const host = await mount(<Harness />);
    const code = (): HTMLInputElement | null => byLabel(host, "Authenticator code");
    await act(async () => type(code(), "123456"));
    expect(host.querySelector('[role="alert"]')).toBeNull();
    await act(async () => fail());
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("Invalid password or code.");
    expect(code()?.getAttribute("aria-invalid")).toBe("true");
    expect(code()?.value).toBe("");
    await act(async () => type(code(), "654321"));
    await act(async () => fail());
    expect(code()?.value).toBe("");
  });

  it("cancels on Esc and cycles Tab inside the dialog", async () => {
    const onCancel = vi.fn();
    const host = await mount(
      <StepUpDialog actionSummary="x" target={null} onSubmit={vi.fn()} onCancel={onCancel} />,
    );
    const dialog = host.querySelector('[role="alertdialog"]') as HTMLElement;
    const key = (init: KeyboardEventInit): void => {
      dialog.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, ...init }));
    };
    key({ key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(button(host, "Cancel"));
    key({ key: "Tab" });
    expect(document.activeElement).toBe(byLabel(host, "Password"));
    key({ key: "Tab" }); // not on the last stop: the browser moves focus, the dialog does nothing
    key({ key: "Enter" });
    key({ key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("points the unknown outcome at where the read-back shows it", () => {
    expect(stepUpOutcomePending("Orders")).toBe("Outcome pending, see Orders");
  });
});
