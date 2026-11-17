/**
 * #5561: SCR-006 over an open CMP-043 dialog (a step-up asked from inside one, as SCR-123's invite asks). The
 * password takes the focus at once, with no fight against the dialog's own focus trap, `Esc` is SCR-006's
 * wherever the focus is, and closing it gives the focus back to the dialog, live again. The idle lock over it
 * leaves it open, as before: E09-D06's close-first rule (§2 item 8, §6) is not built, and this fix does not
 * build it. SCR-006 raised while the lock is up stays under the lock, as before. Runs with and without
 * Chromium's native `inert` emulated.
 */
import { StrictMode, useState, type JSX } from "react";
import { Dialog } from "@candleviewer/ui";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SessionLockDialog } from "../../../src/features/session/SessionLockDialog";
import { StepUpDialog } from "../../../src/features/stepUp/StepUpDialog";
import { inertMode } from "../../helpers/nativeInert";
import { watchFocus } from "../../helpers/watchFocus";

const BELOW = '[inert], [aria-hidden="true"]';

function Invite({
  stepUp,
  lock = false,
}: {
  readonly stepUp: boolean;
  readonly lock?: boolean;
}): JSX.Element {
  return (
    <>
      <main>
        <h1>Users</h1>
      </main>
      <Dialog open onOpenChange={() => undefined} title="Invite user">
        <label>
          Username
          <input />
        </label>
      </Dialog>
      {stepUp ? (
        <StepUpDialog
          actionSummary="Invite annie as a viewer"
          target={null}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
        />
      ) : null}
      {lock ? <SessionLockDialog idleMinutes={15} phase="locked" onUnlock={vi.fn()} /> : null}
    </>
  );
}

const invite = (): HTMLElement => screen.getByRole("dialog", { name: "Invite user", hidden: true });
const named = (name: string): HTMLElement =>
  screen.getByRole("alertdialog", { name, hidden: true });
const flush = (): Promise<void> => act(async () => undefined);

