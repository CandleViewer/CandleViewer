// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Button,
  ConfirmDialog,
  type ConfirmDialogProps,
  type ConfirmMeta,
} from "../src/components/index.js";
import { clampHold } from "../src/components/internal/holdGate.js";
import { mount } from "./theme/mount.js";

/** Fake timers fake `Date`, so the dialog's clock and its timers move together. */
const now = (): number => Date.now();
beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const screen = (): ReturnType<typeof within> => within(document.body);
const LABEL = "Flatten 4 positions — all accounts, LIVE + DEMO";
const ARMED = "Press again to flatten 4 positions — all accounts, LIVE + DEMO";
const confirmButton = (): HTMLElement =>
  screen().getByRole("button", { name: /flatten 4 positions/i });
const ring = (): HTMLElement => screen().getByRole("progressbar");

type Extra = Partial<Omit<ConfirmDialogProps, "open">>;

function Host({ onConfirm, onCancel, ...props }: Extra): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <ConfirmDialog
        open={open}
        title="Flatten everything?"
        restatement={<p>Closes 4 positions at market.</p>}
        confirmLabel={LABEL}
        variant="hold"
        now={now}
        onConfirm={(meta) => onConfirm?.(meta)}
        onCancel={(reason) => {
          onCancel?.(reason);
          setOpen(false);
        }}
        {...props}
      />
    </>
  );
}

/** Opens the dialog and, unless `guard` is kept, waits out the 400 ms activation guard. */
const openHost = async (props: Extra = {}, guard = false): Promise<HTMLElement> => {
  const host = await mount(<Host {...props} />);
  const opener = within(host).getByRole("button", { name: "Open" });
  await act(async () => {
    opener.focus();
    fireEvent.click(opener);
  });
  if (!guard) await advance(400);
  return host;
};

/** jsdom has no PointerEvent: a MouseEvent of the pointer type carries `button` to React's handler. */
const pointer = async (
  target: Element,
  type: "pointerdown" | "pointerup",
  button = 0,
): Promise<void> => {
  await act(async () => {
    fireEvent(target, new MouseEvent(type, { bubbles: true, cancelable: true, button }));
  });
};
const pointerDown = (target: HTMLElement): Promise<void> => pointer(target, "pointerdown");
const pointerUp = (target: HTMLElement): Promise<void> => pointer(target, "pointerup");
const key = async (
  kind: "keyDown" | "keyUp",
  name: string,
  repeat = false,
  target: Element = document.activeElement ?? document.body,
): Promise<void> => {
  await act(async () => {
    fireEvent[kind](target, { key: name, repeat });
  });
};
const focusConfirm = async (): Promise<HTMLElement> => {
  const target = confirmButton();
  await act(async () => target.focus());
  return target;
};

