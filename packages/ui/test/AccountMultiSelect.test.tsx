// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { describe, it } from "vitest";
import { AccountMultiSelect, Button, type AccountOption } from "../src/components/index.js";
import * as stories from "../src/components/AccountMultiSelect.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const page = within(document.body);
const ACCOUNTS = [
  { id: "main", label: "Main" },
  { id: "sub-1", label: "Sub-1" },
  { id: "sub-2", label: "Sub-2" },
];

interface Spies {
  readonly onToggle: ReturnType<typeof fn>;
  readonly onSelectAll: ReturnType<typeof fn>;
  readonly onOpenChange: ReturnType<typeof fn>;
}

/** A host that holds the chosen ids, with a button before and after the picker. */
function Host({
  spies,
  initial = ["sub-1"],
  accounts = ACCOUNTS,
}: {
  readonly spies: Spies;
  readonly initial?: readonly string[];
  readonly accounts?: readonly Pick<AccountOption, "id" | "label">[];
}): JSX.Element {
  const [chosen, setChosen] = useState<readonly string[]>(initial);
  return (
    <>
      <button type="button">Before</button>
      <AccountMultiSelect
        mode="account"
        trigger={<Button iconLeft="plus">Filter</Button>}
        accounts={accounts.map((a) => ({ ...a, selected: chosen.includes(a.id) }))}
        onToggle={(id) => {
          spies.onToggle(id);
          setChosen((was) => (was.includes(id) ? was.filter((x) => x !== id) : [...was, id]));
        }}
        onSelectAll={() => {
          spies.onSelectAll();
          setChosen(accounts.map((a) => a.id));
        }}
        onOpenChange={spies.onOpenChange}
      />
      <button type="button">After</button>
    </>
  );
}

const spies = (): Spies => ({ onToggle: fn(), onSelectAll: fn(), onOpenChange: fn() });
const trigger = (): HTMLElement => page.getByRole("button", { name: "Filter" });
const list = (): HTMLElement => page.getByRole("listbox", { name: "Filter" });
const option = (name: string): HTMLElement => page.getByRole("option", { name });
const activeName = (): string => {
  const id = list().getAttribute("aria-activedescendant") ?? "";
  return document.getElementById(id)?.textContent ?? "";
};

/** Four accounts, so a fallback to the chosen one and to the first one land on different options. */
const FOUR = [...ACCOUNTS, { id: "sub-3", label: "Sub-3" }];

/** An open picker whose list loses accounts under it: "Revoke {label}" drops one (a scope change, server-side). */
function Revoking({ chosen = [] }: { readonly chosen?: readonly string[] }): JSX.Element {
  const [accounts, setAccounts] = useState(FOUR);
  return (
    <>
      <AccountMultiSelect
        mode="account"
        trigger={<Button>Filter</Button>}
        accounts={accounts.map((a) => ({ ...a, selected: chosen.includes(a.id) }))}
        onToggle={fn()}
        onSelectAll={fn()}
        defaultOpen
      />
      {FOUR.map((a) => (
        <button
          key={a.id}
          type="button"
          onClick={() => setAccounts((all) => all.filter((x) => x.id !== a.id))}
        >
          {`Revoke ${a.label}`}
        </button>
      ))}
    </>
  );
}
/** A programmatic press: no pointer, so no outside press closes the picker, and focus stays in the list. */
const revoke = async (label: string): Promise<void> =>
  act(async () => page.getByRole("button", { name: `Revoke ${label}` }).click());

