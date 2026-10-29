// @vitest-environment jsdom
import { act } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { ConfirmDialog, type ConfirmDialogProps } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

/**
 * The CMP-044 gate matrix for E05-X02: every gate (standard, typed, hold, auto-cancel) in every Confirm state
 * (enabled, gated, pending, error), each cell one test. A cell runs the gate's full gesture past the 400 ms
 * guard and checks what fired. The deeper cases (the guard, key repeats, the keyboard hold, mid-dialog gating)
 * stay in ConfirmDialog.test.tsx and ConfirmDialogHold.test.tsx; docs/plan/qa/E05-S03-qa-handoff.md maps both.
 */

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
const LABEL = "Flatten 4 positions";
const REASON = "Your role can't use the kill switch.";
const confirmButton = (): HTMLElement => screen().getByRole("button", { name: /^Flatten 4/ });

type Gate = "standard" | "typed" | "hold" | "auto-cancel";

const GATE_PROPS: Record<Gate, Partial<ConfirmDialogProps>> = {
  standard: { variant: "standard" },
  typed: { variant: "typed", typedConfirmValue: "FLATTEN" },
  hold: { variant: "hold" },
  "auto-cancel": { variant: "standard", role: "dialog", autoCancelMs: 20_000 },
};
const EXPECTED_META: Record<Gate, { variant: string; gate: string }> = {
  standard: { variant: "standard", gate: "click" },
  typed: { variant: "typed", gate: "typed" },
  hold: { variant: "hold", gate: "pointer-hold" },
  "auto-cancel": { variant: "standard", gate: "click" },
};

interface Cell {
  readonly onConfirm: ReturnType<typeof vi.fn>;
  readonly onCancel: ReturnType<typeof vi.fn>;
}

/** Mounts the dialog open in one cell's state and waits out the 400 ms guard. */
const openCell = async (gate: Gate, extra: Partial<ConfirmDialogProps>): Promise<Cell> => {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  await mount(
    <ConfirmDialog
      open
      title="Flatten everything?"
      restatement={<p>Closes 4 positions at market.</p>}
      confirmLabel={LABEL}
      now={now}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...GATE_PROPS[gate]}
      {...extra}
    />,
  );
  await advance(400);
  return { onConfirm, onCancel };
};

/** jsdom has no PointerEvent: a MouseEvent of the pointer type carries `button` to React's handler. */
const pointer = async (target: Element, type: "pointerdown" | "pointerup"): Promise<void> => {
  await act(async () => {
    fireEvent(target, new MouseEvent(type, { bubbles: true, cancelable: true, button: 0 }));
  });
};

/** The gate's whole gesture: the token typed (and the guard it rearms waited out), then a press or a hold. */
const gesture = async (gate: Gate): Promise<void> => {
  if (gate === "typed") {
    const field = screen().getByRole("textbox", { name: "Type FLATTEN to confirm" });
    await act(async () => {
      fireEvent.change(field, { target: { value: "FLATTEN" } });
    });
    await advance(400);
  }
  const target = confirmButton();
  await pointer(target, "pointerdown");
  if (gate === "hold") await advance(800);
  await pointer(target, "pointerup");
  await act(async () => {
    fireEvent.click(target);
  });
  await advance(0);
};

const GATES: readonly Gate[] = ["standard", "typed", "hold", "auto-cancel"];

describe("ConfirmDialog gate matrix (CMP-044, E05-X02)", () => {
  describe.each(GATES)("%s", (gate) => {
    it("enabled: the full gesture confirms once, with the gate in the metadata", async () => {
      const { onConfirm, onCancel } = await openCell(gate, {});
      await gesture(gate);
      expect(onConfirm).toHaveBeenCalledTimes(1);
      expect(onConfirm.mock.calls[0]?.[0]).toMatchObject(EXPECTED_META[gate]);
      // A second gesture in the same opening never fires again.
      await gesture(gate);
      expect(onConfirm).toHaveBeenCalledTimes(1);
      expect(onCancel).not.toHaveBeenCalled();
    });

    it("gated: Confirm stays focusable with its reason, and the full gesture fires nothing", async () => {
      const { onConfirm, onCancel } = await openCell(gate, { confirmDisabledReason: REASON });
      const target = confirmButton();
      expect(target).toHaveAttribute("aria-disabled", "true");
      expect(target).not.toBeDisabled();
      expect(target).toHaveAccessibleDescription(expect.stringContaining(REASON));
      await gesture(gate);
      expect(onConfirm).not.toHaveBeenCalled();
      if (gate === "auto-cancel") {
        // The count still runs while gated, and its expiry cancels, never confirms.
        await advance(20_000);
        expect(onCancel).toHaveBeenCalledWith("timeout");
        expect(onConfirm).not.toHaveBeenCalled();
      }
    });

    it("pending (summary loading): Confirm is natively disabled and the full gesture fires nothing", async () => {
      const { onConfirm } = await openCell(gate, { summaryLoading: true });
      expect(confirmButton()).toBeDisabled();
      await gesture(gate);
      expect(onConfirm).not.toHaveBeenCalled();
    });

    it("pending (busy send): the card and Confirm are busy and the full gesture fires nothing", async () => {
      const busy = await openCell(gate, { busy: true });
      expect(screen().getByRole(gate === "auto-cancel" ? "dialog" : "alertdialog")).toHaveAttribute(
        "aria-busy",
        "true",
      );
      expect(confirmButton()).toHaveAttribute("aria-busy", "true");
      await gesture(gate);
      expect(busy.onConfirm).not.toHaveBeenCalled();
      if (gate === "auto-cancel") {
        // A busy send is never cancelled by the count.
        await advance(20_000);
        expect(busy.onCancel).not.toHaveBeenCalled();
      }
    });

    it("error: the partial failure shows with Retry, and one more confirm is allowed", async () => {
      const retry = vi.fn();
      const { onConfirm } = await openCell(gate, {
        failure: {
          message: "2 of 4 positions were not closed.",
          retry: { label: "Retry", onClick: retry },
        },
      });
      expect(
        screen().getByText("2 of 4 positions were not closed.").closest('[role="alert"]'),
      ).not.toBeNull();
      await act(async () => {
        fireEvent.click(screen().getByRole("button", { name: "Retry" }));
      });
      expect(retry).toHaveBeenCalledTimes(1);
      await gesture(gate);
      expect(onConfirm).toHaveBeenCalledTimes(1);
      expect(onConfirm.mock.calls[0]?.[0]).toMatchObject(EXPECTED_META[gate]);
    });
  });
});