describe("ConfirmDialog hold (CMP-044, H25)", () => {
  it("clamps holdDurationMs to 300–2,000 ms, 800 by default (H2)", () => {
    expect(clampHold(undefined)).toBe(800);
    expect(clampHold(Number.NaN)).toBe(800);
    expect(clampHold(100)).toBe(300);
    expect(clampHold(5000)).toBe(2000);
    expect(clampHold(1200)).toBe(1200);
  });

  it("renders the ring as a progressbar named by Confirm, at 0 %", async () => {
    await openHost();
    expect(ring()).toHaveAccessibleName(LABEL);
    expect(ring()).toHaveAttribute("aria-valuenow", "0");
    expect(ring()).toHaveAttribute("aria-valuetext", "0 %");
    expect(confirmButton()).toBeEnabled();
  });

  it("Gherkin 'Hold-to-confirm gate': a release at 400 ms fires nothing and resets the progress", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = confirmButton();
    await pointerDown(target);
    await advance(400);
    expect(target).toHaveAttribute("data-holding", "");
    await pointerUp(target);
    await advance(2000);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(ring()).toHaveAttribute("aria-valuenow", "0");
    expect(target).not.toHaveAttribute("data-holding");
  });

  it("a pointer hold fires at the duration, never before, once", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = confirmButton();
    await pointerDown(target);
    await advance(799);
    expect(onConfirm).not.toHaveBeenCalled();
    await advance(1);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenLastCalledWith<[ConfirmMeta]>({
      variant: "hold",
      gate: "pointer-hold",
      elapsedMs: 1200,
    });
    await pointerUp(target);
    await pointerDown(target);
    await advance(2000);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("the ring redraws at up to 10 Hz and its value text at up to 2 Hz", async () => {
    await openHost();
    const target = confirmButton();
    const fill = document.querySelector(".cv-confirm__fill");
    await pointerDown(target);
    await advance(100);
    expect(Number(fill?.getAttribute("stroke-dashoffset"))).toBeCloseTo(87.5);
    await advance(300);
    expect(ring()).toHaveAttribute("aria-valuenow", "0");
    await advance(100);
    expect(ring()).toHaveAttribute("aria-valuenow", "62");
    expect(ring()).toHaveAttribute("aria-valuetext", "62 %");
  });

  it("a synthetic click(), a pointerdown/pointerup pair and two clicks never confirm nor arm", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = confirmButton();
    await act(async () => target.click());
    await pointerDown(target);
    await pointerUp(target);
    await act(async () => {
      fireEvent.click(target);
    });
    await advance(300);
    await act(async () => {
      fireEvent.click(target);
    });
    await advance(3000);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(confirmButton()).toHaveAccessibleName(LABEL);
    expect(target).not.toHaveAttribute("data-armed");
  });

  it("a right-button press starts no hold", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    await pointer(confirmButton(), "pointerdown", 2);
    await advance(2000);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("the guard: a pointer or Enter press that begins in the first 400 ms starts nothing", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm }, true);
    const target = await focusConfirm();
    await advance(100);
    await pointerDown(target);
    await key("keyDown", "Enter");
    await advance(1500);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(target).not.toHaveAttribute("data-armed");
  });

  it("keyboard: holding Enter (repeats included) for the duration fires key-hold", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    await focusConfirm();
    await key("keyDown", "Enter");
    for (let i = 0; i < 7; i += 1) {
      await advance(100);
      await key("keyDown", "Enter", true);
    }
    expect(onConfirm).not.toHaveBeenCalled();
    await advance(100);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).toMatchObject({ variant: "hold", gate: "key-hold" });
  });

  it("keyboard: the first Enter arms and renames Confirm, spoken politely once", async () => {
    await openHost();
    const target = await focusConfirm();
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    expect(target).toHaveAccessibleName(ARMED);
    expect(target).toHaveAttribute("data-armed", "");
    expect(ring()).toHaveAccessibleName(ARMED);
    const statuses: HTMLElement[] = screen().getAllByRole("status");
    expect(statuses.filter((s: HTMLElement) => s.textContent === ARMED)).toHaveLength(1);
    // The release at once kept no progress.
    expect(ring()).toHaveAttribute("aria-valuenow", "0");
  });

  it("keyboard: a second non-repeat Enter 250 ms – 5 s later fires double-press", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    await focusConfirm();
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    await advance(249);
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    expect(onConfirm).not.toHaveBeenCalled();
    await advance(1);
    await key("keyDown", "Enter");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).toMatchObject({ gate: "double-press" });
  });

  it("keyboard: the armed window closes after 5 s; a later press only re-arms", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = await focusConfirm();
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    await advance(5000);
    expect(target).toHaveAccessibleName(LABEL);
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    expect(onConfirm).not.toHaveBeenCalled();
    expect(target).toHaveAccessibleName(ARMED);
  });

  it("Space never holds: a held Space is one press, armed on its keyup; a second press confirms", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = await focusConfirm();
    await key("keyDown", " ");
    for (let i = 0; i < 20; i += 1) {
      await advance(100);
      await key("keyDown", " ", true);
    }
    expect(onConfirm).not.toHaveBeenCalled();
    expect(target).not.toHaveAttribute("data-armed");
    await key("keyUp", " ");
    expect(target).toHaveAccessibleName(ARMED);
    await advance(300);
    await key("keyDown", " ");
    expect(onConfirm).not.toHaveBeenCalled();
    await key("keyUp", " ");
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).toMatchObject({ gate: "double-press" });
  });

  it("a Space keyup without its own press on Confirm counts for nothing", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = await focusConfirm();
    await key("keyUp", " ");
    expect(target).not.toHaveAttribute("data-armed");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("a pointer press never counts as the second press", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = await focusConfirm();
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    await advance(500);
    await pointerDown(target);
    await pointerUp(target);
    await act(async () => {
      fireEvent.click(target);
    });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("blur disarms and drops a key hold", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm });
    const target = await focusConfirm();
    await key("keyDown", "Enter");
    await advance(300);
    await act(async () => screen().getByRole("button", { name: "Cancel" }).focus());
    expect(target).toHaveAccessibleName(LABEL);
    await advance(1000);
    expect(onConfirm).not.toHaveBeenCalled();
    await act(async () => target.focus());
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    expect(target).toHaveAccessibleName(ARMED);
  });

  it("Esc disarms and the dialog cancels; nothing confirms", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    await openHost({ onConfirm, onCancel });
    await focusConfirm();
    await key("keyDown", "Enter");
    await key("keyUp", "Enter");
    await key("keyDown", "Escape");
    expect(onCancel).toHaveBeenLastCalledWith("escape");
    await advance(2000);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("a hold Confirm gated mid-hold drops the hold and fires nothing", async () => {
    const onConfirm = vi.fn();
    const host = await mount(<Gated onConfirm={onConfirm} />);
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Open" }));
    });
    await advance(400);
    const target = confirmButton();
    await pointerDown(target);
    await advance(400);
    await act(async () => {
      // The page behind the modal is inert to AT: the test reaches the host's control by its text.
      const gate = within(host).getByText("Gate").closest("button");
      if (gate !== null) fireEvent.click(gate);
    });
    await advance(1000);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(ring()).toHaveAttribute("aria-valuenow", "0");
  });

  it("hold with a token: no press starts until the field matches", async () => {
    const onConfirm = vi.fn();
    await openHost({ onConfirm, typedConfirmValue: "FLATTEN" });
    expect(confirmButton()).toBeDisabled();
    const field = screen().getByRole("textbox", { name: "Type FLATTEN to confirm" });
    await act(async () => {
      fireEvent.change(field, { target: { value: "FLATTEN" } });
    });
    await advance(400);
    await pointerDown(confirmButton());
    await advance(800);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).toMatchObject({ variant: "hold", gate: "pointer-hold" });
  });

  it("a custom armedLabel and a clamped duration (100 → 300 ms)", async () => {
    const onConfirm = vi.fn();
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await openHost({ onConfirm, holdDurationMs: 100, armedLabel: "Press again to flatten" });
    const target = await focusConfirm();
    await key("keyDown", "Enter");
    expect(target).toHaveAccessibleName("Press again to flatten");
    await advance(299);
    expect(onConfirm).not.toHaveBeenCalled();
    await advance(1);
    expect(onConfirm.mock.calls[0]?.[0]).toMatchObject({ gate: "key-hold" });
  });
});

