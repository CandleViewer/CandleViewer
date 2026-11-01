// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Button,
  ConfirmDialog,
  type ConfirmDialogProps,
  type ConfirmMeta,
} from "../src/components/index.js";
import { visibleTabbables } from "../src/components/internal/focusTrap.js";
import { mount } from "./theme/mount.js";

/** The injected clock: the dialog opens at t = 1000; a test moves `t` to time a press. */
let t = 1000;
const now = (): number => t;
beforeEach(() => {
  t = 1000;
});
afterEach(() => vi.restoreAllMocks());

const screen = (): ReturnType<typeof within> => within(document.body);
const alert = (name: string): HTMLElement =>
  screen().getByRole("alertdialog", { name }) as HTMLElement;
const button = (name: string | RegExp): HTMLElement =>
  screen().getByRole("button", { name }) as HTMLElement;

type Extra = Partial<Omit<ConfirmDialogProps, "open">>;

/** A host: the opener and a confirm it owns; Cancel and Confirm close it as a host would. */
function Host({ onConfirm, onCancel, ...props }: Extra): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <ConfirmDialog
        open={open}
        title="Freeze sub_001?"
        message="Cancels its working orders; positions stay open."
        restatement={<p>Cancels 3 working orders on sub_001.</p>}
        confirmLabel="Freeze sub_001 — cancel 3 working orders"
        now={now}
        onConfirm={(meta) => {
          onConfirm?.(meta);
        }}
        onCancel={(reason) => {
          onCancel?.(reason);
          setOpen(false);
        }}
        {...props}
      />
    </>
  );
}

const openHost = async (props: Extra = {}): Promise<HTMLElement> => {
  const host = await mount(<Host {...props} />);
  const opener = within(host).getByRole("button", { name: "Open" });
  await act(async () => opener.focus());
  await act(async () => {
    fireEvent.click(opener);
  });
  return host;
};

/** Esc on the focused element, flushed: the layer stack closes the topmost layer. */
const escape = async (): Promise<void> => {
  await act(async () => {
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  });
};

const confirmButton = (): HTMLElement => button(/^Freeze sub_001 — cancel/);

