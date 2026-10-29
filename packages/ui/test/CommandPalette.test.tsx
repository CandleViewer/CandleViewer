// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Button,
  CommandPalette,
  type CommandPaletteProps,
  type PaletteCommand,
} from "../src/index.js";
import { mount } from "./theme/mount.js";

type Violation = { id: string; impact?: string | null };
type Axe = { run: (c: object, o?: object) => Promise<{ violations: Violation[] }> };
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const REASON = "Your role can't change positions.";
const run = { chart: vi.fn(), settings: vi.fn(), flatten: vi.fn(), lev: vi.fn() };
const CHART: PaletteCommand = {
  id: "chart",
  label: "Go to chart",
  group: "Navigate",
  shortcut: ["Ctrl", "1"],
  onRun: () => run.chart(),
};
const SETTINGS: PaletteCommand = {
  id: "settings",
  label: "Open settings",
  group: "Setting",
  onRun: () => run.settings(),
};
const FLATTEN: PaletteCommand = {
  id: "flatten",
  label: "Flatten all positions",
  group: "Action",
  destructive: true,
  onRun: () => run.flatten(),
};
const LEVERAGE: PaletteCommand = {
  id: "lev",
  label: "Set leverage",
  group: "Action",
  disabledReason: REASON,
  onRun: () => run.lev(),
};
const COMMANDS = [CHART, SETTINGS, FLATTEN, LEVERAGE];

type Extra = Partial<Omit<CommandPaletteProps, "open" | "onOpenChange">>;
/** A host with an opener: it owns `open`, as the shell's `Ctrl+K` binding does. */
function Host({ spy, ...props }: Extra & { spy?: (open: boolean) => void }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Commands</Button>
      <CommandPalette
        commands={COMMANDS}
        {...props}
        open={open}
        onOpenChange={(next) => {
          spy?.(next);
          setOpen(next);
        }}
      />
    </>
  );
}

const screen = (): ReturnType<typeof within> => within(document.body);
const input = (): HTMLElement => screen().getByRole("combobox", { name: "Search commands" });
const status = (): HTMLElement => screen().getByRole("status");
const names = (): string[] =>
  screen()
    .queryAllByRole("option")
    .map((o: HTMLElement) => o.getAttribute("aria-label") ?? "");
const groups = (): string[] =>
  screen()
    .queryAllByRole("group")
    .map(
      (g: HTMLElement) =>
        document.getElementById(g.getAttribute("aria-labelledby") ?? "")?.textContent ?? "",
    );
const active = (): string | null => {
  const id = input().getAttribute("aria-activedescendant");
  return id === null ? null : (document.getElementById(id)?.getAttribute("aria-label") ?? null);
};
const press = async (key: string, init: KeyboardEventInit = {}): Promise<void> => {
  await act(async () =>
    input().dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
    ),
  );
};
const type = (text: string): Promise<void> =>
  act(async () => void fireEvent.change(input(), { target: { value: text } }));
const wait = (ms: number): Promise<void> =>
  act(() => vi.advanceTimersByTimeAsync(ms).then(() => undefined));