/** A host that gates Confirm on demand (H30), outside the dialog's trap for the test only. */
function Gated({ onConfirm }: { onConfirm: (meta: ConfirmMeta) => void }): JSX.Element {
  const [gated, setGated] = useState(false);
  return (
    <>
      <Button onClick={() => setGated(true)}>Gate</Button>
      <Host
        onConfirm={onConfirm}
        {...(gated ? { confirmDisabledReason: "Your role can't use the kill switch." } : {})}
      />
    </>
  );
}

describe("ConfirmDialog autoCancelMs (CMP-044, E30-D03 D3)", () => {
  const order: Extra = { variant: "standard", role: "dialog", autoCancelMs: 20_000 };

  it("shows 'Cancels in 0:20' at the footer's start, read as a sentence", async () => {
    await openHost(order);
    const line = document.querySelector(".cv-confirm__countdown");
    expect(line).toHaveTextContent("Cancels in 0:20");
    expect(line?.querySelector('[aria-live="off"]')).not.toBeNull();
    expect(line?.textContent).toContain("unless you act");
  });

  it("speaks politely at 0:10 and 0:00 only, and cancels at 0:00, never confirming", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    await openHost({ ...order, onConfirm, onCancel });
    const status = (): string =>
      document.querySelector(".cv-confirm__countdown [role='status']")?.textContent ?? "";
    await advance(9_000);
    expect(status()).toBe("");
    await advance(1_000);
    expect(status()).toBe("10 seconds until this confirmation cancels");
    expect(onCancel).not.toHaveBeenCalled();
    await advance(10_000);
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenLastCalledWith("timeout");
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(screen().getByRole("button", { name: "Open" })).toHaveFocus();
  });

  it("any key or pointer input restarts the count", async () => {
    const onCancel = vi.fn();
    await openHost({ ...order, onCancel });
    await advance(15_000);
    await key("keyDown", "Shift", false, document.body);
    expect(document.querySelector(".cv-confirm__countdown")).toHaveTextContent("Cancels in 0:20");
    await advance(15_000);
    await pointer(document.body, "pointerdown");
    await advance(19_000);
    expect(onCancel).not.toHaveBeenCalled();
    await advance(1_000);
    expect(onCancel).toHaveBeenLastCalledWith("timeout");
  });

  it("stops once Confirm has fired: a busy send is never cancelled by the count", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    await openHost({ ...order, onConfirm, onCancel });
    await act(async () => {
      fireEvent.click(confirmButton());
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".cv-confirm__countdown")).toBeNull();
    await advance(30_000);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("a hold in progress at 0:00 is dropped: the expiry cancels, never confirms", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    await openHost({
      variant: "hold",
      holdDurationMs: 2_000,
      autoCancelMs: 1_000,
      onConfirm,
      onCancel,
    });
    // The press restarts the count to 1 s, which ends before the 2 s hold.
    await pointerDown(confirmButton());
    await advance(1_000);
    expect(onCancel).toHaveBeenLastCalledWith("timeout");
    await advance(2_000);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