describe.each([
  ["no native inert", false],
  ["native inert", true],
] as const)("SCR-006 over a CMP-043 dialog (%s)", (_mode, native) => {
  inertMode(native);

  it("the password takes the focus at once, and the dialog under it is inert", async () => {
    const view = render(<Invite stepUp={false} />);
    expect(screen.getByRole("textbox", { name: "Username" })).toHaveFocus();
    const watch = watchFocus();
    view.rerender(<Invite stepUp />);
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(watch.count()).toBe(1);
    expect(watch.errors).toEqual([]);
    expect(invite().closest(BELOW)).not.toBeNull();
    await flush();
    expect(named("Confirm with two-factor").closest(BELOW)).toBeNull(); // spared by the inert page
  });

  it("Esc with the focus on body cancels SCR-006 and leaves the dialog under it open", async () => {
    const onCancel = vi.fn();
    function Ask({ stepUp }: { readonly stepUp: boolean }): JSX.Element {
      const [open, setOpen] = useState(true);
      return (
        <>
          <Dialog open={open} onOpenChange={setOpen} title="Invite user">
            <label>
              Username
              <input />
            </label>
          </Dialog>
          {stepUp ? (
            <StepUpDialog
              actionSummary="Invite annie"
              target={null}
              onSubmit={vi.fn()}
              onCancel={onCancel}
            />
          ) : null}
        </>
      );
    }
    const view = render(<Ask stepUp={false} />);
    const field = screen.getByRole("textbox", { name: "Username" });
    fireEvent.change(field, { target: { value: "annie" } });
    const watch = watchFocus();
    view.rerender(<Ask stepUp />);
    expect(screen.getByLabelText("Password")).toHaveFocus();
    (document.activeElement as HTMLElement).blur(); // a press on the card's own text
    fireEvent.keyDown(document.body, { key: "Escape" });
    await flush();
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(invite()).toBeInTheDocument();
    expect(field).toHaveValue("annie");
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("closing it gives the focus back to the dialog's field, live again", () => {
    const view = render(<Invite stepUp={false} />);
    const field = screen.getByRole("textbox", { name: "Username" });
    const watch = watchFocus();
    view.rerender(<Invite stepUp />);
    view.rerender(<Invite stepUp={false} />);
    expect(field).toHaveFocus();
    expect(invite().closest(BELOW)).toBeNull();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("the lock over SCR-006 leaves it open, as before; after unlock it has the focus again", () => {
    const view = render(<Invite stepUp={false} />);
    const watch = watchFocus();
    view.rerender(<Invite stepUp />); // raised from inside the open dialog, as the gate does
    const stepUp = named("Confirm with two-factor");
    const password = within(stepUp).getByLabelText("Password");
    expect(password).toHaveFocus();
    fireEvent.change(password, { target: { value: "typed" } });
    view.rerender(<Invite stepUp lock />);
    expect(within(named("Session locked")).getByLabelText("Password")).toHaveFocus();
    expect(stepUp).toBeInTheDocument(); // no close-first: SCR-006 waits under the lock
    expect(stepUp.closest(BELOW)).not.toBeNull();
    view.rerender(<Invite stepUp />); // unlocked
    expect(password).toHaveFocus();
    expect(password).toHaveValue("typed");
    expect(invite().closest(BELOW)).not.toBeNull(); // still under SCR-006
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });

  it("SCR-006 raised while the lock is up stays under it: the lock keeps the focus and stays live", async () => {
    function Locked({ stepUp }: { readonly stepUp: boolean }): JSX.Element {
      return (
        <>
          <main>
            <h1>Users</h1>
            {stepUp ? (
              <StepUpDialog
                actionSummary="Invite annie"
                target={null}
                onSubmit={vi.fn()}
                onCancel={vi.fn()}
              />
            ) : null}
          </main>
          <SessionLockDialog idleMinutes={15} phase="locked" onUnlock={vi.fn()} />
        </>
      );
    }
    const view = render(<Locked stepUp={false} />);
    const lock = named("Session locked");
    const password = within(lock).getByLabelText("Password");
    expect(password).toHaveFocus();
    const watch = watchFocus();
    view.rerender(<Locked stepUp />); // a step-up answered after the lock came
    await flush();
    const stepUp = named("Confirm with two-factor");
    expect(password).toHaveFocus();
    expect(lock.closest(BELOW)).toBeNull();
    expect(stepUp.compareDocumentPosition(lock) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(stepUp.closest(BELOW)).not.toBeNull();
    expect(watch.count()).toBeLessThan(5);
    expect(watch.errors).toEqual([]);
  });
  it("under StrictMode, SCR-006 raised under the lock keeps the dialog under it held when the lock goes", async () => {
    function Seq({
      lock,
      stepUp,
    }: {
      readonly lock: boolean;
      readonly stepUp: boolean;
    }): JSX.Element {
      return (
        <StrictMode>
          <Invite stepUp={stepUp} lock={lock} />
        </StrictMode>
      );
    }
    const view = render(<Seq lock={false} stepUp={false} />);
    await flush();
    view.rerender(<Seq lock stepUp={false} />);
    await flush();
    view.rerender(<Seq lock stepUp />); // a step-up answered after the lock came
    await flush();
    const watch = watchFocus();
    view.rerender(<Seq lock={false} stepUp />); // unlocked: before any microtask
    expect(invite().closest(BELOW)).not.toBeNull();
    expect(invite().contains(document.activeElement)).toBe(false);
    await flush();
    expect(invite().closest(BELOW)).not.toBeNull();
    expect(watch.count()).toBeLessThan(10);
    expect(watch.errors).toEqual([]);
  });

  it("unmounted, it leaves no Esc claim behind: a later Esc on body cancels nothing", () => {
    const onCancel = vi.fn();
    const view = render(
      <StepUpDialog
        actionSummary="Invite annie"
        target={null}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
    );
    view.unmount();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });
});
