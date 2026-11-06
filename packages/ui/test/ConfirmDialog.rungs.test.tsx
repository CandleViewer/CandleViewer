// @vitest-environment jsdom
/**
 * E42-S02 (#1023): CMP-044's ladder (E42-D03 §12, `15` CMP-044's catalogued props). The rung derives the
 * variant; the two-choice block is a radiogroup named by its lead, required, none checked, whose T2 option is
 * focused but never checked; the acknowledgement follows it; Confirm stays natively disabled (form validity,
 * never T2: R-2) until a choice, then the tick, then the typed name, the hint naming the first unmet input; the
 * step-up line and the audit marker close the body, the marker last and part of the dialog's description.
 */
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import {
  Button,
  ConfirmDialog,
  type ConfirmAuditCode,
  type ConfirmChoice,
  type ConfirmDialogProps,
  type ConfirmMeta,
} from "../src/components/index.js";
import { visibleTabbables } from "../src/components/internal/focusTrap.js";
import { mount } from "./theme/mount.js";

/** The injected clock: the dialog opens at t = 1000; a test moves `t` past the 400 ms guard. */
let t = 1000;
const now = (): number => t;
beforeEach(() => {
  t = 1000;
});
afterEach(() => vi.restoreAllMocks());

const page = within(document.body);
const dialog = (): HTMLElement => page.getByRole("alertdialog") as HTMLElement;
const confirmButton = (name = "Disable alex"): HTMLElement =>
  page.getByRole("button", { name }) as HTMLElement;
const radio = (name: string | RegExp): HTMLElement => page.getByRole("radio", { name });
const tick = (): HTMLElement => page.getByRole("checkbox") as HTMLElement;
/** The dialog's own polite line (the re-shown reason of a T2 option). */
const politeLine = (): string => within(dialog()).getByRole("status").textContent ?? "";

const LEAD = "We can't count the open positions and orders on sub_001 [LIVE] right now.";
const LEAVE: ConfirmChoice = {
  id: "leave",
  label: "Leave positions open — you take over",
  consequence:
    "The positions and orders stay as they are on Bybit. Their exchange stop-losses stay active.",
};
const FLATTEN: ConfirmChoice = {
  id: "flatten",
  label: "Flatten first, then remove access",
  consequence: "Closes the open positions at market on sub_001, then removes alex's access.",
};
const NEEDS_COUNT = "Needs the open-position count.";
const FLATTEN_T2: ConfirmChoice = { ...FLATTEN, disabledReason: NEEDS_COUNT };
const ACK =
  "I accept that any open positions and orders stay open on Bybit under their exchange stop-losses.";
const CHOOSE_FIRST = "Choose an option first.";
const ACK_FIRST = "Tick the acknowledgement first.";
const CODES: readonly ConfirmAuditCode[] = [
  { label: "Disable user", code: "users.disable" },
  { label: "Session signed out", code: "auth.session_revoked" },
];

type Extra = Partial<
  Omit<ConfirmDialogProps, "open" | "choice" | "onChoiceChange" | "acknowledge">
> & {
  /** The two-choice block, its choice held by the host. */
  readonly options?: readonly ConfirmChoice[];
  /** The acknowledgement, its tick held by the host. */
  readonly withTick?: boolean;
  /** What the host holds as chosen when the dialog opens (a host defect the dialog must survive). */
  readonly initialChoice?: string;
  readonly picked?: (id: string) => void;
  readonly ticked?: (checked: boolean) => void;
};

