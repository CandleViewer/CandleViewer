// @vitest-environment jsdom
// E29-S02 (#912) BQ-11: the cell use of CMP-100 / CMP-101 (E29-D02 §7, E29-D01 D12, E29-D04 handoff §C.2): a decimal
// string stepped by its tick or lot, `Enter`, `F2` or a double-click to edit, `Enter` alone to commit, `Esc`, `Tab` or
// a click elsewhere to restore, no rounding, T2 with a visible reason (E29-D04 §4.1: the value's own look, the reason
// re-shown 2a, a host's notice pointed at, a gated commit), a focused value never remounted by a gate, and no serious
// axe violation in any state.
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  CELL_NUMBER_EDITOR_COPY,
  CELL_TRIGGER_OFF_TICK,
  CellNumberEditor,
  type CellNumberEditorProps,
} from "../src/components/index.js";
import * as stories from "../src/components/CellNumberEditor.stories.js";
import { seriousViolations } from "./axe.js";
import { clearPolite, politeText } from "./theme/polite.js";
import { mount } from "./theme/mount.js";

const page = within(document.body);
const PRICE = "Price, ETHUSDT Buy on Sub-2";
const EDITING = "Editing the price. 2,500.00 stays live until you press Enter.";
const IN_FLIGHT = "An amend is already in flight.";

type Props = Partial<CellNumberEditorProps>;

/** One editor on the D02 §7 specimen (2500 on a 0.01 tick) and a button after it, for `Tab`'s exit. */
async function render(extra: Props = {}): Promise<{
  onCommit: ReturnType<typeof fn>;
  onEditingChange: ReturnType<typeof fn>;
  host: HTMLElement;
}> {
  const onCommit = fn();
  const onEditingChange = fn();
  const host = await mount(
    <>
      <CellNumberEditor
        label={PRICE}
        value="2500"
        step="0.01"
        unit="tick"
        editingDescription={EDITING}
        onCommit={onCommit}
        onEditingChange={onEditingChange}
        {...extra}
      />
      <button type="button">After</button>
    </>,
  );
  return { onCommit, onEditingChange, host };
}

/** The description with its empty live nodes: compared as words, so a blank node never matters. */
const described = (el: HTMLElement, words: string): void => {
  const pattern = words
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  expect(el).toHaveAccessibleDescription(new RegExp(`^\\s*${pattern.join("\\s+")}\\s*$`));
};
const cell = (name = PRICE): HTMLInputElement =>
  page.getByRole("spinbutton", { name }) as HTMLInputElement;
const key = async (el: HTMLElement, init: KeyboardEventInit): Promise<boolean> => {
  let ok = true;
  await act(async () => {
    ok = await fireEvent.keyDown(el, init);
  });
  return ok;
};
const open = async (): Promise<HTMLInputElement> => {
  cell().focus();
  await userEvent.keyboard("{Enter}");
  return cell();
};
const retype = async (editor: HTMLInputElement, text: string): Promise<void> => {
  await userEvent.clear(editor);
  await userEvent.type(editor, text);
};

describe("CellNumberEditor at rest", () => {
  it("marks one root CMP-100 for a tick and CMP-101 for a lot, as their cell use", async () => {
    await render();
    await render({ label: "Qty", value: "0.15", step: "0.001", unit: "lot" });
    expect(document.querySelectorAll('[data-cmp="CMP-100"][data-use="cell"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-cmp="CMP-101"][data-use="cell"]')).toHaveLength(1);
  });

  it("is a read-only spin button named by the host, showing the live value at the step's places", async () => {
    await render();
    const value = cell();
    expect(value).toHaveValue("2,500.00");
    expect(value).toHaveAttribute("readonly");
    expect(value).toHaveAttribute("aria-valuetext", "2,500.00");
    expect(value).not.toHaveAttribute("aria-valuenow"); // a decimal string never becomes a number here
    await userEvent.tab();
    expect(value).toHaveFocus();
  });

  it("never rounds a live value finer than the step, and shows an unreadable one as sent, not editable", async () => {
    const { onEditingChange } = await render({ value: "2500.005" });
    expect(cell()).toHaveValue("2,500.005");
    document.body.replaceChildren();
    await render({ value: "n/a" });
    expect(cell()).toHaveValue("n/a");
    cell().focus();
    await userEvent.keyboard("{Enter}{F2}");
    expect(cell()).toHaveAttribute("readonly");
    expect(onEditingChange).not.toHaveBeenCalled();
  });

  it("refuses a step that is not a decimal above zero (a host's programming error)", async () => {
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      for (const step of ["0", "-0.1", "abc"]) {
        await expect(
          mount(
            <CellNumberEditor label={PRICE} value="1" step={step} unit="tick" onCommit={fn()} />,
          ),
        ).rejects.toThrow(RangeError);
      }
    } finally {
      quiet.mockRestore();
    }
  });
});