describe("ConfirmDialog (CMP-044)", () => {
  it("standard: an alertdialog named by its title, described by the restatement, focus on Cancel", async () => {
    await openHost();
    const node = alert("Freeze sub_001?");
    expect(node).toHaveAttribute("aria-modal", "true");
    expect(node).toHaveAccessibleDescription(
      "Cancels its working orders; positions stay open. What this does Cancels 3 working orders on sub_001.",
    );
    expect(within(node).getByRole("group", { name: "What this does" })).toBeVisible();
    expect(within(node).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(within(node).queryByRole("button", { name: /^Close/ })).toBeNull();
    expect(confirmButton()).toHaveAttribute("data-variant", "danger");
    expect(confirmButton()).toBeEnabled();
    expect(node.querySelectorAll('[data-cmp="CMP-044"]')).toHaveLength(1);
  });

  it("Cancel and Esc cancel with their reason; focus returns to the opener", async () => {
    const onCancel = vi.fn();
    const host = await openHost({ onCancel });
    await act(async () => {
      fireEvent.click(button("Cancel"));
    });
    expect(onCancel).toHaveBeenLastCalledWith("cancel");
    expect(screen().queryByRole("alertdialog")).toBeNull();
    expect(within(host).getByRole("button", { name: "Open" })).toHaveFocus();
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Open" }));
    });
    await escape();
    expect(onCancel).toHaveBeenLastCalledWith("escape");
  });

  it("the 400 ms guard: a stray click or a single Enter inside it does nothing", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    t = 1100;
    await userEvent.click(confirmButton());
    t = 1399;
    await act(async () => confirmButton().focus());
    await userEvent.keyboard("{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    t = 1400;
    await userEvent.keyboard("{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenLastCalledWith<[ConfirmMeta]>({
      variant: "standard",
      gate: "click",
      elapsedMs: 400,
    });
  });

  it("a press that begins inside the guard does nothing when it ends after it (pointer and Space)", async () => {
    const onConfirm = vi.fn();
    // One session, so the button or key pressed in one call is the one released in the next.
    const user = userEvent.setup();
    await openHost({ onConfirm });
    const target = confirmButton();
    const clicks = vi.fn();
    target.addEventListener("click", clicks);
    t = 1300;
    await user.pointer({ keys: "[MouseLeft>]", target });
    t = 1600;
    await user.pointer({ keys: "[/MouseLeft]", target });
    // The release did click: the guard, not a missing event, rejected it.
    expect(clicks).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    await act(async () => target.focus());
    t = 1350;
    await user.keyboard("[Space>]");
    t = 1700;
    await user.keyboard("[/Space]");
    expect(clicks).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
    t = 1800;
    await user.click(target);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("held-Enter repeats are ignored: one press, one confirm; Cancel ignores repeats too", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    t = 2000;
    const confirm = confirmButton();
    await act(async () => confirm.focus());
    const user = userEvent.setup();
    await user.keyboard("{Enter>}");
    // The repeats a held key sends: each is cancelled, so the browser activates nothing.
    for (let i = 0; i < 3; i += 1)
      expect(fireEvent.keyDown(confirm, { key: "Enter", repeat: true })).toBe(false);
    await user.keyboard("{/Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(fireEvent.keyDown(confirm, { key: " ", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(confirm, { key: "a", repeat: true })).toBe(true);
    expect(fireEvent.keyDown(button("Cancel"), { key: "Enter", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(button("Cancel"), { key: "Enter" })).toBe(true);
  });

  it("Gherkin 'Typed confirm': with FLATTEN required, other text keeps Confirm disabled with the instruction", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm, variant: "typed", typedConfirmValue: "FLATTEN" });
    const field = screen().getByRole("textbox", { name: "Type FLATTEN to confirm" });
    const confirm = confirmButton();
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAccessibleDescription("Type FLATTEN to confirm");
    expect(confirm).not.toHaveAttribute("aria-disabled");
    expect(button("Cancel")).toHaveFocus();
    t = 3000;
    for (const text of ["flatten", "FLATTEN ", " FLATTEN", "FLATTE"]) {
      await userEvent.clear(field);
      await userEvent.type(field, text);
      expect(confirm).toBeDisabled();
    }
    await userEvent.clear(field);
    await userEvent.type(field, "FLATTEN");
    expect(confirm).toBeEnabled();
    // Enter in the field never confirms.
    expect(fireEvent.keyDown(field, { key: "Enter" })).toBe(false);
    await userEvent.type(field, "{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    // The match rearmed the guard: a click on the instant Confirm enables does nothing.
    await userEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    t = 3400;
    await userEvent.click(confirm);
    // The field's text as typed rides with the confirm, so a host whose server checks an echo sends what was
    // typed, never its own copy of the token (E16-D06 §20.3 (ii)); a standard confirm carries none (above).
    expect(onConfirm).toHaveBeenLastCalledWith<[ConfirmMeta]>({
      variant: "typed",
      gate: "typed",
      elapsedMs: 2400,
      typedValue: "FLATTEN",
    });
  });

  it("typed: paste is allowed; the field is cleared on every open", async () => {
    await openHost({ variant: "typed", typedConfirmValue: "BTCUSDT" });
    const field = screen().getByRole("textbox", { name: "Type BTCUSDT to confirm" });
    await act(async () => field.focus());
    await userEvent.paste("BTCUSDT");
    expect(field).toHaveValue("BTCUSDT");
    expect(confirmButton()).toBeEnabled();
    await escape();
    await act(async () => {
      fireEvent.click(button("Open"));
    });
    expect(screen().getByRole("textbox", { name: "Type BTCUSDT to confirm" })).toHaveValue("");
    expect(confirmButton()).toBeDisabled();
  });

  it("typed: a host instruction labels the field and describes Confirm", async () => {
    await openHost({
      variant: "typed",
      typedConfirmValue: "alex",
      typedInstruction: "Type the username alex to delete it",
    });
    const field = screen().getByRole("textbox", { name: "Type the username alex to delete it" });
    expect(confirmButton()).toHaveAccessibleDescription("Type the username alex to delete it");
    await userEvent.type(field, "alex");
    expect(confirmButton()).toBeEnabled();
  });

  it("the summary still loading keeps Confirm natively disabled (availability, not T2)", async () => {
    const onConfirm = vi.fn();
    await mount(
      <ConfirmDialog
        open
        title="Flatten all?"
        confirmLabel="Flatten 4 positions"
        variant="typed"
        typedConfirmValue="FLATTEN"
        summaryLoading
        now={now}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    await userEvent.type(
      screen().getByRole("textbox", { name: "Type FLATTEN to confirm" }),
      "FLATTEN",
    );
    const confirm = button("Flatten 4 positions");
    expect(confirm).toBeDisabled();
    expect(confirm).not.toHaveAttribute("aria-disabled");
    t = 5000;
    await act(async () => {
      fireEvent.click(confirm);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("order confirm: a dialog with its close button; Tab runs Cancel, Confirm, close, the body", async () => {
    const onCancel = vi.fn();
    await openHost({
      onCancel,
      role: "dialog",
      "aria-label": "Confirm order - BTCUSDT - LIVE - Main",
      title: "Confirm order",
      confirmVariant: "buy",
      confirmLabel: "BUY 0.250 BTCUSDT limit 64,010.0",
      variant: "typed",
      typedConfirmValue: "LIVE",
    });
    const node = screen().getByRole("dialog", { name: "Confirm order - BTCUSDT - LIVE - Main" });
    const cancel = within(node).getByRole("button", { name: "Cancel" });
    const confirm = within(node).getByRole("button", { name: /^BUY 0.250/ });
    const close = within(node).getByRole("button", { name: "Close Confirm order" });
    const field = within(node).getByRole("textbox", { name: "Type LIVE to confirm" });
    expect(cancel).toHaveFocus();
    expect(confirm).toHaveAttribute("data-variant", "buy");
    await userEvent.type(field, "LIVE");
    // DOM order from Cancel: Confirm, then the trap wraps to the close button, then the field.
    const order = visibleTabbables(node);
    expect(order.slice(order.indexOf(cancel))).toEqual([cancel, confirm]);
    expect(order.slice(0, order.indexOf(cancel))).toEqual([close, field]);
    await act(async () => confirm.focus());
    await userEvent.keyboard("{Tab}");
    expect(close).toHaveFocus();
    await userEvent.click(close);
    expect(onCancel).toHaveBeenLastCalledWith("close");
  });

  it("a scrim press: nothing for an alertdialog, Cancel for an order dialog", async () => {
    const onCancel = vi.fn();
    const scrim = (): Element => {
      const node = document.querySelector(".cv-dialog__scrim");
      if (node === null) throw new Error("no scrim");
      return node;
    };
    await openHost({ onCancel });
    await userEvent.click(scrim());
    expect(onCancel).not.toHaveBeenCalled();
    await escape();
    await act(async () => {
      fireEvent.click(button("Open"));
    });
    await escape();
    onCancel.mockClear();
    document.body.replaceChildren();
    await openHost({ onCancel, role: "dialog" });
    await userEvent.click(scrim());
    expect(onCancel).toHaveBeenLastCalledWith("scrim");
  });

  it("busy: aria-busy on the card, Confirm loading and inert to presses, the field read-only", async () => {
    const onConfirm = vi.fn();
    await mount(
      <ConfirmDialog
        open
        busy
        title="Flatten all?"
        confirmLabel="Flatten 4 positions"
        variant="typed"
        typedConfirmValue="FLATTEN"
        now={now}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    expect(alert("Flatten all?")).toHaveAttribute("aria-busy", "true");
    expect(screen().getByRole("textbox", { name: "Type FLATTEN to confirm" })).toHaveAttribute(
      "readonly",
    );
    const confirm = button(/^Flatten 4 positions/);
    expect(confirm).toHaveAttribute("aria-busy", "true");
    t = 5000;
    await act(async () => {
      fireEvent.click(confirm);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("partial failure: CMP-027's inline error with Retry above the footer", async () => {
    const retry = vi.fn();
    await mount(
      <ConfirmDialog
        open
        title="Freeze sub_001?"
        confirmLabel="Freeze sub_001"
        failure={{
          message: "2 of 3 orders were not cancelled.",
          retry: { label: "Retry", onClick: retry },
        }}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const node = alert("Freeze sub_001?");
    const error = within(node).getByText("2 of 3 orders were not cancelled.");
    expect(error.closest('[role="alert"]')).not.toBeNull();
    await userEvent.click(within(node).getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("H30: a Confirm gated mid-dialog keeps focus, speaks once assertively, then re-shows its reason politely", async () => {
    const onConfirm = vi.fn();
    let gate: (reason: string | undefined) => void = () => undefined;
    function Gated(): JSX.Element {
      const [reason, setReason] = useState<string | undefined>(undefined);
      gate = setReason;
      return (
        <ConfirmDialog
          open
          title="Freeze sub_001?"
          confirmLabel="Freeze sub_001"
          confirmDisabledReason={reason}
          now={now}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );
    }
    await mount(<Gated />);
    const node = alert("Freeze sub_001?");
    const confirm = button("Freeze sub_001");
    await act(async () => confirm.focus());
    expect(within(node).getByRole("alert")).toBeEmptyDOMElement();
    const reason = "Your role can't use the kill switch.";
    await act(async () => gate(reason));
    expect(confirm).toHaveFocus();
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toBeEnabled();
    expect(confirm).toHaveAccessibleDescription(reason);
    expect(within(node).getByRole("alert")).toHaveTextContent(reason);
    expect(node.querySelector(".cv-confirm__reason")).toHaveTextContent(reason);
    expect(within(node).getByRole("status")).toBeEmptyDOMElement();
    t = 5000;
    await userEvent.keyboard("{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    expect(within(node).getByRole("status")).toHaveTextContent(reason);
    // The same reason again is a new node in the live region, so a screen reader speaks it again.
    const spoken = within(node).getByRole("status").firstElementChild;
    await userEvent.keyboard("{Enter}");
    expect(within(node).getByRole("status").firstElementChild).not.toBe(spoken);
    expect(within(node).getByRole("status")).toHaveTextContent(reason);
    // The same reason again: still one assertive announcement.
    await act(async () => gate(` ${reason} `));
    expect(within(node).getAllByText(reason, { selector: "[role=alert] span" })).toHaveLength(1);
  });

  it("gated while focus is elsewhere: no assertive announcement; a reason that clears restores Confirm", async () => {
    const onConfirm = vi.fn();
    let gate: (reason: string | undefined) => void = () => undefined;
    function Gated(): JSX.Element {
      const [reason, setReason] = useState<string | undefined>(undefined);
      gate = setReason;
      return (
        <ConfirmDialog
          open
          title="Freeze sub_001?"
          confirmLabel="Freeze sub_001"
          confirmDisabledReason={reason}
          now={now}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );
    }
    await mount(<Gated />);
    const node = alert("Freeze sub_001?");
    await act(async () => gate("Not allowed."));
    expect(within(node).getByRole("alert")).toBeEmptyDOMElement();
    await act(async () => gate("   "));
    const confirm = button("Freeze sub_001");
    expect(confirm).not.toHaveAttribute("aria-disabled");
    t = 5000;
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("dev warnings: a bare 'Confirm' label, and typed without a token (which never enables)", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await mount(
      <ConfirmDialog
        open
        title="Delete key?"
        confirmLabel="Confirm"
        variant="typed"
        now={now}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('never "Confirm"'));
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("typedConfirmValue"));
    expect(button("Confirm")).toBeDisabled();
  });

  it("an order restatement with no group label renders as plain text, still the description", async () => {
    await mount(
      <ConfirmDialog
        open
        role="dialog"
        title="Confirm order"
        restatementLabel=""
        restatement="LIVE on Main: BUY 0.250 BTCUSDT."
        confirmLabel="BUY 0.250 BTCUSDT"
        confirmVariant="buy"
        legs={<table aria-label="Legs" />}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      >
        <p>Step-up verified.</p>
      </ConfirmDialog>,
    );
    const node = screen().getByRole("dialog", { name: "Confirm order" });
    expect(node).toHaveAccessibleDescription("LIVE on Main: BUY 0.250 BTCUSDT.");
    expect(within(node).queryByRole("group", { name: "What this does" })).toBeNull();
    expect(within(node).getByRole("table", { name: "Legs" })).toBeInTheDocument();
    expect(within(node).getByText("Step-up verified.")).toBeVisible();
  });

  it("single fire: two clicks or two Enters past the guard, with no busy from the host, confirm once", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    t = 2000;
    const confirm = confirmButton();
    await userEvent.dblClick(confirm);
    await act(async () => confirm.focus());
    await userEvent.keyboard("{Enter}{Enter}");
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("single fire: a new failure, or busy ending, allows one more confirm", async () => {
    const onConfirm = vi.fn();
    let set: (next: Pick<ConfirmDialogProps, "busy" | "failure">) => void = () => undefined;
    function Retrying(): JSX.Element {
      const [state, setState] = useState<Pick<ConfirmDialogProps, "busy" | "failure">>({});
      set = setState;
      return (
        <ConfirmDialog
          open
          title="Freeze sub_001?"
          confirmLabel="Freeze sub_001"
          now={now}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
          {...state}
        />
      );
    }
    await mount(<Retrying />);
    t = 2000;
    await userEvent.click(button("Freeze sub_001"));
    await userEvent.click(button("Freeze sub_001"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    await act(async () => set({ failure: { message: "1 of 3 orders was not cancelled." } }));
    await userEvent.click(button("Freeze sub_001"));
    await userEvent.click(button("Freeze sub_001"));
    expect(onConfirm).toHaveBeenCalledTimes(2);
    await act(async () =>
      set({ busy: true, failure: { message: "1 of 3 orders was not cancelled." } }),
    );
    await act(async () => set({ failure: { message: "1 of 3 orders was not cancelled." } }));
    await userEvent.click(button("Freeze sub_001"));
    expect(onConfirm).toHaveBeenCalledTimes(3);
  });

  it("confirmDelayMs: a longer guard holds; a shorter or non-finite one is raised to 400 with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const onConfirm = vi.fn();
    await openHost({ onConfirm, confirmDelayMs: 1000 });
    t = 1999;
    await userEvent.click(confirmButton());
    expect(onConfirm).not.toHaveBeenCalled();
    t = 2000;
    await userEvent.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(warn).not.toHaveBeenCalled();
    for (const confirmDelayMs of [0, -5, Number.NaN]) {
      await escape();
      document.body.replaceChildren();
      t = 1000;
      onConfirm.mockClear();
      await openHost({ onConfirm, confirmDelayMs });
      t = 1399;
      await userEvent.click(confirmButton());
      expect(onConfirm).not.toHaveBeenCalled();
      t = 1400;
      await userEvent.click(confirmButton());
      expect(onConfirm).toHaveBeenCalledTimes(1);
    }
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("confirmDelayMs below 400 ms"));
  });

  it("a press begun inside the guard stays rejected across a blur or a pointercancel", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = confirmButton();
    t = 1150;
    fireEvent.pointerDown(target);
    await act(async () => target.focus());
    await act(async () => target.blur());
    fireEvent.pointerCancel(target);
    t = 1700;
    await act(async () => {
      fireEvent.click(target);
    });
    expect(onConfirm).not.toHaveBeenCalled();
    // That click consumed the trip: a later press-less click (assistive technology) is measured on its own.
    await act(async () => {
      fireEvent.click(target);
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("the guard rearms when Confirm becomes available or the intent changes while open", async () => {
    const onConfirm = vi.fn();
    let set: (next: Partial<ConfirmDialogProps>) => void = () => undefined;
    function Changing(): JSX.Element {
      const [props, setProps] = useState<Partial<ConfirmDialogProps>>({ summaryLoading: true });
      set = setProps;
      return (
        <ConfirmDialog
          open
          title="Freeze sub_001?"
          confirmLabel="Freeze sub_001"
          now={now}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
          {...props}
        />
      );
    }
    await mount(<Changing />);
    t = 3000;
    await act(async () => set({}));
    t = 3399;
    await userEvent.click(button("Freeze sub_001"));
    expect(onConfirm).not.toHaveBeenCalled();
    t = 5000;
    await act(async () => set({ confirmLabel: "Freeze sub_002" }));
    t = 5399;
    await userEvent.click(button("Freeze sub_002"));
    expect(onConfirm).not.toHaveBeenCalled();
    t = 5400;
    await userEvent.click(button("Freeze sub_002"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("a click during the exit fade, after the host closed it, does nothing", async () => {
    const onConfirm = vi.fn();
    let close: () => void = () => undefined;
    function Closing(): JSX.Element {
      const [open, setOpen] = useState(true);
      close = () => setOpen(false);
      return (
        <ConfirmDialog
          open={open}
          title="Freeze sub_001?"
          confirmLabel="Freeze sub_001"
          now={now}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );
    }
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) =>
      element.classList.contains("cv-dialog__scrim")
        ? ({
            transitionDuration: "200ms",
            getPropertyValue: (name: string) =>
              ({
                "transition-property": "opacity",
                "transition-duration": "200ms",
                "transition-delay": "0s",
              })[name] ?? "",
          } as unknown as CSSStyleDeclaration)
        : real(element, pseudo),
    );
    await mount(<Closing />);
    const confirm = button("Freeze sub_001");
    await act(async () => close());
    expect(document.querySelector(".cv-dialog-layer")).toHaveAttribute("data-state", "closing");
    t = 5000;
    await act(async () => {
      fireEvent.click(confirm);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("Space released on a button activates only when its own press began there", async () => {
    await openHost();
    const cancel = button("Cancel");
    // A Space held from elsewhere: its repeats and its release on Cancel are cancelled.
    expect(fireEvent.keyDown(cancel, { key: " ", repeat: true })).toBe(false);
    expect(fireEvent.keyUp(cancel, { key: " " })).toBe(false);
    expect(fireEvent.keyDown(cancel, { key: " " })).toBe(true);
    expect(fireEvent.keyUp(cancel, { key: " " })).toBe(true);
    expect(fireEvent.keyUp(confirmButton(), { key: " " })).toBe(false);
    expect(fireEvent.keyUp(cancel, { key: "a" })).toBe(true);
  });
});

// The typed confirm's validity look (E16-D06 KB-07, KB-12, T2-07, T2-10; E16-D04 §1.3; E09-D09 §9.1: form validity is
// the host's call, never T2): with `typedReason` or `validityReason`, Confirm stays a Tab stop, `aria-disabled`, its
// fill and label dimmed, the reason under the footer as its description; a press says the reason once, politely, and
// confirms nothing. Without them `typed` keeps the native disabled state above.
describe("ConfirmDialog: the validity look", () => {
  const TYPED = "Type BTCUSDT exactly to confirm.";
  const SHORT = "Give a reason of at least 3 characters.";
  const polite = (): string =>
    document.querySelector(".cv-confirm > [role='status']")?.textContent ?? "";

  it("typedReason: focusable, aria-disabled, described by the reason; a press says it once and sends nothing", async () => {
    const onConfirm = vi.fn();
    await openHost({
      onConfirm,
      variant: "typed",
      typedConfirmValue: "BTCUSDT",
      typedReason: TYPED,
    });
    const confirm = confirmButton();
    expect(confirm).toBeEnabled();
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAttribute("data-unavailable", "");
    expect(confirm).toHaveAccessibleDescription(TYPED);
    expect(within(alert("Freeze sub_001?")).getByText(TYPED)).toBeVisible();
    expect(within(confirm).queryByRole("img", { name: "Not available" })).toBeNull();
    t = 5000;
    await userEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(polite()).toBe(TYPED);
    expect(confirm).toHaveFocus();
  });

  it("typedReason: the match lifts the look, drops the reason and rearms the guard", async () => {
    const onConfirm = vi.fn();
    await openHost({
      onConfirm,
      variant: "typed",
      typedConfirmValue: "BTCUSDT",
      typedReason: TYPED,
    });
    t = 3000;
    await userEvent.type(
      screen().getByRole("textbox", { name: "Type BTCUSDT to confirm" }),
      "BTCUSDT",
    );
    const confirm = confirmButton();
    expect(confirm).not.toHaveAttribute("aria-disabled");
    expect(confirm).not.toHaveAttribute("data-unavailable");
    expect(screen().queryByText(TYPED)).toBeNull();
    await userEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    t = 3400;
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("validityReason: the host's own rule takes the look once the token matches; the typed reason comes first", async () => {
    const onConfirm = vi.fn();
    function Form(): JSX.Element {
      const [reason, setReason] = useState("");
      return (
        <ConfirmDialog
          open
          title="Purge ETHUSDT data?"
          role="dialog"
          confirmLabel="Purge ETHUSDT data"
          variant="typed"
          typedConfirmValue="ETHUSDT"
          typedInstruction="Type the symbol to confirm"
          typedReason="Type ETHUSDT exactly to confirm."
          validityReason={reason.trim().length < 3 ? SHORT : undefined}
          now={now}
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        >
          <label>
            Reason
            <input value={reason} onChange={(event) => setReason(event.currentTarget.value)} />
          </label>
        </ConfirmDialog>
      );
    }
    await mount(<Form />);
    const confirm = button("Purge ETHUSDT data");
    expect(confirm).toHaveAccessibleDescription("Type ETHUSDT exactly to confirm.");
    await userEvent.type(
      screen().getByRole("textbox", { name: "Type the symbol to confirm" }),
      "ETHUSDT",
    );
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAccessibleDescription(SHORT);
    await userEvent.type(screen().getByRole("textbox", { name: "Reason" }), "space for the import");
    expect(confirm).not.toHaveAttribute("aria-disabled");
    t = 9000;
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("aria-describedby: a host's body node describes the dialog after the restatement", async () => {
    await mount(
      <ConfirmDialog
        open
        role="dialog"
        title="Purge ETHUSDT data?"
        confirmLabel="Purge ETHUSDT data"
        aria-describedby="purge-body"
        now={now}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      >
        <p>Symbol: ETHUSDT</p>
        <p id="purge-body">This deletes about 1.2 GB recorded from 2026-08-13 to 2026-08-15.</p>
      </ConfirmDialog>,
    );
    expect(
      screen().getByRole("dialog", { name: "Purge ETHUSDT data?" }),
    ).toHaveAccessibleDescription(
      "This deletes about 1.2 GB recorded from 2026-08-13 to 2026-08-15.",
    );
  });

  it("a gated Confirm (T2) wins over the look; notes follow the typed field, before the footer", async () => {
    await openHost({
      variant: "typed",
      typedConfirmValue: "BTCUSDT",
      typedReason: TYPED,
      confirmDisabledReason: "Only the owner can change recording.",
      notes: <p>This action is audited.</p>,
    });
    const confirm = confirmButton();
    expect(confirm).toHaveAttribute("data-gated", "");
    expect(confirm).not.toHaveAttribute("data-unavailable");
    const field = screen().getByRole("textbox", { name: "Type BTCUSDT to confirm" });
    const note = screen().getByText("This action is audited.");
    expect(field.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(note.closest(".cv-dialog__footer")).toBeNull();
  });
});