/** SCR-121's dialog host: the opener, the choice and the tick it owns; Cancel and Esc close it. */
function Host({
  options,
  withTick = false,
  initialChoice,
  picked,
  ticked,
  onConfirm,
  onCancel,
  ...props
}: Extra): JSX.Element {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<string | undefined>(initialChoice);
  const [checked, setChecked] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Open</Button>
      <ConfirmDialog
        open={open}
        title="Disable alex"
        message="alex can't sign in from now on."
        confirmLabel="Disable alex"
        now={now}
        onConfirm={(meta) => onConfirm?.(meta)}
        onCancel={(reason) => {
          onCancel?.(reason);
          setOpen(false);
        }}
        {...(options === undefined
          ? {}
          : {
              choices: options,
              choiceLead: LEAD,
              choice,
              onChoiceChange: (id: string) => {
                picked?.(id);
                setChoice(id);
              },
            })}
        {...(withTick
          ? {
              acknowledge: {
                label: ACK,
                checked,
                onChange: (next: boolean) => {
                  ticked?.(next);
                  setChecked(next);
                },
              },
            }
          : {})}
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

const key = async (keys: string): Promise<void> => {
  await userEvent.keyboard(keys);
};

describe("ConfirmDialog (CMP-044): the rung derives the variant (E42-D03 §12)", () => {
  // A hold given a typed value asks for it too (E29-D02 §8.4); a standard one never does.
  it.each([
    [0, "hold", 1],
    [1, "standard", 0],
    [2, "standard", 0],
    [3, "typed", 1],
  ] as const)("rung %i is %s", async (rung, variant, fields) => {
    await openHost({ rung, typedConfirmValue: "alex" });
    const root = dialog().querySelector('[data-cmp="CMP-044"]');
    expect(root).toHaveAttribute("data-variant", variant);
    expect(page.queryAllByRole("textbox")).toHaveLength(fields);
    expect(page.queryAllByRole("progressbar")).toHaveLength(variant === "hold" ? 1 : 0);
  });

  it("rung 4 is typed where a typed value is given, else standard", async () => {
    await openHost({ rung: 4, typedConfirmValue: "2026-09-13 04:00" });
    expect(dialog().querySelector('[data-cmp="CMP-044"]')).toHaveAttribute("data-variant", "typed");
    expect(page.getByRole("textbox", { name: "Type 2026-09-13 04:00 to confirm" })).toBeVisible();
  });

  it("rung 4 without a typed value is standard", async () => {
    await openHost({ rung: 4 });
    expect(dialog().querySelector('[data-cmp="CMP-044"]')).toHaveAttribute(
      "data-variant",
      "standard",
    );
  });

  it("passing a rung and a variant both is a dev error: it is warned and the rung wins", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await openHost({ rung: 1, variant: "typed", typedConfirmValue: "alex" });
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("rung"));
    expect(dialog().querySelector('[data-cmp="CMP-044"]')).toHaveAttribute(
      "data-variant",
      "standard",
    );
    expect(page.queryByRole("textbox")).toBeNull();
  });

  it("a confirm after every input fires once with the rung's variant", async () => {
    const onConfirm = vi.fn();
    await openHost({ rung: 3, typedConfirmValue: "alex", withTick: true, onConfirm });
    await userEvent.click(tick());
    await userEvent.type(page.getByRole("textbox", { name: "Type alex to confirm" }), "alex");
    t = 5000;
    await userEvent.click(confirmButton());
    await userEvent.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).toMatchObject<Partial<ConfirmMeta>>({
      variant: "typed",
      gate: "typed",
    });
  });
});

