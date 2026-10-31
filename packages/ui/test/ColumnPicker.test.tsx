// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  ColumnPicker,
  GatedAnnounceProvider,
  type ColumnPickerColumn,
  type ColumnPickerListProps,
} from "../src/index.js";
import { seriousViolations } from "./axe.js";
import * as stories from "../src/components/ColumnPicker.stories.js";
import { mount } from "./theme/mount.js";

const SYMBOL_FIXED = "The symbol column is always shown.";
const READ_ONLY = "Read-only — your role can't change watchlists.";

const COLUMNS: readonly ColumnPickerColumn[] = [
  { id: "symbol", label: "Symbol", visible: true, lockedReason: SYMBOL_FIXED },
  { id: "last", label: "Last", visible: true },
  { id: "chg_24h_pct", label: "24h %", visible: true },
  { id: "turnover_24h", label: "Turnover USDT", visible: true },
  { id: "funding_rate", label: "Funding %", visible: true },
  { id: "mark_price", label: "Mark", visible: false },
];

type HostProps = Partial<Omit<ColumnPickerListProps, "variant">>;

/** A host that owns the columns, as SCR-101's Columns tab does. */
function Host(props: HostProps): JSX.Element {
  const [columns, setColumns] = useState(COLUMNS);
  return (
    <ColumnPicker
      label="Columns"
      columns={columns}
      onChange={(id, visible) =>
        setColumns((all) => all.map((c) => (c.id === id ? { ...c, visible } : c)))
      }
      onReorder={(id, to) =>
        setColumns((all) => {
          const moving = all.find((c) => c.id === id);
          if (moving === undefined) return all;
          const rest = all.filter((c) => c.id !== id);
          return [...rest.slice(0, to), moving, ...rest.slice(to)];
        })
      }
      {...props}
    />
  );
}

const page = within(document.body);
const box = (name: string): HTMLElement => page.getByRole("checkbox", { name });
/** The columns' labels in their order (the label's text: the locked box's name adds its lock's "Not available"). */
const order = (): string[] =>
  page.getAllByRole("checkbox").map((b) => b.getAttribute("aria-label") ?? labelOf(b));
const labelOf = (b: HTMLElement): string =>
  (b.id === "" ? "" : document.querySelector(`label[for="${b.id}"]`)?.textContent) ?? "";
const status = (): HTMLElement =>
  document.querySelector<HTMLElement>('[data-cmp="CMP-056"] [role="status"]') as HTMLElement;