describe("AccountMultiSelect (CMP-105, the account filter use)", () => {
  it("marks exactly one root with data-cmp, open or closed", async () => {
    await mount(<Host spies={spies()} />);
    expect(document.querySelectorAll('[data-cmp="CMP-105"]')).toHaveLength(1);
    await userEvent.click(trigger());
    expect(document.querySelectorAll('[data-cmp="CMP-105"]')).toHaveLength(1);
  });

  it("is closed at first: the trigger names the picker and opens a dialog", async () => {
    await mount(<Host spies={spies()} />);
    expect(document.querySelector('[data-cmp="CMP-105"]')).toHaveAttribute("data-mode", "account");
    expect(trigger()).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(page.queryByRole("listbox")).toBeNull();
  });

  it("Enter on the trigger opens a multi-select listbox named by the trigger, focus on it at the chosen option", async () => {
    const s = spies();
    await mount(<Host spies={s} />);
    await userEvent.tab();
    await userEvent.tab();
    expect(trigger()).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(s.onOpenChange).toHaveBeenLastCalledWith(true);
    expect(page.getByRole("dialog", { name: "Filter" })).toBeDefined();
    await waitFor(() => expect(list()).toHaveFocus());
    expect(list()).toHaveAttribute("aria-multiselectable", "true");
    expect(option("Sub-1")).toHaveAttribute("aria-selected", "true");
    expect(option("Main")).toHaveAttribute("aria-selected", "false");
    expect(activeName()).toBe("Sub-1");
  });

  it("Alt+↓ opens; ↑/↓ and Home/End move the active option without wrapping; Space toggles it", async () => {
    const s = spies();
    await mount(<Host spies={s} initial={[]} />);
    trigger().focus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() => expect(list()).toHaveFocus());
    expect(activeName()).toBe("Main");
    await userEvent.keyboard("{ArrowUp}");
    expect(activeName()).toBe("Main");
    await userEvent.keyboard("{End}");
    expect(activeName()).toBe("Sub-2");
    await userEvent.keyboard("{ArrowDown}");
    expect(activeName()).toBe("Sub-2");
    await userEvent.keyboard(" ");
    expect(s.onToggle).toHaveBeenLastCalledWith("sub-2");
    expect(option("Sub-2")).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Home} ");
    expect(s.onToggle).toHaveBeenLastCalledWith("main");
    await userEvent.keyboard(" ");
    expect(option("Main")).toHaveAttribute("aria-selected", "false");
  });

  it("Enter in the list closes it and Escape does too, each returning focus to the trigger", async () => {
    const s = spies();
    await mount(<Host spies={s} />);
    trigger().focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(list()).toHaveFocus());
    await userEvent.keyboard("{Enter}");
    expect(page.queryByRole("listbox")).toBeNull();
    // CMP-017 hands focus back in an effect once it has closed.
    await waitFor(() => expect(trigger()).toHaveFocus());
    expect(s.onToggle).not.toHaveBeenCalled();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    await waitFor(() => expect(list()).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(page.queryByRole("listbox")).toBeNull());
    await waitFor(() => expect(trigger()).toHaveFocus());
  });

  it("'Select all' is a distinct labelled control after the list, reached by Tab", async () => {
    const s = spies();
    await mount(<Host spies={s} initial={[]} />);
    await userEvent.click(trigger());
    await waitFor(() => expect(list()).toHaveFocus());
    await userEvent.tab();
    const all = page.getByRole("button", { name: "Select all" });
    expect(all).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(s.onSelectAll).toHaveBeenCalledTimes(1);
    for (const name of ["Main", "Sub-1", "Sub-2"])
      expect(option(name)).toHaveAttribute("aria-selected", "true");
  });

  it("a press on an option toggles it and makes it active; the pointer moves the active option", async () => {
    const s = spies();
    await mount(<Host spies={s} />);
    await userEvent.click(trigger());
    await userEvent.click(option("Main"));
    expect(s.onToggle).toHaveBeenLastCalledWith("main");
    expect(option("Main")).toHaveAttribute("aria-selected", "true");
    expect(activeName()).toBe("Main");
    await userEvent.hover(option("Sub-2"));
    expect(activeName()).toBe("Sub-2");
  });

  it("a Manager's options are the assigned accounts alone, none gated (no T2 on a filter)", async () => {
    await mount(<Host spies={spies()} accounts={ACCOUNTS.slice(1)} />);
    await userEvent.click(trigger());
    expect(page.getAllByRole("option").map((o) => o.textContent)).toEqual(["Sub-1", "Sub-2"]);
    expect(document.querySelector("[aria-disabled]")).toBeNull();
  });

  it("keeps the active account when the list changes under it, and falls back when it leaves", async () => {
    await mount(<Revoking chosen={["sub-3"]} />);
    await waitFor(() => expect(list()).toHaveFocus());
    expect(activeName()).toBe("Sub-3");
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    expect(activeName()).toBe("Sub-1");
    await revoke("Main");
    expect(activeName()).toBe("Sub-1");
    // The active account leaves: the active option falls to the chosen one (not the first, Sub-2), and the list
    // keeps DOM focus, so the keys go on working there.
    await revoke("Sub-1");
    expect(activeName()).toBe("Sub-3");
    expect(list()).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(activeName()).toBe("Sub-2");
  });

  it("with nothing chosen, an active account that leaves hands the active option to the first one", async () => {
    await mount(<Revoking />);
    await waitFor(() => expect(list()).toHaveFocus());
    await userEvent.keyboard("{End}");
    expect(activeName()).toBe("Sub-3");
    await revoke("Sub-3");
    // The first account, not the departed one's neighbour (Sub-2).
    expect(activeName()).toBe("Main");
    expect(list()).toHaveFocus();
  });

  it("a controlled open follows the host and reports each change", async () => {
    const onOpenChange = fn();
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button id="pick">Filter</Button>}
        accounts={[{ id: "main", label: "Main", selected: false }]}
        onToggle={fn()}
        onSelectAll={fn()}
        open
        onOpenChange={onOpenChange}
      />,
    );
    expect(trigger()).toHaveAttribute("id", "pick");
    expect(list()).toHaveAttribute("aria-labelledby", "pick");
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
    // Controlled: the host kept it open.
    expect(list()).toBeDefined();
  });

  it("an empty account list still opens and takes focus; its keys move and toggle nothing", async () => {
    const onToggle = fn();
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button>Filter</Button>}
        accounts={[]}
        onToggle={onToggle}
        onSelectAll={fn()}
        defaultOpen
      />,
    );
    await waitFor(() => expect(list()).toHaveFocus());
    expect(list()).not.toHaveAttribute("aria-activedescendant");
    await userEvent.keyboard("{ArrowDown} ");
    expect(onToggle).not.toHaveBeenCalled();
    expect(list()).not.toHaveAttribute("aria-activedescendant");
  });

  it("leaves a modified key in the list to the host: Ctrl+↓ moves nothing, Ctrl+Space toggles nothing", async () => {
    const s = spies();
    await mount(<Host spies={s} initial={[]} />);
    await userEvent.click(trigger());
    await waitFor(() => expect(list()).toHaveFocus());
    expect(activeName()).toBe("Main");
    await userEvent.keyboard("{Control>}{ArrowDown} {/Control}");
    expect(activeName()).toBe("Main");
    expect(s.onToggle).not.toHaveBeenCalled();
  });

  it("the trigger's own onKeyDown runs first: a host that takes Alt+↓ keeps the picker closed", async () => {
    const onOpenChange = fn();
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button onKeyDown={(event) => event.preventDefault()}>Filter</Button>}
        accounts={[{ id: "main", label: "Main", selected: false }]}
        onToggle={fn()}
        onSelectAll={fn()}
        onOpenChange={onOpenChange}
      />,
    );
    trigger().focus();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(page.queryByRole("listbox")).toBeNull();
  });

  it("Alt+↓ on the trigger of a picker already open opens nothing twice", async () => {
    const onOpenChange = fn();
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button>Filter</Button>}
        accounts={[{ id: "main", label: "Main", selected: false }]}
        onToggle={fn()}
        onSelectAll={fn()}
        open
        onOpenChange={onOpenChange}
      />,
    );
    // Focus leaving the panel for the trigger reports a close; the host keeps it open (controlled).
    await act(async () => trigger().focus());
    onOpenChange.mockClear();
    await userEvent.keyboard("{Alt>}{ArrowDown}{/Alt}");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(list()).toBeDefined();
  });

  it("emits density on the portalled list and its 'Select all'", async () => {
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button>Filter</Button>}
        accounts={[{ id: "main", label: "Main", selected: false }]}
        onToggle={fn()}
        onSelectAll={fn()}
        density="comfortable"
        defaultOpen
      />,
    );
    expect(list().dataset["density"]).toBe("comfortable");
    expect(page.getByRole("button", { name: "Select all" }).dataset["density"]).toBe("comfortable");
  });

  it("listLabel names the list when the trigger's words don't name the choice; the trigger still names the panel", async () => {
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button>Filter</Button>}
        listLabel="Accounts"
        accounts={[{ id: "main", label: "Main", selected: false }]}
        onToggle={fn()}
        onSelectAll={fn()}
        defaultOpen
      />,
    );
    const named = page.getByRole("listbox", { name: "Accounts" });
    expect(named).not.toHaveAttribute("aria-labelledby");
    expect(page.getByRole("dialog", { name: "Filter" })).toBeDefined();
    await waitFor(() => expect(named).toHaveFocus());
  });

  it("a blank listLabel leaves the trigger naming the list, as with none", async () => {
    await mount(
      <AccountMultiSelect
        mode="account"
        trigger={<Button>Filter</Button>}
        listLabel="  "
        accounts={[{ id: "main", label: "Main", selected: false }]}
        onToggle={fn()}
        onSelectAll={fn()}
        defaultOpen
      />,
    );
    expect(list()).not.toHaveAttribute("aria-label");
  });

  it("has no serious or critical axe violation, closed and open", async () => {
    await mount(<Host spies={spies()} />);
    expect(await seriousViolations(document.body)).toEqual([]);
    await userEvent.click(trigger());
    expect(await seriousViolations(document.body)).toEqual([]);
  });
});

describe("AccountMultiSelect stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    await mount(<Story />);
    expect(document.querySelectorAll('[data-cmp="CMP-105"]').length).toBeGreaterThan(0);
  });
});