describe("ConfirmDialog (CMP-044): the two-choice block", () => {
  it("is a radiogroup named by its lead, required, with no option checked at opening", async () => {
    await openHost({ rung: 2, options: [LEAVE, FLATTEN] });
    const group = page.getByRole("radiogroup", { name: LEAD });
    expect(group).toHaveAttribute("aria-required", "true");
    expect(page.getByText(LEAD)).toBeVisible();
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    for (const r of radios) expect(r).toHaveAttribute("aria-checked", "false");
    expect(radio(LEAVE.label)).toHaveAccessibleDescription(LEAVE.consequence);
    expect(page.getByText(LEAVE.consequence)).toBeVisible();
  });

  it("focus opens on Cancel; the DOM order is the group, the tick, Cancel (Confirm skipped while disabled)", async () => {
    await openHost({ rung: 2, options: [LEAVE, FLATTEN], withTick: true });
    const cancel = page.getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    expect(visibleTabbables(dialog())).toEqual([radio(LEAVE.label), tick(), cancel]);
    // Tab from Cancel wraps into the group on its first option, which it does not check.
    await key("{Tab}");
    expect(radio(LEAVE.label)).toHaveFocus();
    expect(radio(LEAVE.label)).toHaveAttribute("aria-checked", "false");
  });

  it("Space checks the focused option; the arrows move and check", async () => {
    const picked = vi.fn();
    await openHost({ rung: 2, options: [LEAVE, FLATTEN], picked });
    await act(async () => radio(LEAVE.label).focus());
    await key(" ");
    expect(picked).toHaveBeenLastCalledWith("leave");
    expect(radio(LEAVE.label)).toHaveAttribute("aria-checked", "true");
    await key("{ArrowDown}");
    expect(radio(FLATTEN.label)).toHaveFocus();
    expect(radio(FLATTEN.label)).toHaveAttribute("aria-checked", "true");
    expect(radio(LEAVE.label)).toHaveAttribute("aria-checked", "false");
  });

  it("a T2 option keeps role radio, aria-disabled, the named lock leading its label, its reason its second line", async () => {
    await openHost({ rung: 2, options: [LEAVE, FLATTEN_T2], withTick: true });
    const gated = radio(/Flatten first, then remove access$/);
    expect(gated).toHaveAttribute("aria-disabled", "true");
    expect(gated).not.toHaveAttribute("disabled");
    expect(gated).toHaveAccessibleName("Not available Flatten first, then remove access");
    expect(within(gated).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    // The reason is in the DOM at mount, visible, and the option's description (G-T2.1c).
    expect(page.getByText(NEEDS_COUNT)).toBeVisible();
    expect(gated).toHaveAccessibleDescription(new RegExp(`^${NEEDS_COUNT}`));
    // The lock leads: it comes before the label's words.
    const label = gated.querySelector(".cv-confirm__choice-label");
    expect(label?.firstElementChild?.querySelector("svg")).not.toBeNull();
  });

  it("a reason of whitespace alone is no reason: the option is no T2, carries no lock and checks", async () => {
    const picked = vi.fn();
    await openHost({
      rung: 2,
      options: [LEAVE, { ...FLATTEN, disabledReason: "  \t " }],
      withTick: true,
      picked,
    });
    const option = radio(FLATTEN.label);
    expect(option).not.toHaveAttribute("aria-disabled");
    expect(option).toHaveAccessibleName(FLATTEN.label);
    expect(within(option).queryByRole("img", { name: "Not available" })).toBeNull();
    expect(option).toHaveAccessibleDescription(FLATTEN.consequence);
    await act(async () => option.focus());
    await key(" ");
    expect(picked).toHaveBeenLastCalledWith("flatten");
    expect(option).toHaveAttribute("aria-checked", "true");
    expect(confirmButton()).toHaveAccessibleDescription(ACK_FIRST);
  });

  it("an arrow onto a T2 option focuses it without checking it; the checked option stays", async () => {
    const picked = vi.fn();
    await openHost({ rung: 2, options: [LEAVE, FLATTEN_T2], withTick: true, picked });
    await act(async () => radio(LEAVE.label).focus());
    await key(" ");
    await key("{ArrowDown}");
    const gated = radio(/Flatten first, then remove access$/);
    expect(gated).toHaveFocus();
    expect(gated).toHaveAttribute("aria-checked", "false");
    expect(radio(LEAVE.label)).toHaveAttribute("aria-checked", "true");
    expect(picked).toHaveBeenCalledTimes(1);
  });

  it("Space or Enter on a T2 option checks nothing and re-shows its reason once, politely; a held key once", async () => {
    const picked = vi.fn();
    await openHost({ rung: 2, options: [LEAVE, FLATTEN_T2], picked });
    const gated = radio(/Flatten first, then remove access$/);
    await act(async () => gated.focus());
    await key(" ");
    expect(picked).not.toHaveBeenCalled();
    expect(gated).toHaveAttribute("aria-checked", "false");
    expect(politeLine()).toBe(NEEDS_COUNT);
    const said = (): number => within(dialog()).getByRole("status").querySelectorAll("span").length;
    expect(said()).toBe(1);
    // A held Space: its repeats say nothing more.
    await act(async () => {
      fireEvent.keyDown(gated, { key: " ", repeat: true });
      fireEvent.keyDown(gated, { key: " ", repeat: true });
    });
    const keyed = within(dialog()).getByRole("status").firstElementChild;
    await key("{Enter}");
    expect(politeLine()).toBe(NEEDS_COUNT);
    // A new press re-keys the line, so the same words are said again.
    expect(within(dialog()).getByRole("status").firstElementChild).not.toBe(keyed);
    expect(picked).not.toHaveBeenCalled();
  });

  it("a click on a T2 option checks nothing and re-shows its reason", async () => {
    const picked = vi.fn();
    await openHost({ rung: 2, options: [LEAVE, FLATTEN_T2], picked });
    await userEvent.click(radio(/Flatten first, then remove access$/));
    expect(picked).not.toHaveBeenCalled();
    expect(politeLine()).toBe(NEEDS_COUNT);
  });

  it("Enter in the group never confirms", async () => {
    const onConfirm = vi.fn();
    await openHost({ rung: 2, options: [LEAVE, FLATTEN], onConfirm });
    await act(async () => radio(LEAVE.label).focus());
    await key(" ");
    t = 5000;
    expect(fireEvent.keyDown(radio(LEAVE.label), { key: "Enter" })).toBe(false);
    await key("{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    expect(dialog()).toBeVisible();
  });

  it("a dismissal picks nothing: Esc and Cancel leave the choice as it was", async () => {
    const picked = vi.fn();
    const onCancel = vi.fn();
    const host = await openHost({ rung: 2, options: [LEAVE, FLATTEN], picked, onCancel });
    await key("{Escape}");
    expect(onCancel).toHaveBeenLastCalledWith("escape");
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Open" }));
    });
    await userEvent.click(page.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenLastCalledWith("cancel");
    expect(picked).not.toHaveBeenCalled();
  });

  it("busy: the choice and the tick do not change", async () => {
    const picked = vi.fn();
    const ticked = vi.fn();
    await openHost({
      rung: 2,
      options: [LEAVE, FLATTEN],
      withTick: true,
      picked,
      ticked,
      busy: true,
    });
    await act(async () => radio(LEAVE.label).focus());
    await key(" ");
    await key("{ArrowDown}");
    await userEvent.click(tick());
    expect(picked).not.toHaveBeenCalled();
    expect(ticked).not.toHaveBeenCalled();
  });

  it("a choice held at opening is warned (none is ever pre-selected)", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await openHost({ rung: 2, options: [LEAVE, FLATTEN], initialChoice: "leave" });
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("pre-selected"));
  });
});