const openHost = async (ui: JSX.Element): Promise<HTMLElement> => {
  const host = await mount(ui);
  const opener = within(host).getByRole("button", { name: "Commands" });
  await act(async () => {
    opener.focus();
    fireEvent.click(opener);
  });
  return host;
};

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  Object.values(run).forEach((f) => f.mockClear());
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("CommandPalette (CMP-059)", () => {
  it("opens as a named modal dialog with focus in a combobox that owns a grouped listbox", async () => {
    await openHost(<Host />);
    const dialog = screen().getByRole("dialog", { name: "Command palette" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(input()).toHaveFocus();
    const list = screen().getByRole("listbox", { name: "Commands" });
    expect(input()).toHaveAttribute("aria-controls", list.id);
    expect(input()).toHaveAttribute("aria-expanded", "true");
    expect(input()).toHaveAttribute("aria-autocomplete", "list");
    // No sections given: every command, grouped in first-appearance order; the first is active.
    expect(groups()).toEqual(["Navigate", "Setting", "Action"]);
    expect(active()).toBe("Go to chart");
  });

  it("an empty query shows the host's sections and drops an empty one", async () => {
    await openHost(
      <Host
        sections={[
          { label: "Recent", commands: [SETTINGS, CHART] },
          { label: "Pinned", commands: [] },
          { label: "Suggested", commands: [CHART] },
        ]}
      />,
    );
    expect(groups()).toEqual(["Recent", "Suggested"]);
    expect(names()).toEqual(["Open settings", "Go to chart", "Go to chart"]);
    // Every option id is unique, though a command shows in two sections.
    const ids = screen()
      .getAllByRole("option")
      .map((o: HTMLElement) => o.id);
    expect(new Set(ids).size).toBe(3);
  });

  it("a query ranks, groups (empty groups dropped), marks matches and activates the first result", async () => {
    await openHost(<Host />);
    await type("set");
    expect(groups()).toEqual(["Setting", "Action"]);
    expect(names()).toEqual(["Open settings", "Set leverage"]);
    expect(active()).toBe("Open settings");
    const mark = screen().getByRole("option", { name: "Set leverage" }).querySelector("mark");
    expect(mark?.textContent).toBe("Set");
  });

  it("keyboard: ↓ / ↑ wrap, Home / End, PageUp / PageDown by ten; focus never leaves the input", async () => {
    const many = Array.from({ length: 14 }, (_, i) => ({
      id: `c${String(i)}`,
      label: `Command ${String(i)}`,
      group: "Action",
      onRun: () => undefined,
    }));
    await openHost(<Host commands={many} />);
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled(); // opening never scrolls
    const steps: [string, string][] = [
      ["ArrowUp", "Command 13"],
      ["ArrowDown", "Command 0"],
      ["ArrowDown", "Command 1"],
      ["PageDown", "Command 11"],
      ["PageDown", "Command 13"],
      ["PageUp", "Command 3"],
      ["PageUp", "Command 0"],
      ["End", "Command 13"],
      ["Home", "Command 0"],
    ];
    for (const [key, expected] of steps) {
      await press(key);
      expect([key, active()]).toEqual([key, expected]);
      expect(input()).toHaveFocus();
    }
    expect(Element.prototype.scrollIntoView).toHaveBeenLastCalledWith({ block: "nearest" });
    const option = screen().getByRole("option", { name: "Command 0" });
    expect(option).toHaveAttribute("aria-selected", "true");
    // A press on a row keeps focus in the input.
    const down = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    option.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
  });

  it("Enter runs the active command once and closes; a held key does not run it again", async () => {
    const spy = vi.fn();
    await openHost(<Host spy={spy} />);
    await press("Enter", { repeat: true });
    expect(run.chart).not.toHaveBeenCalled();
    await press("Enter");
    expect(run.chart).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenLastCalledWith(false);
    expect(screen().queryByRole("dialog")).toBeNull();
  });

  it("Esc closes and returns focus to the opener", async () => {
    const host = await openHost(<Host />);
    await press("Escape");
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(within(host).getByRole("button", { name: "Commands" })).toHaveFocus();
  });

  it("a destructive row is tagged 'confirms' and asks the host's confirm; it never runs", async () => {
    const confirm = vi.fn();
    const group = vi.fn();
    const spy = vi.fn();
    await openHost(<Host onRequestConfirm={confirm} onRunGroup={group} spy={spy} />);
    await type("flatten");
    expect(active()).toBe("Flatten all positions, confirms");
    const option = screen().getByRole("option", { name: "Flatten all positions, confirms" });
    expect(option.closest(".cv-palette__row")?.querySelector(".cv-palette__tag")).toHaveTextContent(
      "confirms",
    );
    await press("Enter");
    expect(confirm).toHaveBeenLastCalledWith(FLATTEN, "one");
    await press("Enter", { ctrlKey: true });
    expect(confirm).toHaveBeenLastCalledWith(FLATTEN, "group");
    await act(async () => fireEvent.click(option));
    expect(confirm).toHaveBeenCalledTimes(3);
    expect([run.flatten.mock.calls.length, group.mock.calls.length, spy.mock.calls]).toEqual([
      0,
      0,
      [],
    ]);
    expect(input()).toHaveFocus(); // the palette stays open under the host's confirm
  });

  it("a gated row is reachable and aria-disabled; Enter re-shows its reason once per press, never runs", async () => {
    vi.useFakeTimers();
    await openHost(<Host onRunGroup={vi.fn()} />);
    await type("leverage");
    await wait(500);
    const option = screen().getByRole("option", { name: "Set leverage" });
    expect(option).toHaveAttribute("aria-disabled", "true");
    expect(option).toHaveAccessibleDescription(REASON);
    expect(active()).toBe("Set leverage");
    const count = status().firstElementChild;
    expect(status()).toHaveTextContent("1 result");
    await press("Enter");
    const first = status().lastElementChild;
    expect(first).toHaveTextContent(REASON);
    await press("Enter", { repeat: true }); // held: no second announcement
    expect(status().lastElementChild).toBe(first);
    await press("Enter", { ctrlKey: true }); // gated as Enter
    const second = status().lastElementChild;
    expect(second).not.toBe(first);
    expect(second).toHaveTextContent(REASON);
    expect(status().querySelectorAll("span")).toHaveLength(2); // the count, then one reason
    expect(status().firstElementChild).toBe(count); // the count is not said again
    expect(run.lev).not.toHaveBeenCalled();
  });

  it("Ctrl+Enter runs the group action and closes; without onRunGroup it is a no-op with no footer", async () => {
    const group = vi.fn();
    await openHost(<Host onRunGroup={group} />);
    expect(screen().getByText("runs for every account in the group")).toBeInTheDocument();
    await press("Enter", { ctrlKey: true });
    expect(group).toHaveBeenCalledWith(CHART);
    expect(run.chart).not.toHaveBeenCalled();
    expect(screen().queryByRole("dialog")).toBeNull();
    document.body.replaceChildren();

    await openHost(<Host />);
    expect(screen().queryByText("runs for every account in the group")).toBeNull();
    await press("Enter", { ctrlKey: true });
    expect(run.chart).not.toHaveBeenCalled();
    expect(screen().getByRole("dialog")).toBeInTheDocument();
  });

  it("the count is said once per settled query, never per keystroke", async () => {
    vi.useFakeTimers();
    await openHost(<Host />);
    expect(status()).toHaveTextContent(""); // nothing on open
    await type("o");
    await wait(200);
    await type("op");
    await wait(499);
    expect(status()).toHaveTextContent("");
    await wait(1);
    expect(status()).toHaveTextContent("1 result");
    const node = status().firstElementChild;
    await press("ArrowDown");
    expect(status().firstElementChild).toBe(node);
    await type("open");
    expect(status()).toHaveTextContent("");
    await wait(500);
    expect(status()).toHaveTextContent("1 result");
  });

  it("no match: no listbox, collapsed, the host's sentence shown and said", async () => {
    vi.useFakeTimers();
    await openHost(<Host noResultsText={(q) => `Nothing for ${q}`} />);
    await type("xyz");
    expect(screen().queryByRole("listbox")).toBeNull();
    expect(input()).toHaveAttribute("aria-expanded", "false");
    expect(input()).not.toHaveAttribute("aria-controls");
    expect(input()).not.toHaveAttribute("aria-activedescendant");
    expect(screen().getByText("Nothing for xyz")).toBeInTheDocument();
    await press("Enter");
    await wait(500);
    expect(status()).toHaveTextContent("Nothing for xyz");
  });

  it("hides the Kbd hint from AT and carries aria-keyshortcuts on the option", async () => {
    await openHost(<Host />);
    const option = screen().getByRole("option", { name: "Go to chart" });
    expect(option).toHaveAttribute("aria-keyshortcuts", "Control+1");
    const kbd = option.closest(".cv-palette__row")?.querySelector(".cv-palette__kbd");
    expect(kbd).toHaveAttribute("aria-hidden", "true");
  });

  it("strings are props; a reopening starts from the host's query", async () => {
    const host = await openHost(
      <Host
        title="Palette"
        inputLabel="Find"
        listLabel="Found"
        placeholder="Type a command"
        countText={(n) => `${String(n)} found`}
        defaultQuery="chart"
      />,
    );
    expect(screen().getByRole("dialog", { name: "Palette" })).toBeInTheDocument();
    const field = screen().getByRole("combobox", { name: "Find" });
    expect(field).toHaveValue("chart");
    expect(field).toHaveAttribute("placeholder", "Type a command");
    expect(screen().getByRole("listbox", { name: "Found" })).toBeInTheDocument();
    expect(screen().getByRole("status")).toHaveTextContent("1 found");
    await act(async () => fireEvent.change(field, { target: { value: "zzz" } }));
    await act(async () => fireEvent.keyDown(field, { key: "Escape" }));
    await act(async () => fireEvent.click(within(host).getByRole("button", { name: "Commands" })));
    expect(screen().getByRole("combobox", { name: "Find" })).toHaveValue("chart");
  });

  it("a click on a row runs it", async () => {
    await openHost(<Host />);
    await act(async () => fireEvent.click(screen().getByRole("option", { name: "Open settings" })));
    expect(run.settings).toHaveBeenCalledTimes(1);
  });

  it("has no serious or critical axe violation with every row kind showing", async () => {
    await openHost(<Host onRunGroup={vi.fn()} />);
    const { violations } = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
