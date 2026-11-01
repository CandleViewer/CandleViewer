// @vitest-environment jsdom
// E29-S02 (#912) BQ-11: the cell use of CMP-100 / CMP-101 (E29-D02 §7, E29-D01 D12, E29-D04 handoff §C.2): a decimal
// string stepped by its tick or lot, `Enter`, `F2` or a double-click to edit, `Enter` alone to commit, `Esc`, `Tab` or
// a click elsewhere to restore, no rounding, T2 with a visible reason, and no serious axe violation in any state.
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  CELL_NUMBER_EDITOR_COPY,
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
    ["2495.003", "Enter a multiple of 0.01."],
    ["abc", "Enter a number."],
    ["0", "Enter a number above zero."],
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
      expect.stringContaining("Enter 0.002 or more."),
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
    expect(host.querySelector(".cv-field__message")).toHaveTextContent("Enter a multiple of 0.01.");
    await retype(cell(), "2495.00");
    expect(cell()).not.toHaveAttribute("aria-invalid");
    expect(host.querySelector(".cv-field__message")).toHaveTextContent("");
  });

  it("the host's copy replaces the editor's words", async () => {
    await render({ copy: { offStep: (step) => `Not on the ${step} tick.` } });
    const editor = await open();
    await retype(editor, "1.001{Enter}");
    expect(cell()).toHaveAccessibleDescription(expect.stringContaining("Not on the 0.01 tick."));
  });
});

describe("T2: disabled with a visible reason (E09-D09 §2.2, rendering 2b)", () => {
  it("keeps its role, name and Tab stop with aria-disabled, the lock and the reason node at mount", async () => {
    await render({ disabledReason: IN_FLIGHT });
    const value = cell();
    expect(value).toHaveAttribute("aria-disabled", "true");
    expect(value).not.toBeDisabled();
    expect(value).toHaveAccessibleDescription(IN_FLIGHT);
    const id = value.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(id)).toHaveTextContent(IN_FLIGHT);
    expect(page.getByRole("img", { name: "Not available" })).toBeInTheDocument();
    await userEvent.tab();
    expect(value).toHaveFocus();
  });

  it("Enter, F2 and a double-click open nothing and say the reason once more, politely, each time", async () => {
    const { onEditingChange } = await render({ disabledReason: IN_FLIGHT });
    clearPolite();
    cell().focus();
    for (const press of ["{Enter}", "{F2}"]) {
      await userEvent.keyboard(press);
      expect(await politeText()).toBe(IN_FLIGHT);
      clearPolite();
    }
    await userEvent.dblClick(cell());
    expect(await politeText()).toBe(IN_FLIGHT);
    expect(cell()).toHaveAttribute("readonly");
    expect(onEditingChange).not.toHaveBeenCalled();
  });

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
});