describe("opening the editor (E29-D02 §7)", () => {
  it.each([["{Enter}"], ["{F2}"]])(
    "%s opens a fresh field holding the live value, selected",
    async (press) => {
      const { onEditingChange } = await render();
      cell().focus();
      await userEvent.keyboard(press);
      const editor = cell();
      expect(editor).toHaveFocus();
      expect(editor).not.toHaveAttribute("readonly");
      expect(editor).toHaveValue("2500.00");
      expect(editor.selectionStart).toBe(0);
      expect(editor.selectionEnd).toBe("2500.00".length);
      expect(onEditingChange).toHaveBeenLastCalledWith(true);
    },
  );

  it("a double-click opens it; Space and a chord do not (Space is the grid's row selection)", async () => {
    const { onEditingChange } = await render();
    const value = cell();
    expect(await key(value, { key: " " })).toBe(true);
    expect(await key(value, { key: "Enter", ctrlKey: true })).toBe(true);
    expect(await key(value, { key: "F2", shiftKey: true })).toBe(true);
    expect(onEditingChange).not.toHaveBeenCalled();
    await userEvent.dblClick(value);
    expect(cell()).not.toHaveAttribute("readonly");
  });

  it("describes the edit with the host's sentence and the step hint, and shows the live value under it", async () => {
    const { host } = await render();
    const editor = await open();
    described(editor, `${EDITING} ${CELL_NUMBER_EDITOR_COPY.stepHint("0.01", "tick")}`);
    expect(host.querySelector(".cv-cell-editor__hint")).toHaveTextContent(
      "Step 0.01 · ↑/↓ one tick · Shift ten",
    );
    expect(CELL_NUMBER_EDITOR_COPY.stepHint("0.1", "tick")).toBe(
      "Step 0.1 · ↑/↓ one tick · Shift ten",
    );
    expect(CELL_NUMBER_EDITOR_COPY.stepHint("0.001", "lot")).toBe(
      "Step 0.001 · ↑/↓ one lot · Shift ten",
    );
    const live = host.querySelector(".cv-cell-editor__live");
    expect(live).toHaveTextContent("2,500.00");
    expect(live).toHaveAttribute("aria-hidden", "true");
  });

  it("a host opens it controlled, from the live value, and is asked to close it", async () => {
    const onCommit = fn();
    const log: boolean[] = [];
    function Host(): JSX.Element {
      const [editing, setEditing] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setEditing(true)}>
            Edit price
          </button>
          <CellNumberEditor
            label={PRICE}
            value="2500"
            step="0.01"
            unit="tick"
            editing={editing}
            onEditingChange={(next) => {
              log.push(next);
              setEditing(next);
            }}
            onCommit={onCommit}
          />
        </>
      );
    }
    await mount(<Host />);
    await userEvent.click(page.getByRole("button", { name: "Edit price" }));
    const editor = cell();
    expect(editor).toHaveFocus();
    expect(editor).toHaveValue("2500.00");
    await retype(editor, "2495.00");
    await userEvent.keyboard("{Enter}");
    expect(onCommit).toHaveBeenCalledWith("2495.00");
    expect(log).toEqual([false]);
    expect(cell()).toHaveAttribute("readonly");
    expect(cell()).toHaveFocus();
  });
});

describe("stepping by the tick or the lot: exact, never a float", () => {
  it("↑ and ↓ move one tick, Shift ten, and the keys stay in the editor", async () => {
    await render();
    const editor = await open();
    expect(await key(editor, { key: "ArrowDown" })).toBe(false);
    expect(cell()).toHaveValue("2499.99");
    await key(cell(), { key: "ArrowUp", shiftKey: true });
    expect(cell()).toHaveValue("2500.09");
    expect(await key(cell(), { key: "ArrowUp", altKey: true })).toBe(true); // a chord is the host's
    expect(cell()).toHaveValue("2500.09");
  });

  it("a step from an off-step value lands on the adjacent multiple; from junk it starts at the live value", async () => {
    await render({ step: "0.1", value: "63950" });
    const editor = await open();
    await retype(editor, "63950.03");
    await key(cell(), { key: "ArrowUp" });
    expect(cell()).toHaveValue("63950.1");
    await retype(cell(), "abc");
    await key(cell(), { key: "ArrowDown" });
    expect(cell()).toHaveValue("63949.9");
  });

  it("a lot steps 0.1 + 0.2 exactly, and a step down stops at the lowest valid value", async () => {
    await render({ label: "Qty", value: "0.1", step: "0.1", unit: "lot", min: "0.1" });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    await key(cell("Qty"), { key: "ArrowUp" });
    await key(cell("Qty"), { key: "ArrowUp" });
    expect(cell("Qty")).toHaveValue("0.3"); // never 0.30000000000000004
    await key(cell("Qty"), { key: "ArrowDown", shiftKey: true });
    expect(cell("Qty")).toHaveValue("0.1");
  });
});