describe("ConfirmDialog (CMP-044): the acknowledgement and the validity form (R-2)", () => {
  it("Confirm stays natively disabled until a choice, then the tick; the hint names the first unmet input", async () => {
    await openHost({ rung: 2, options: [LEAVE, FLATTEN_T2], withTick: true });
    const confirm = confirmButton();
    expect(tick()).toHaveAccessibleName(ACK);
    // Form validity, never T2: native disabled, out of the Tab order, no lock, no aria-disabled.
    expect(confirm).toBeDisabled();
    expect(confirm).not.toHaveAttribute("aria-disabled");
    expect(confirm.querySelector("svg")).toBeNull();
    expect(confirm).toHaveAttribute("data-unmet");
    expect(visibleTabbables(dialog())).not.toContain(confirm);
    expect(page.getByText(CHOOSE_FIRST)).toBeVisible();
    expect(confirm).toHaveAccessibleDescription(CHOOSE_FIRST);
    await userEvent.click(radio(LEAVE.label));
    expect(page.queryByText(CHOOSE_FIRST)).toBeNull();
    expect(page.getByText(ACK_FIRST)).toBeVisible();
    expect(confirm).toHaveAccessibleDescription(ACK_FIRST);
    expect(confirm).toBeDisabled();
    await userEvent.click(tick());
    expect(page.queryByText(ACK_FIRST)).toBeNull();
    expect(confirm).toBeEnabled();
    expect(confirm).not.toHaveAttribute("data-unmet");
    expect(confirm).not.toHaveAccessibleDescription(ACK_FIRST);
    // Unticking takes it back.
    await userEvent.click(tick());
    expect(confirm).toBeDisabled();
    expect(page.getByText(ACK_FIRST)).toBeVisible();
  });

  it("rung 3: the typed name after the choice and the tick; Enter in the field never confirms", async () => {
    const onConfirm = vi.fn();
    await openHost({
      rung: 3,
      options: [LEAVE, FLATTEN_T2],
      withTick: true,
      typedConfirmValue: "alex",
      typedInstruction: "Type the username to confirm.",
      confirmLabel: "Delete alex (keeps history)",
      onConfirm,
    });
    const confirm = confirmButton("Delete alex (keeps history)");
    await userEvent.click(radio(LEAVE.label));
    await userEvent.click(tick());
    expect(confirm).toBeDisabled();
    const hint = dialog().querySelector(".cv-confirm__hint");
    expect(hint).toHaveTextContent("Type the username to confirm.");
    expect(confirm).toHaveAccessibleDescription("Type the username to confirm.");
    const field = page.getByRole("textbox", { name: "Type the username to confirm." });
    await userEvent.type(field, "alex");
    expect(confirm).toBeEnabled();
    expect(dialog().querySelector(".cv-confirm__hint")).toBeNull();
    t = 5000;
    expect(fireEvent.keyDown(field, { key: "Enter" })).toBe(false);
    await userEvent.type(field, "{Enter}");
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("a T2 option the host holds as chosen never enables Confirm", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await openHost({ rung: 2, options: [LEAVE, FLATTEN_T2], initialChoice: "flatten" });
    expect(radio(/Flatten first, then remove access$/)).toHaveAttribute("aria-checked", "false");
    expect(confirmButton()).toBeDisabled();
    expect(page.getByText(CHOOSE_FIRST)).toBeVisible();
  });

  it("while the counts load Confirm is natively disabled with CMP-001's loading look, and no hint shows", async () => {
    await openHost({ rung: 2, options: [LEAVE, FLATTEN], withTick: true, summaryLoading: true });
    const confirm = confirmButton();
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(confirm).not.toHaveAttribute("data-unmet");
    expect(page.queryByText(CHOOSE_FIRST)).toBeNull();
  });

  it("a rung with no input to wait on is enabled at once (rung 1)", async () => {
    await openHost({ rung: 1, confirmLabel: "Enable dan" });
    expect(confirmButton("Enable dan")).toBeEnabled();
    expect(dialog().querySelector(".cv-confirm__hint")).toBeNull();
  });

  it("without the ladder nothing new renders: a typed dialog keeps its plain look", async () => {
    await openHost({ variant: "typed", typedConfirmValue: "alex" });
    const confirm = confirmButton();
    expect(confirm).toBeDisabled();
    expect(confirm).not.toHaveAttribute("data-unmet");
    expect(confirm).toHaveAccessibleDescription("Type alex to confirm");
    expect(dialog().querySelector(".cv-confirm__hint")).toBeNull();
    expect(dialog().querySelector(".cv-confirm__stepup")).toBeNull();
    expect(dialog().querySelector(".cv-confirm__marker")).toBeNull();
  });
});

// The ladder composed with #5347's validity props and with T2 (E42-D03 §12/§13, R-2; E16-D04 §1.3; D09 §9.1).
// With a rung the validity look never applies: the host's `validityReason` is the hint's last step, Confirm
// natively disabled; `typedReason` is not used (the hint carries the typed instruction). A T2 reason still wins.
describe("ConfirmDialog (CMP-044): the ladder with the host's rule, the typed reason and T2", () => {
  const HOST_RULE = "Give a reason of at least 3 characters.";
  const TYPED = "Type alex exactly to confirm.";
  const OWNER_ONLY = "Only the owner can manage users.";
  const polite = (): string =>
    document.querySelector(".cv-confirm > [role='status']")?.textContent ?? "";

  /** A host whose own field (in `children`) holds a rule until it is met. */
  function RuleHost(props: Extra): JSX.Element {
    const [rule, setRule] = useState<string | undefined>(HOST_RULE);
    return (
      <Host {...props} validityReason={rule}>
        <Button onClick={() => setRule(undefined)}>Meet the rule</Button>
      </Host>
    );
  }

  const openRuleHost = async (props: Extra): Promise<void> => {
    const host = await mount(<RuleHost {...props} />);
    const opener = within(host).getByRole("button", { name: "Open" });
    await act(async () => opener.focus());
    await act(async () => {
      fireEvent.click(opener);
    });
  };

  it("a met rung with the host's rule: natively disabled, the hint is the rule, nothing fires until it clears", async () => {
    const onConfirm = vi.fn();
    await openRuleHost({ rung: 1, confirmLabel: "Enable dan", onConfirm });
    const confirm = confirmButton("Enable dan");
    expect(confirm).toBeDisabled();
    expect(confirm).not.toHaveAttribute("aria-disabled");
    expect(confirm).not.toHaveAttribute("data-unavailable");
    expect(confirm).toHaveAttribute("data-unmet");
    expect(visibleTabbables(dialog())).not.toContain(confirm);
    expect(dialog().querySelector(".cv-confirm__hint")).toHaveTextContent(HOST_RULE);
    expect(confirm).toHaveAccessibleDescription(HOST_RULE);
    // Never main's validity look: no reason row under the footer.
    expect(dialog().querySelector("[data-validity]")).toBeNull();
    t = 5000;
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(page.getByRole("button", { name: "Meet the rule" }));
    expect(confirm).toBeEnabled();
    expect(dialog().querySelector(".cv-confirm__hint")).toBeNull();
    // The guard rearms as Confirm becomes available; past it, the press confirms.
    t = 9000;
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("the host's rule is the hint's fourth step: after the choice, the tick and the typed value", async () => {
    await openRuleHost({
      rung: 3,
      options: [LEAVE, FLATTEN_T2],
      withTick: true,
      typedConfirmValue: "alex",
    });
    const confirm = confirmButton();
    const hint = (): string => dialog().querySelector(".cv-confirm__hint")?.textContent ?? "";
    expect(hint()).toBe(CHOOSE_FIRST);
    await userEvent.click(radio(LEAVE.label));
    expect(hint()).toBe(ACK_FIRST);
    await userEvent.click(tick());
    expect(hint()).toBe("Type alex to confirm");
    await userEvent.type(page.getByRole("textbox", { name: "Type alex to confirm" }), "alex");
    expect(hint()).toBe(HOST_RULE);
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAccessibleDescription(HOST_RULE);
    await userEvent.click(page.getByRole("button", { name: "Meet the rule" }));
    expect(confirm).toBeEnabled();
  });

  it("rung 3 ignores typedReason: natively disabled, the hint carries the typed instruction, no look", async () => {
    const onConfirm = vi.fn();
    await openHost({
      rung: 3,
      options: [LEAVE, FLATTEN_T2],
      withTick: true,
      typedConfirmValue: "alex",
      typedReason: TYPED,
      onConfirm,
    });
    const confirm = confirmButton();
    await userEvent.click(radio(LEAVE.label));
    await userEvent.click(tick());
    expect(confirm).toBeDisabled();
    expect(confirm).not.toHaveAttribute("aria-disabled");
    expect(confirm).not.toHaveAttribute("data-unavailable");
    expect(dialog().querySelector(".cv-confirm__hint")).toHaveTextContent("Type alex to confirm");
    expect(confirm).toHaveAccessibleDescription("Type alex to confirm");
    expect(dialog().querySelector("[data-validity]")).toBeNull();
    expect(page.queryByText(TYPED)).toBeNull();
    t = 5000;
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(polite()).not.toBe(TYPED);
    await userEvent.type(page.getByRole("textbox", { name: "Type alex to confirm" }), "alex");
    expect(confirm).toBeEnabled();
  });

  it("T2 with an unmet ladder: aria-disabled, a Tab stop, no hint, and a press confirms nothing", async () => {
    const onConfirm = vi.fn();
    await openHost({
      rung: 2,
      options: [LEAVE, FLATTEN_T2],
      withTick: true,
      confirmDisabledReason: OWNER_ONLY,
      onConfirm,
    });
    const confirm = confirmButton();
    expect(confirm).toBeEnabled();
    expect(confirm).toHaveAttribute("aria-disabled", "true");
    expect(confirm).toHaveAttribute("data-gated", "");
    expect(confirm).not.toHaveAttribute("data-unmet");
    expect(visibleTabbables(dialog())).toContain(confirm);
    expect(dialog().querySelector(".cv-confirm__hint")).toBeNull();
    expect(confirm).toHaveAccessibleDescription(OWNER_ONLY);
    t = 5000;
    await userEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
    expect(polite()).toBe(OWNER_ONLY);
  });
});

describe("ConfirmDialog (CMP-044): the step-up line and the audit marker", () => {
  const stepUp = (): string | null =>
    dialog().querySelector(".cv-confirm__stepup")?.textContent ?? null;

  it.each([
    [undefined, null],
    ["none", null],
    ["code", "You'll confirm with your password and a code."],
    ["fresh", "This always needs a fresh code."],
  ] as const)("stepUpState %s draws %s", async (state, line) => {
    await openHost({ rung: 1, ...(state === undefined ? {} : { stepUpState: state }) });
    expect(stepUp()).toBe(line);
  });

  it("grace: 'Still trusted for {class} · m:ss', counted on the wall clock", async () => {
    await openHost({
      rung: 2,
      stepUpState: "grace",
      stepUpClassLabel: "user changes",
      stepUpGraceEndsAt: Date.now() + 134_000,
    });
    const line = dialog().querySelector(".cv-confirm__stepup");
    expect(line?.textContent).toMatch(/^Still trusted for user changes · 2:1[34]/);
    expect(line?.querySelector('[data-cmp="CMP-035"]')).not.toBeNull();
  });

  it("grace that has ended reads as the code line", async () => {
    await openHost({
      rung: 2,
      stepUpState: "grace",
      stepUpClassLabel: "user changes",
      stepUpGraceEndsAt: Date.now() - 1,
    });
    expect(stepUp()).toBe("You'll confirm with your password and a code.");
  });

  it("grace without its class or its end is never claimed: the code line, warned", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await openHost({ rung: 2, stepUpState: "grace" });
    expect(stepUp()).toBe("You'll confirm with your password and a code.");
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("grace"));
  });

  it("the marker: each code with its label, joined by '+', the last body line and the dialog's description", async () => {
    await openHost({ rung: 2, stepUpState: "code", auditCodes: CODES });
    const marker = dialog().querySelector(".cv-confirm__marker");
    expect(marker).toHaveTextContent(
      "Recorded in the audit log · Disable user (users.disable) + Session signed out (auth.session_revoked)",
    );
    // The step-up line, then the marker, last before the buttons (D02 §4.1).
    const body = dialog().querySelector(".cv-confirm");
    const lines = [...(body?.children ?? [])].filter(
      (n) => !n.classList.contains("cv-visually-hidden"),
    );
    expect(lines.at(-1)).toBe(marker);
    expect(lines.at(-2)).toBe(dialog().querySelector(".cv-confirm__stepup"));
    expect(dialog()).toHaveAccessibleDescription(
      "alex can't sign in from now on. Recorded in the audit log · Disable user (users.disable) + Session signed out (auth.session_revoked)",
    );
  });

  it("no code: 'Recorded in the audit log' alone", async () => {
    await openHost({ rung: 1, auditCodes: [] });
    expect(dialog().querySelector(".cv-confirm__marker")).toHaveTextContent(
      /^Recorded in the audit log$/,
    );
  });
});