describe("ColumnPicker (CMP-056), the list (SCR-101's Columns tab)", () => {
  it("a named group with one checkbox per column, checked when shown", async () => {
    await mount(<Host />);
    expect(page.getByRole("group", { name: "Columns" })).toBeInTheDocument();
    expect(order()).toEqual(["Symbol", "Last", "24h %", "Turnover USDT", "Funding %", "Mark"]);
    expect(box("Last")).toBeChecked();
    expect(box("Mark")).not.toBeChecked();
  });

  it("a checkbox shows or hides its column", async () => {
    const onChange = vi.fn();
    await mount(<Host onChange={onChange} />);
    await userEvent.click(box("Mark"));
    expect(onChange).toHaveBeenCalledWith("mark_price", true);
  });

  it("a locked column: checked, T2 with its reason, never changed, and no move buttons", async () => {
    const onChange = vi.fn();
    await mount(<Host onChange={onChange} />);
    const symbol = box("Not available Symbol");
    expect(symbol).toBeChecked();
    expect(symbol).toHaveAttribute("aria-disabled", "true");
    expect(symbol).toHaveAccessibleDescription(SYMBOL_FIXED);
    await userEvent.click(symbol);
    expect(onChange).not.toHaveBeenCalled();
    expect(page.queryByRole("button", { name: "Move Symbol up" })).toBeNull();
  });

  it("a locked column shows its reason under the row (2a), the box's one description", async () => {
    await mount(<Host />);
    const symbol = box("Not available Symbol");
    const caption = page.getByText(SYMBOL_FIXED);
    expect(caption).not.toHaveClass("cv-visually-hidden");
    expect(caption.closest("[data-column]")).toBe(symbol.closest("[data-column]"));
    expect(symbol.getAttribute("aria-describedby")).toBe(caption.id);
  });

  it("a locked column's lock leads its label, named Not available (G-T2.1d)", async () => {
    await mount(<Host />);
    const row = box("Not available Symbol").closest("[data-column]") as HTMLElement;
    const label = row.querySelector<HTMLElement>(".cv-choice__label") as HTMLElement;
    expect(label.firstElementChild).toContainElement(
      within(label).getByRole("img", { name: "Not available" }),
    );
  });

  it("Move <column> up and down buttons; the movable range's ends are T2: Already first., Already last.", async () => {
    await mount(<Host />);
    const first = page.getByRole("button", { name: "Move Last up" });
    expect(first).toHaveAttribute("aria-disabled", "true");
    expect(first).toHaveAccessibleDescription("Already first.");
    const last = page.getByRole("button", { name: "Move Mark down" });
    expect(last).toHaveAccessibleDescription("Already last.");
    expect(page.getByRole("button", { name: "Move Last down" })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("a move keeps focus on the pressed button and says the new position once", async () => {
    await mount(<Host />);
    const up = page.getByRole("button", { name: "Move Funding % up" });
    await userEvent.click(up);
    expect(order()).toEqual(["Symbol", "Last", "24h %", "Funding %", "Turnover USDT", "Mark"]);
    expect(page.getByRole("button", { name: "Move Funding % up" })).toHaveFocus();
    await waitFor(() => expect(status()).toHaveTextContent("Funding % moved to position 4 of 6."));
  });

  it("Alt+↓ on a focused column's checkbox moves it, focus kept", async () => {
    await mount(<Host />);
    act(() => box("Last").focus());
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(order()).toEqual(["Symbol", "24h %", "Last", "Turnover USDT", "Funding %", "Mark"]);
    expect(box("Last")).toHaveFocus();
  });

  it("Alt+↑ at the top of the movable range moves nothing and says Already first. once", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host />
      </GatedAnnounceProvider>,
    );
    act(() => box("Last").focus());
    await userEvent.keyboard("{Alt>}{ArrowUp}{/Alt}");
    expect(order()[1]).toBe("Last");
    expect(announce.mock.calls).toEqual([["Already first."]]);
    expect(status()).not.toHaveTextContent("Already first.");
  });

  it("a press on an end's T2 move button says its reason once, from the button alone", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host />
      </GatedAnnounceProvider>,
    );
    await userEvent.click(page.getByRole("button", { name: "Move Mark down" }));
    expect(announce.mock.calls).toEqual([["Already last."]]);
    expect(status().textContent).toBe("");
  });

  it("Alt+↑ on the locked column moves nothing and says its reason once (a bound key on a T2 box)", async () => {
    const announce = vi.fn<(text: string) => void>();
    const onReorder = vi.fn();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host onReorder={onReorder} />
      </GatedAnnounceProvider>,
    );
    act(() => box("Not available Symbol").focus());
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(onReorder).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[SYMBOL_FIXED]]);
  });

  it("read-only: every checkbox and move button is T2 with the host's reason; nothing changes", async () => {
    const onChange = vi.fn();
    const onReorder = vi.fn();
    await mount(<Host writeReason={READ_ONLY} onChange={onChange} onReorder={onReorder} />);
    for (const b of page.getAllByRole("checkbox"))
      expect(b).toHaveAttribute("aria-disabled", "true");
    expect(box("Mark")).toHaveAccessibleDescription(READ_ONLY);
    await userEvent.click(box("Mark"));
    await userEvent.click(page.getByRole("button", { name: "Move Mark up" }));
    act(() => box("Last").focus());
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect([onChange.mock.calls.length, onReorder.mock.calls.length]).toEqual([0, 0]);
  });

  it("writeReasonId: every box and move button is described by the host's one notice (G-T2.5)", async () => {
    await mount(
      <>
        <p id="columns-notice">{READ_ONLY}</p>
        <Host writeReason={READ_ONLY} writeReasonId="columns-notice" />
      </>,
    );
    const gated = [
      ...page.getAllByRole("checkbox").filter((b) => b !== box("Not available Symbol")),
      ...page.getAllByRole("button", { name: /^Move / }),
    ];
    for (const control of gated) {
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).toHaveAttribute("aria-describedby", "columns-notice");
    }
    expect(page.getAllByText(READ_ONLY)).toHaveLength(1);
  });

  it("announce: the host's region says the move, and the picker renders none of its own", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(<Host announce={announce} />);
    expect(status()).toBeNull();
    await userEvent.click(page.getByRole("button", { name: "Move Last down" }));
    expect(announce).toHaveBeenCalledWith("Last moved to position 3 of 6.");
  });

  it("axe: no serious or critical violation, read-only too", async () => {
    const host = await mount(<Host writeReason={READ_ONLY} />);
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("ColumnPicker (CMP-056), the menu (SCR-100's Columns)", () => {
  const MenuHost = ({ writeReason }: { readonly writeReason?: string }): JSX.Element => {
    const [columns, setColumns] = useState(COLUMNS);
    return (
      <ColumnPicker
        variant="menu"
        label="Columns"
        columns={columns}
        {...(writeReason === undefined ? {} : { writeReason })}
        onChange={(id, visible) =>
          setColumns((all) => all.map((c) => (c.id === id ? { ...c, visible } : c)))
        }
      />
    );
  };

  it("a Columns button opens the columns as checkable menu items", async () => {
    await mount(<MenuHost />);
    await userEvent.click(page.getByRole("button", { name: "Columns" }));
    const items = within(page.getByRole("menu", { name: "Columns" })).getAllByRole(
      "menuitemcheckbox",
    );
    expect(items.map((i) => i.getAttribute("aria-checked"))).toEqual([
      "true",
      "true",
      "true",
      "true",
      "true",
      "false",
    ]);
  });

  it("Space on an item shows or hides its column and keeps the menu open", async () => {
    await mount(<MenuHost />);
    await userEvent.click(page.getByRole("button", { name: "Columns" }));
    await userEvent.keyboard("{ArrowUp} ");
    expect(page.getByRole("menuitemcheckbox", { name: "Mark" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(page.getByRole("menu", { name: "Columns" })).toBeVisible();
  });

  it("the locked column is a T2 item with its reason", async () => {
    await mount(<MenuHost />);
    await userEvent.click(page.getByRole("button", { name: "Columns" }));
    const symbol = page.getByRole("menuitemcheckbox", { name: /Symbol/ });
    expect(symbol).toHaveAttribute("aria-disabled", "true");
    expect(symbol).toHaveAccessibleDescription(new RegExp(SYMBOL_FIXED.replace(".", "\\.")));
  });

  it("writeReasonId: the Columns button is described by the host's one notice", async () => {
    await mount(
      <>
        <p id="columns-notice">{READ_ONLY}</p>
        <ColumnPicker
          variant="menu"
          label="Columns"
          columns={COLUMNS}
          writeReason={READ_ONLY}
          writeReasonId="columns-notice"
          onChange={() => undefined}
        />
      </>,
    );
    const button = page.getByRole("button", { name: "Not available Columns" });
    expect(button).toHaveAttribute("aria-describedby", "columns-notice");
    expect(page.getAllByText(READ_ONLY)).toHaveLength(1);
  });

  it("read-only: the Columns button itself is T2 with the reason", async () => {
    await mount(<MenuHost writeReason={READ_ONLY} />);
    const button = page.getByRole("button", { name: "Columns" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(READ_ONLY);
    await userEvent.click(button);
    expect(page.queryByRole("menu")).toBeNull();
  });

  // G-T2.3 (E09-D09 §9.3): a key on the T2 button changes nothing; the reason is re-shown once per press.
  it.each([
    ["ArrowDown", "{ArrowDown}"],
    ["ArrowUp", "{ArrowUp}"],
    ["Enter", "{Enter}"],
    ["Space", " "],
  ])(
    "read-only: %s on the Columns button opens nothing and says the reason once",
    async (_, key) => {
      const announce = vi.fn<(text: string) => void>();
      const onChange = vi.fn();
      await mount(
        <GatedAnnounceProvider announce={announce}>
          <ColumnPicker
            variant="menu"
            label="Columns"
            columns={COLUMNS}
            writeReason={READ_ONLY}
            onChange={onChange}
          />
        </GatedAnnounceProvider>,
      );
      act(() => page.getByRole("button", { name: "Columns" }).focus());
      await userEvent.keyboard(key);
      expect(page.queryByRole("menu")).toBeNull();
      expect(announce.mock.calls).toEqual([[READ_ONLY]]);
      // What would toggle an item had a menu opened (the lens's probe: ↓, ↓, Space) toggles nothing.
      await userEvent.keyboard("{ArrowDown}{ArrowDown} ");
      expect(onChange).not.toHaveBeenCalled();
      expect(page.queryByRole("menu")).toBeNull();
    },
  );

  it("read-only: a held ↓ on the Columns button says the reason once, not per repeat", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <ColumnPicker
          variant="menu"
          label="Columns"
          columns={COLUMNS}
          writeReason={READ_ONLY}
          onChange={() => undefined}
        />
      </GatedAnnounceProvider>,
    );
    const button = page.getByRole("button", { name: "Columns" });
    act(() => button.focus());
    fireEvent.keyDown(button, { key: "ArrowDown" });
    fireEvent.keyDown(button, { key: "ArrowDown", repeat: true });
    expect(announce.mock.calls).toEqual([[READ_ONLY]]);
    expect(page.queryByRole("menu")).toBeNull();
  });

  // A11Y-4702A3-01: one tree whatever `writeReason` is, so the button is never swapped for another.
  describe("as writeReason comes and goes", () => {
    let setReason: (reason: string | undefined) => void = () => undefined;
    /** A host whose session turns read-only and back, as a view-as switch does. */
    const Toggled = ({ initial }: { readonly initial?: string }): JSX.Element => {
      const [reason, set] = useState<string | undefined>(initial);
      setReason = set;
      return (
        <ColumnPicker
          variant="menu"
          label="Columns"
          columns={COLUMNS}
          {...(reason === undefined ? {} : { writeReason: reason })}
          onChange={() => undefined}
        />
      );
    };

    it("a focused Columns button keeps its node and its focus", async () => {
      await mount(<Toggled />);
      const button = page.getByRole("button", { name: "Columns" });
      act(() => button.focus());
      for (const reason of [READ_ONLY, undefined, READ_ONLY]) {
        act(() => setReason(reason));
        expect(page.getByRole("button", { name: "Columns" })).toBe(button);
        expect(button).toHaveFocus();
      }
    });

    it("↓ opens the menu once the reason is gone, and opens nothing when it is back", async () => {
      await mount(<Toggled initial={READ_ONLY} />);
      act(() => page.getByRole("button", { name: "Columns" }).focus());
      await userEvent.keyboard("{ArrowDown}");
      expect(page.queryByRole("menu")).toBeNull();
      act(() => setReason(undefined));
      await userEvent.keyboard("{ArrowDown}");
      expect(page.getByRole("menu", { name: "Columns" })).toBeVisible();
      await userEvent.keyboard("{Escape}");
      expect(page.getByRole("button", { name: "Columns" })).toHaveFocus();
      act(() => setReason(READ_ONLY));
      await userEvent.keyboard("{ArrowDown}");
      expect(page.queryByRole("menu")).toBeNull();
    });
  });
});

// Each story's play in jsdom (the storybook project runs them in Chromium, with axe).
describe("ColumnPicker stories", () => {
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });
});