describe("committing and restoring", () => {
  it("Enter commits a changed, valid value as its decimal string and returns focus to the cell", async () => {
    const { onCommit, onEditingChange } = await render();
    const editor = await open();
    await retype(editor, "2495.00");
    await userEvent.keyboard("{Enter}");
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("2495.00");
    expect(typeof onCommit.mock.calls[0]?.[0]).toBe("string");
    expect(cell()).toHaveAttribute("readonly");
    expect(cell()).toHaveFocus();
    expect(cell()).toHaveValue("2,500.00"); // the live value stays until the host's frame confirms (D02 §7)
    expect(onEditingChange.mock.calls.map(([v]) => v)).toEqual([true, false]);
  });

  it("Enter on the unchanged value closes without a commit", async () => {
    const { onCommit } = await render();
    await open();
    await userEvent.keyboard("{Enter}");
    expect(onCommit).not.toHaveBeenCalled();
    expect(cell()).toHaveAttribute("readonly");
  });

  it("Esc restores the live value, sends nothing and keeps the key from the grid", async () => {
    const onGridKey = fn();
    const onCommit = fn();
    await mount(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a stand-in for the grid's key handler
      <div onKeyDown={(event) => onGridKey(event.key)}>
        <CellNumberEditor label={PRICE} value="2500" step="0.01" unit="tick" onCommit={onCommit} />
      </div>,
    );
    const editor = await open();
    await retype(editor, "2495.00");
    onGridKey.mockClear();
    expect(await key(cell(), { key: "Escape" })).toBe(false);
    expect(onGridKey).not.toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
    expect(cell()).toHaveValue("2,500.00");
    expect(cell()).toHaveFocus();
  });

  it("Tab away or a click elsewhere restores without a commit and leaves focus where it went", async () => {
    const { onCommit } = await render();
    const editor = await open();
    await retype(editor, "2495.00");
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
    expect(cell()).toHaveValue("2,500.00");
    await open();
    await userEvent.click(page.getByRole("button", { name: "After" }));
    expect(cell()).toHaveAttribute("readonly");
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("refusals: never rounded, never sent", () => {
  it.each([
    ["2495.003", "Price must be a multiple of 0.01."],
    ["abc", "Enter a number."],
    ["0", "Enter a number above zero."],
    ["-5", "Enter a number above zero."],
    ["2,5", "Enter a number."],
    ["0,150", "Enter a number."], // a decimal comma: on this tick it would read as 150.00, on step
    ["   ", "Enter a number."],
  ])("%s is refused with “%s”, the text kept as typed", async (typed, message) => {
    const { onCommit } = await render();
    const editor = await open();
    await userEvent.clear(editor);
    if (typed.trim() !== "") await userEvent.type(editor, typed);
    else fireEvent.change(editor, { target: { value: typed } });
    await key(cell(), { key: "Enter" });
    expect(cell()).toHaveAttribute("aria-invalid", "true");
    expect(cell()).toHaveValue(typed);
    expect(cell()).toHaveAccessibleDescription(expect.stringContaining(message));
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("well-formed grouping, as the grid shows a value, is dropped: 2,495.00 commits 2495.00", async () => {
    const { onCommit } = await render();
    const editor = await open();
    await retype(editor, "2,495.00{Enter}");
    expect(onCommit).toHaveBeenCalledWith("2495.00");
  });

  it("a leading-zero first group is a decimal comma, never thousands: 0,150 on a lot sends nothing", async () => {
    const { onCommit } = await render({ label: "Qty", value: "0.15", step: "0.001", unit: "lot" });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    for (const typed of ["0,150", "01,234"]) {
      await retype(cell("Qty"), `${typed}{Enter}`);
      expect(cell("Qty")).toHaveAttribute("aria-invalid", "true"); // read as 150 it would be on step and sent
      expect(cell("Qty")).toHaveValue(typed);
      expect(cell("Qty")).toHaveAccessibleDescription(expect.stringContaining("Enter a number."));
    }
    expect(onCommit).not.toHaveBeenCalled();
    expect(cell("Qty")).not.toHaveAttribute("readonly"); // still open, nothing committed
  });

  it("a lot's refusals are E30's words: off the lot, zero and below the lowest (E30-D06 v.qty.lot)", async () => {
    const { onCommit } = await render({ label: "Qty", value: "0.15", step: "0.001", unit: "lot" });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    for (const typed of ["0.0015", "0", "-1"]) {
      await retype(cell("Qty"), `${typed}{Enter}`);
      expect(cell("Qty")).toHaveAccessibleDescription(
        expect.stringContaining("Minimum 0.001, step 0.001."),
      );
    }
    expect(CELL_NUMBER_EDITOR_COPY.offLot("0.001", "0.001")).toBe("Minimum 0.001, step 0.001.");
    expect(CELL_NUMBER_EDITOR_COPY.offTick("0.1")).toBe("Price must be a multiple of 0.1.");
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("below the lowest valid value, and the host's own verdict, each refuse with their words", async () => {
    const validate = fn((value: string) =>
      value === "0.002" ? "Leaves 0.003 BTC without a stop." : undefined,
    );
    const { onCommit } = await render({
      label: "Qty",
      value: "0.005",
      step: "0.001",
      unit: "lot",
      min: "0.002",
      validate,
    });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    await retype(cell("Qty"), "0.001{Enter}");
    expect(cell("Qty")).toHaveAccessibleDescription(
      expect.stringContaining("Minimum 0.002, step 0.001."),
    );
    await retype(cell("Qty"), "0.002{Enter}");
    expect(validate).toHaveBeenCalledWith("0.002");
    expect(cell("Qty")).toHaveAccessibleDescription(
      expect.stringContaining("Leaves 0.003 BTC without a stop."),
    );
    expect(onCommit).not.toHaveBeenCalled();
    await retype(cell("Qty"), "0.004{Enter}");
    expect(onCommit).toHaveBeenCalledWith("0.004");
  });

  it("a message stays while the text is refused, then clears silently once it is valid", async () => {
    const { host } = await render();
    const editor = await open();
    await retype(editor, "2495.003{Enter}");
    await userEvent.type(cell(), "9");
    expect(host.querySelector(".cv-field__message")).toHaveTextContent(
      "Price must be a multiple of 0.01.",
    );
    await retype(cell(), "2495.00");
    expect(cell()).not.toHaveAttribute("aria-invalid");
    expect(host.querySelector(".cv-field__message")).toHaveTextContent("");
  });

  it("the host's copy replaces the editor's words: a Trigger cell's PROPOSED off-tick sentence", async () => {
    await render({ label: "Trigger", copy: { offTick: CELL_TRIGGER_OFF_TICK } });
    cell("Trigger").focus();
    await userEvent.keyboard("{Enter}");
    await retype(cell("Trigger"), "1.001{Enter}");
    expect(cell("Trigger")).toHaveAccessibleDescription(
      expect.stringContaining("Trigger must be a multiple of 0.01."),
    );
  });
});

describe("T2: disabled with a visible reason (E09-D09 §2.2; E29-D04 §4.1, D02:429)", () => {
  it("keeps its value's look, role, name and Tab stop with aria-disabled: no glyph, no echo, the reason at mount", async () => {
    const { host } = await render({ disabledReason: IN_FLIGHT });
    const value = cell();
    expect(value).toHaveValue("2,500.00");
    expect(value).toHaveAttribute("aria-disabled", "true");
    expect(value).not.toBeDisabled();
    expect(value).toHaveAccessibleDescription(IN_FLIGHT);
    const id = value.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(id)).toHaveTextContent(IN_FLIGHT);
    expect(document.getElementById(id)?.closest(".cv-visually-hidden")).not.toBeNull();
    expect(page.queryByRole("img", { name: "Not available" })).toBeNull(); // nothing among the numerals
    expect(page.queryByRole("tooltip")).toBeNull();
    expect(host.querySelector(".cv-cell-editor__well")?.children).toHaveLength(1);
    await userEvent.tab();
    expect(value).toHaveFocus();
    expect(page.queryByRole("tooltip")).toBeNull(); // no echo on focus either
  });

  it("Enter, F2 and a double-click open nothing, re-show the reason 2a under the cell and say it each time", async () => {
    const { onEditingChange, host } = await render({ disabledReason: IN_FLIGHT });
    clearPolite();
    const value = cell();
    const reasonNode = document.getElementById(value.getAttribute("aria-describedby") ?? "");
    value.focus();
    for (const press of ["{Enter}", "{F2}"]) {
      await userEvent.keyboard(press);
      expect(await politeText()).toBe(IN_FLIGHT);
      clearPolite();
    }
    await userEvent.dblClick(value);
    expect(await politeText()).toBe(IN_FLIGHT);
    const note = host.querySelector(".cv-cell-editor__note");
    expect(note).toHaveTextContent(IN_FLIGHT);
    expect(within(note as HTMLElement).getByRole("img", { name: "Not available" })).toBeTruthy();
    expect(note?.firstElementChild?.firstElementChild).toHaveClass("cv-cell-editor__lock"); // the lock leads
    expect(document.getElementById(value.getAttribute("aria-describedby") ?? "")).toBe(reasonNode);
    expect(value).toHaveAccessibleDescription(IN_FLIGHT); // the reason alone, never the lock's name
    expect(cell()).toBe(value);
    expect(cell()).toHaveAttribute("readonly");
    expect(onEditingChange).not.toHaveBeenCalled();
    await userEvent.tab(); // focus leaves the cell: the re-shown reason goes, the node stays
    expect(host.querySelector(".cv-cell-editor__note")).toBeNull();
    expect(reasonNode?.isConnected).toBe(true);
  });

  it("points at the host's notice (disabledReasonId): no reason node of its own, one notice for many cells", async () => {
    const notice = document.body.appendChild(document.createElement("p"));
    notice.id = "orders-notice";
    notice.textContent = "Read-only while viewing as alex.";
    const { host } = await render({
      disabledReason: "Read-only while viewing as alex.",
      disabledReasonId: "orders-notice",
    });
    await render({
      label: "Qty",
      value: "0.15",
      step: "0.001",
      unit: "lot",
      disabledReason: "Read-only while viewing as alex.",
      disabledReasonId: "orders-notice",
    });
    for (const value of [cell(), cell("Qty")]) {
      expect(value).toHaveAttribute("aria-describedby", "orders-notice");
      expect(value).toHaveAccessibleDescription("Read-only while viewing as alex.");
    }
    expect(page.getAllByText("Read-only while viewing as alex.")).toHaveLength(1);
    clearPolite();
    cell().focus();
    await userEvent.keyboard("{Enter}");
    expect(await politeText()).toBe("Read-only while viewing as alex.");
    const note = host.querySelector(".cv-cell-editor__note");
    expect(note).toHaveTextContent("Read-only while viewing as alex.");
    expect(note).toHaveAttribute("aria-hidden", "true"); // a re-show: the notice stays the description
  });

  it("a gate that lifts takes the re-shown reason with it; one that returns shows nothing until a press", async () => {
    let gate: (reason: string | undefined) => void = () => undefined;
    function Host(): JSX.Element {
      const [reason, setReason] = useState<string | undefined>(IN_FLIGHT);
      gate = setReason;
      return (
        <CellNumberEditor
          label={PRICE}
          value="2500"
          step="0.01"
          unit="tick"
          onCommit={fn()}
          {...(reason === undefined ? {} : { disabledReason: reason })}
        />
      );
    }
    const host = await mount(<Host />);
    const note = (): Element | null => host.querySelector(".cv-cell-editor__note");
    cell().focus();
    await userEvent.keyboard("{Enter}");
    expect(note()).toHaveTextContent(IN_FLIGHT); // re-shown by the press
    await act(async () => gate(undefined)); // the gate lifts, focus stays on the value
    expect(note()).toBeNull();
    expect(cell()).toHaveFocus();
    await act(async () => gate(IN_FLIGHT)); // and comes back
    expect(note()).toBeNull(); // nothing shows until the next press
    await userEvent.keyboard("{Enter}");
    expect(note()).toHaveTextContent(IN_FLIGHT);
  });

  it.each([
    ["arrives", undefined, IN_FLIGHT],
    ["lifts", IN_FLIGHT, undefined],
  ])(
    "a gate that %s on the focused cell at rest keeps the same element focused",
    async (_, from, to) => {
      let gate: (reason: string | undefined) => void = () => undefined;
      function Host(): JSX.Element {
        const [reason, setReason] = useState<string | undefined>(from);
        gate = setReason;
        return (
          <CellNumberEditor
            label={PRICE}
            value="2500"
            step="0.01"
            unit="tick"
            onCommit={fn()}
            {...(reason === undefined ? {} : { disabledReason: reason })}
          />
        );
      }
      await mount(<Host />);
      const value = cell();
      value.focus();
      await act(async () => gate(to));
      expect(cell()).toBe(value); // never remounted
      expect(document.activeElement).toBe(value);
      expect(value.hasAttribute("aria-disabled")).toBe(to !== undefined);
      await act(async () => gate(from));
      expect(cell()).toBe(value);
      expect(document.activeElement).toBe(value);
    },
  );

  it("an edit under way when the gate arrives is discarded, never committed, and the host is told", async () => {
    const onCommit = fn();
    const onEditingChange = fn();
    let gate: (reason: string) => void = () => undefined;
    function Host(): JSX.Element {
      const [reason, setReason] = useState<string | null>(null);
      gate = setReason;
      return (
        <CellNumberEditor
          label={PRICE}
          value="2500"
          step="0.01"
          unit="tick"
          onCommit={onCommit}
          onEditingChange={onEditingChange}
          {...(reason === null ? {} : { disabledReason: reason })}
        />
      );
    }
    await mount(<Host />);
    const editor = await open();
    await retype(editor, "2495.00");
    expect(onEditingChange).toHaveBeenLastCalledWith(true);
    await act(async () => gate(IN_FLIGHT));
    expect(cell()).toHaveAttribute("readonly");
    expect(cell()).toHaveValue("2,500.00");
    expect(cell()).toHaveAttribute("aria-disabled", "true");
    expect(cell()).toHaveFocus(); // the cell's value, never the body
    expect(onEditingChange).toHaveBeenLastCalledWith(false);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("plain disabled, with no reason, is native and out of the Tab order", async () => {
    await render({ disabled: true });
    expect(cell()).toBeDisabled();
    await userEvent.tab();
    expect(page.getByRole("button", { name: "After" })).toHaveFocus();
  });
});

/** Board 16's gate: a quantity up is new exposure under the kill switch; a cut passes it (C-2.6). */
const FROZEN =
  "Trading frozen by the owner at 14:02 UTC — new orders off. Cancel and close still work.";
const lots = (qty: string): bigint => {
  const [whole = "0", fraction = ""] = qty.split(".");
  return BigInt(`${whole}${fraction.padEnd(3, "0")}`);
};
const qtyUp = (qty: string): string | undefined => (lots(qty) > lots("0.1") ? FROZEN : undefined);

describe("T2 on the commit (commitGate; E29-D02 §7, board 16)", () => {
  async function openQty(): Promise<{ onCommit: ReturnType<typeof fn>; host: HTMLElement }> {
    const gate = fn(qtyUp);
    const out = await render({
      label: "Qty",
      value: "0.1",
      step: "0.001",
      unit: "lot",
      commitGate: gate,
    });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    return out;
  }

  it("Enter on a gated value sends nothing: the reason 2a under the editor, said once, never aria-invalid", async () => {
    const { onCommit, host } = await openQty();
    clearPolite();
    await retype(cell("Qty"), "0.150{Enter}");
    expect(onCommit).not.toHaveBeenCalled();
    const editor = cell("Qty");
    expect(editor).not.toHaveAttribute("readonly"); // still open
    expect(editor).toHaveFocus();
    expect(editor).not.toHaveAttribute("aria-invalid");
    expect(editor).toHaveAccessibleDescription(expect.stringContaining(FROZEN));
    expect(editor.getAttribute("aria-describedby")).toMatch(/\S+ \S+ \S+/);
    expect(await politeText()).toBe(FROZEN);
    const reason = host.querySelector(".cv-cell-editor__note .cv-cell-editor__reason");
    expect(reason).toHaveAttribute("data-shown");
    expect(reason?.firstElementChild).toHaveClass("cv-cell-editor__lock");
    expect(host.querySelector(".cv-field__message")).toHaveTextContent("");
    expect(host.querySelector("[data-invalid]")).toBeNull();
    clearPolite();
    await key(editor, { key: "Enter" }); // a second press says it once more
    expect(await politeText()).toBe(FROZEN);
  });

  it("Esc restores the live value and sends nothing; a quantity cut passes the gate and commits", async () => {
    const { onCommit } = await openQty();
    await retype(cell("Qty"), "0.150{Enter}");
    expect(await key(cell("Qty"), { key: "Escape" })).toBe(false);
    expect(cell("Qty")).toHaveAttribute("readonly");
    expect(cell("Qty")).toHaveValue("0.100");
    expect(cell("Qty")).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    await retype(cell("Qty"), "0.050{Enter}");
    expect(onCommit).toHaveBeenCalledWith("0.050");
  });

  it("a change of text takes the gate's reason away until the next press", async () => {
    const { host } = await openQty();
    await retype(cell("Qty"), "0.150{Enter}");
    await userEvent.type(cell("Qty"), "0");
    expect(host.querySelector(".cv-cell-editor__reason")).not.toHaveAttribute("data-shown");
    expect(cell("Qty")).toHaveAccessibleDescription(expect.not.stringContaining(FROZEN));
    await key(cell("Qty"), { key: "ArrowUp" });
    await key(cell("Qty"), { key: "Enter" });
    expect(host.querySelector(".cv-cell-editor__reason")).toHaveAttribute("data-shown");
    await key(cell("Qty"), { key: "ArrowDown" });
    expect(host.querySelector(".cv-cell-editor__reason")).not.toHaveAttribute("data-shown");
  });

  it("the gate is asked only about a value that would be sent: never junk, never the live value", async () => {
    const gate = fn(qtyUp);
    const { onCommit } = await render({
      label: "Qty",
      value: "0.1",
      step: "0.001",
      unit: "lot",
      commitGate: gate,
    });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    await retype(cell("Qty"), "abc{Enter}");
    await retype(cell("Qty"), "0.100{Enter}");
    expect(gate).not.toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("the open editor's keys and note (E29-D01 D12; D01 D13 b)", () => {
  it("keeps ←, →, Home and End for its caret: they move it and never reach the grid", async () => {
    const onGridKey = fn();
    await mount(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a stand-in for the grid's key handler
      <div onKeyDown={(event) => onGridKey(event.key)}>
        <CellNumberEditor label={PRICE} value="2500" step="0.01" unit="tick" onCommit={fn()} />
      </div>,
    );
    await open();
    for (const caret of ["ArrowLeft", "ArrowRight", "Home", "End"]) {
      expect(await key(cell(), { key: caret })).toBe(true); // not prevented: the caret moves
      expect(await key(cell(), { key: caret, shiftKey: true })).toBe(true);
    }
    expect(onGridKey).not.toHaveBeenCalled();
    await key(cell(), { key: "PageDown" }); // a key the editor does not use is the host's to suspend
    await key(cell(), { key: "ArrowLeft", ctrlKey: true });
    expect(onGridKey.mock.calls.map(([k]) => k)).toEqual(["PageDown", "ArrowLeft"]);
    expect(cell()).not.toHaveAttribute("readonly");
  });

  it("hangs the live value, the step hint and a refusal in one note under the well, out of the cell's flow", async () => {
    const { host } = await render();
    await open();
    const note = host.querySelector(".cv-cell-editor__note");
    expect(note?.previousElementSibling).toHaveClass("cv-cell-editor__well");
    for (const part of [".cv-cell-editor__live", ".cv-cell-editor__hint", ".cv-field__message"])
      expect(note?.querySelector(part)).not.toBeNull();
    expect(host.querySelector(".cv-cell-editor__well")?.children).toHaveLength(1);
  });
});

describe("the grid's keys at rest, and the caret's while open (E29-D02 §11.1; `05` §3.1 item 1)", () => {
  /** A stand-in for the grid's key handler around the editor: what it receives is what the grid would move on. */
  async function inGrid(): Promise<ReturnType<typeof fn>> {
    const onGridKey = fn();
    await mount(
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a stand-in for the grid's key handler
      <div onKeyDown={(event) => onGridKey(event.key)}>
        <CellNumberEditor label={PRICE} value="2500" step="0.01" unit="tick" onCommit={fn()} />
      </div>,
    );
    return onGridKey;
  }

  it.each(["ArrowLeft", "ArrowRight", "Home", "End", "ArrowUp", "ArrowDown"])(
    "at rest, %s reaches the grid, with and without Shift, and the editor never prevents it",
    async (name) => {
      const onGridKey = await inGrid();
      const value = cell();
      value.focus();
      expect(await key(value, { key: name })).toBe(true); // not default-prevented: the grid's handler owns it
      expect(await key(value, { key: name, shiftKey: true })).toBe(true); // an extending move too
      expect(onGridKey.mock.calls.map(([k]) => k)).toEqual([name, name]);
      expect(value).toHaveAttribute("readonly"); // nothing opened
    },
  );

  it("while open, ←, →, Home and End stay in the field: never to the grid, never prevented, so the caret moves", async () => {
    const onGridKey = await inGrid();
    await open();
    onGridKey.mockClear();
    for (const caret of ["ArrowLeft", "ArrowRight", "Home", "End"]) {
      expect(await key(cell(), { key: caret })).toBe(true);
      expect(await key(cell(), { key: caret, shiftKey: true })).toBe(true);
    }
    expect(onGridKey).not.toHaveBeenCalled();
    expect(cell()).not.toHaveAttribute("readonly"); // still open
  });
});

describe("the note is brought into view when it shows (the grid's scroll region clips it; `05` §5 item 7)", () => {
  // jsdom has no `scrollIntoView`: a spy stands in for it in this block only, and every other test runs without one.
  const scroll = vi.fn();
  beforeEach(() => {
    scroll.mockClear();
    Element.prototype.scrollIntoView = scroll;
  });
  afterEach(() => {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  });
  const noteOf = (host: HTMLElement): Element | null => host.querySelector(".cv-cell-editor__note");

  it("opening the editor scrolls its note into view once: nearest on both axes, never smooth", async () => {
    const { host } = await render();
    expect(scroll).not.toHaveBeenCalled(); // at rest there is no note
    await open();
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" }); // no `behavior`: instant
    expect(scroll.mock.contexts[0]).toBe(noteOf(host));
  });

  it("a refusal, and a gated commit's reason, that join the open note bring it into view again", async () => {
    const { host } = await render({
      label: "Qty",
      value: "0.1",
      step: "0.001",
      unit: "lot",
      commitGate: qtyUp,
    });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    await retype(cell("Qty"), "0.0015");
    expect(scroll).toHaveBeenCalledTimes(1); // typing alone adds nothing to the note
    scroll.mockClear();
    await key(cell("Qty"), { key: "Enter" }); // off the lot: the refusal joins the note
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    await retype(cell("Qty"), "0.150"); // valid now: the refusal clears silently
    scroll.mockClear();
    await key(cell("Qty"), { key: "Enter" }); // a quantity up under the freeze: the reason joins it
    expect(cell("Qty")).toHaveAccessibleDescription(expect.stringContaining(FROZEN));
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0]).toBe(noteOf(host));
  });

  it("a refused press at rest scrolls the re-shown reason into view; the gate alone scrolls nothing", async () => {
    const { host } = await render({ disabledReason: IN_FLIGHT });
    expect(scroll).not.toHaveBeenCalled();
    cell().focus();
    await userEvent.keyboard("{Enter}");
    expect(noteOf(host)).toHaveTextContent(IN_FLIGHT);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    expect(scroll.mock.contexts[0]).toBe(noteOf(host));
  });

  it("does the same for the re-shown copy of the host's notice (disabledReasonId)", async () => {
    const notice = document.body.appendChild(document.createElement("p"));
    notice.id = "orders-notice";
    notice.textContent = "Read-only while viewing as alex.";
    const { host } = await render({
      disabledReason: "Read-only while viewing as alex.",
      disabledReasonId: "orders-notice",
    });
    expect(scroll).not.toHaveBeenCalled();
    cell().focus();
    await userEvent.keyboard("{Enter}");
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll).toHaveBeenCalledWith({ block: "nearest", inline: "nearest" });
    expect(scroll.mock.contexts[0]).toBe(noteOf(host));
  });

  it("is guarded where the method is missing, as in jsdom: the editor opens and refuses all the same", async () => {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    expect(typeof Element.prototype.scrollIntoView).toBe("undefined");
    await render({ disabledReason: IN_FLIGHT });
    cell().focus();
    await userEvent.keyboard("{Enter}"); // a refused press re-shows the reason: nothing throws
    expect(document.querySelectorAll(".cv-cell-editor__note")).toHaveLength(1);
    document.body.replaceChildren();
    await render();
    const editor = await open();
    await retype(editor, "2495.003{Enter}");
    expect(cell()).toHaveAttribute("aria-invalid", "true");
  });
});

describe("accessibility", () => {
  it("has no serious or critical axe violation at rest, open, refused, gated and disabled", async () => {
    await render();
    await render({
      label: "Qty, BTCUSDT Buy on Sub-1",
      value: "0.15",
      step: "0.001",
      unit: "lot",
      disabledReason: IN_FLIGHT,
    });
    await render({
      label: "Price, SOLUSDT Buy on Main",
      value: "147.5",
      step: "0.01",
      unit: "tick",
      disabled: true,
    });
    expect(await seriousViolations(document.body)).toEqual([]);
    const editor = await open();
    expect(await seriousViolations(document.body)).toEqual([]);
    await retype(editor, "1.001{Enter}");
    expect(cell()).toHaveAttribute("aria-invalid", "true");
    expect(await seriousViolations(document.body)).toEqual([]);
  });

  it("has none with its own reason re-shown 2a under the cell", async () => {
    await render({ disabledReason: IN_FLIGHT });
    cell().focus();
    await userEvent.keyboard("{Enter}");
    expect(document.querySelectorAll(".cv-cell-editor__note")).toHaveLength(1);
    expect(await seriousViolations(document.body)).toEqual([]);
  });

  it("has none pointing at the host's notice, its reason re-shown", async () => {
    const notice = document.body.appendChild(document.createElement("p"));
    notice.id = "orders-notice";
    notice.textContent = "Read-only while viewing as alex.";
    await render({
      disabledReason: "Read-only while viewing as alex.",
      disabledReasonId: "orders-notice",
    });
    cell().focus();
    await userEvent.keyboard("{Enter}");
    expect(document.querySelectorAll(".cv-cell-editor__note")).toHaveLength(1);
    expect(await seriousViolations(document.body)).toEqual([]);
  });

  it("has none with a commit gated under the editor", async () => {
    await render({ label: "Qty", value: "0.1", step: "0.001", unit: "lot", commitGate: qtyUp });
    cell("Qty").focus();
    await userEvent.keyboard("{F2}");
    await retype(cell("Qty"), "0.150{Enter}");
    expect(cell("Qty")).toHaveAccessibleDescription(expect.stringContaining(FROZEN));
    expect(await seriousViolations(document.body)).toEqual([]);
  });
});

describe("CellNumberEditor stories", () => {
  const composed = composeStories(stories);

  it.each(Object.entries(composed))(
    "%s renders the cell use of CMP-100 or CMP-101",
    async (_name, Story) => {
      const host = await mount(<Story />);
      expect(host.querySelectorAll('[data-use="cell"]').length).toBeGreaterThan(0);
    },
  );

  // One story's play in jsdom, as the other suites run theirs (the storybook project runs every play in Chromium, with
  // axe, and the visual run keeps its last frame): the one whose `Enter` press keeps the refused activation's re-shown
  // reason a frame (R4), so the light gate runs that press too, not only CI.
  it("runs PointsAtNotice's play: the refused press re-shows the notice's sentence", async () => {
    const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    const canvasElement = document.body.appendChild(document.createElement("div"));
    env.IS_REACT_ACT_ENVIRONMENT = false; // the play's presses are not act-wrapped, as in the storybook project
    try {
      await expect(
        composed.PointsAtNotice.run({ canvasElement }),
        "PointsAtNotice",
      ).resolves.toBeUndefined();
    } finally {
      env.IS_REACT_ACT_ENVIRONMENT = true;
      canvasElement.remove();
    }
  });
});
