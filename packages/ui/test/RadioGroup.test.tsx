// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { RadioGroup, type RadioGroupBaseProps } from "../src/components/index.js";
import * as stories from "../src/components/RadioGroup.stories.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

const REASON = "Owner only";
const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
  { value: "c", label: "Charlie" },
];
const radio = (host: HTMLElement, name: string): HTMLElement =>
  within(host).getByRole("radio", { name });
const checkedOf = (host: HTMLElement): string[] =>
  within(host)
    .getAllByRole("radio")
    .filter((r) => r.getAttribute("aria-checked") === "true")
    .map((r) => r.textContent ?? "");

/** Keeps the value like a real host does. */
function Host(props: Partial<RadioGroupBaseProps>): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <RadioGroup
      aria-label="Rule"
      options={OPTIONS}
      {...props}
      value={value}
      onChange={(v) => {
        setValue(v);
        props.onChange?.(v);
      }}
    />
  );
}

describe("RadioGroup (CMP-006)", () => {
  it("renders a named radiogroup of radios with aria-checked and one tab stop on the checked", async () => {
    const host = await mount(<Host value="b" />);
    const g = within(host).getByRole("radiogroup", { name: "Rule" });
    expect(g.dataset["cmp"]).toBe("CMP-006");
    expect(g.dataset["orientation"]).toBe("vertical");
    expect(
      within(host)
        .getAllByRole("radio")
        .map((r) => r.tabIndex),
    ).toEqual([-1, 0, -1]);
    expect(checkedOf(host)).toEqual(["Bravo"]);
  });

  it("is named by aria-labelledby, and the type requires one name", async () => {
    const host = await mount(
      <>
        <span id="lbl">Sizing</span>
        <RadioGroup aria-labelledby="lbl" options={OPTIONS} />
      </>,
    );
    expect(within(host).getByRole("radiogroup", { name: "Sizing" })).toBeTruthy();
    // @ts-expect-error neither aria-label nor aria-labelledby: the group would have no name.
    const unnamed = <RadioGroup options={OPTIONS} />;
    expect(unnamed).toBeTruthy();
  });

  it("gives the first enabled radio the tab stop when none is checked", async () => {
    const host = await mount(
      <Host options={[{ ...OPTIONS[0]!, disabled: true }, OPTIONS[1]!, OPTIONS[2]!]} />,
    );
    expect(radio(host, "Bravo").tabIndex).toBe(0);
    await userEvent.tab();
    expect(radio(host, "Bravo")).toHaveFocus();
  });

  it("emits orientation and density", async () => {
    const host = await mount(<Host orientation="horizontal" density="comfortable" />);
    const g = within(host).getByRole("radiogroup");
    expect(g.dataset["orientation"]).toBe("horizontal");
    expect(g.dataset["density"]).toBe("comfortable");
  });

  it("arrows move focus and check, wrapping, in both orientations", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    expect(radio(host, "Bravo")).toHaveFocus();
    expect(checkedOf(host)).toEqual(["Bravo"]);
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(checkedOf(host)).toEqual(["Alpha"]);
    await userEvent.keyboard("{ArrowUp}");
    expect(checkedOf(host)).toEqual(["Charlie"]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(checkedOf(host)).toEqual(["Bravo"]);
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(["b", "c", "a", "c", "b"]);
  });

  it("Home and End jump to the first and last enabled radio and check it", async () => {
    const host = await mount(<Host value="b" />);
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    expect(checkedOf(host)).toEqual(["Charlie"]);
    await userEvent.keyboard("{Home}");
    expect(checkedOf(host)).toEqual(["Alpha"]);
  });

  it("Space checks the focused radio and ignores other keys", async () => {
    const onChange = fn();
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} onChange={onChange} />,
    );
    radio(host, "Bravo").focus();
    await userEvent.keyboard("x{Enter}");
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("does not report the value it already has", async () => {
    const onChange = fn();
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} value="a" onChange={onChange} />,
    );
    await userEvent.click(radio(host, "Alpha"));
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("Tab leaves the group in both directions", async () => {
    const host = await mount(
      <>
        <button type="button">before</button>
        <Host value="b" />
        <button type="button">after</button>
      </>,
    );
    await userEvent.tab();
    await userEvent.tab();
    expect(radio(host, "Bravo")).toHaveFocus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "after" })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(radio(host, "Bravo")).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(within(host).getByRole("button", { name: "before" })).toHaveFocus();
  });

  it("a click anywhere on the row checks it, and moves focus to it", async () => {
    const host = await mount(<Host value="a" />);
    await userEvent.click(within(radio(host, "Charlie")).getByText("Charlie"));
    expect(checkedOf(host)).toEqual(["Charlie"]);
    expect(radio(host, "Charlie")).toHaveFocus();
  });

  it("skips a plain-disabled option for the arrows and the click", async () => {
    const onChange = fn();
    const options = [OPTIONS[0]!, { ...OPTIONS[1]!, disabled: true }, OPTIONS[2]!];
    const host = await mount(<Host value="a" options={options} onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    expect(checkedOf(host)).toEqual(["Charlie"]);
    await userEvent.click(radio(host, "Bravo"));
    expect(checkedOf(host)).toEqual(["Charlie"]);
    expect(radio(host, "Bravo").getAttribute("aria-disabled")).toBe("true");
    // A plain-disabled row has no tabindex at all: a click cannot focus it and no key reaches it.
    expect(radio(host, "Bravo").hasAttribute("tabindex")).toBe(false);
    expect(radio(host, "Bravo")).not.toHaveFocus();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("clicking a plain-disabled row does not focus it, and no key on it does anything", async () => {
    const onChange = fn();
    const options = [OPTIONS[0]!, { ...OPTIONS[1]!, disabled: true }, OPTIONS[2]!];
    const host = await mount(<Host value="a" options={options} onChange={onChange} />);
    const bravo = radio(host, "Bravo");
    await userEvent.click(bravo);
    expect(bravo).not.toHaveFocus();
    expect(document.activeElement).toBe(document.body);
    for (const key of ["ArrowDown", "ArrowUp", "Home", "End", " ", "Enter"]) {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
      bravo.dispatchEvent(event);
      expect(event.defaultPrevented, key).toBe(false);
    }
    expect(onChange).not.toHaveBeenCalled();
    expect(checkedOf(host)).toEqual(["Alpha"]);
  });

  it("an option with a reason is reached by the arrows, never checked, and describes itself", async () => {
    const onChange = fn();
    const options = [OPTIONS[0]!, { ...OPTIONS[1]!, disabledReason: REASON }, OPTIONS[2]!];
    const host = await mount(<Host value="a" options={options} onChange={onChange} />);
    const locked = radio(host, "Bravo");
    expect(locked.getAttribute("aria-disabled")).toBe("true");
    expect(locked).toHaveAccessibleDescription(REASON);
    expect(locked.querySelector("svg")).not.toBeNull();
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    expect(locked).toHaveFocus();
    expect(checkedOf(host)).toEqual(["Alpha"]);
    // The tab stop follows focus while inside, so Tab leaves instead of landing on the checked radio.
    await userEvent.keyboard(" ");
    await userEvent.click(locked);
    expect(onChange).not.toHaveBeenCalled();
    expect(checkedOf(host)).toEqual(["Alpha"]);
    await userEvent.keyboard("{ArrowDown}");
    expect(checkedOf(host)).toEqual(["Charlie"]);
    // The accessible name is the label alone, never the reason.
    expect(within(host).getByRole("radio", { name: "Bravo" })).toBe(locked);
  });

  it("Tab from a focused option with a reason leaves the group, and re-entry lands on the checked one", async () => {
    const options = [OPTIONS[0]!, { ...OPTIONS[1]!, disabledReason: REASON }, OPTIONS[2]!];
    const host = await mount(
      <>
        <Host value="c" options={options} />
        <button type="button">after</button>
      </>,
    );
    await userEvent.tab();
    expect(radio(host, "Charlie")).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(radio(host, "Bravo")).toHaveFocus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "after" })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(radio(host, "Charlie")).toHaveFocus();
  });

  it("a reason wins over plain disabled on an option", async () => {
    const options = [OPTIONS[0]!, { ...OPTIONS[1]!, disabled: true, disabledReason: REASON }];
    const host = await mount(<Host value="a" options={options} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    expect(radio(host, "Bravo")).toHaveFocus();
    expect(checkedOf(host)).toEqual(["Alpha"]);
  });

  it("a plain-disabled group is out of the Tab order and every radio is aria-disabled", async () => {
    const onChange = fn();
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} value="a" disabled onChange={onChange} />,
    );
    expect(within(host).getByRole("radiogroup").getAttribute("aria-disabled")).toBe("true");
    for (const r of within(host).getAllByRole("radio")) {
      expect(r.hasAttribute("tabindex")).toBe(false);
      expect(r.getAttribute("aria-disabled")).toBe("true");
    }
    await userEvent.tab();
    await userEvent.click(radio(host, "Bravo"));
    expect(host.contains(document.activeElement)).toBe(false);
    expect(host.contains(document.activeElement)).toBe(false);
    await userEvent.click(radio(host, "Bravo"));
    expect(onChange).not.toHaveBeenCalled();
    expect(host.querySelector("svg")).toBeNull();
  });

  it("a gated group keeps the checked radio focusable with the reason, and nothing changes", async () => {
    const onChange = fn();
    const onSubmit = fn((e: { preventDefault: () => void }) => e.preventDefault());
    const host = await mount(
      <form onSubmit={onSubmit}>
        <RadioGroup
          aria-label="Rule"
          options={OPTIONS}
          value="b"
          disabledReason={REASON}
          onChange={onChange}
        />
      </form>,
    );
    const g = within(host).getByRole("radiogroup");
    expect(g.getAttribute("aria-disabled")).toBe("true");
    expect(g).toHaveAccessibleDescription(REASON);
    for (const r of within(host).getAllByRole("radio")) {
      expect(r.getAttribute("aria-disabled")).toBe("true");
      expect(r.hasAttribute("disabled")).toBe(false);
    }
    expect(
      within(host)
        .getAllByRole("radio")
        .map((r) => r.tabIndex),
    ).toEqual([-1, 0, -1]);
    await userEvent.tab();
    expect(radio(host, "Bravo")).toHaveFocus();
    expect(radio(host, "Bravo")).toHaveAccessibleDescription(REASON);
    // Refused keys and clicks: no change, no submit, and the assistive-tech state still matches the visuals.
    await userEvent.keyboard("{ArrowDown}{ArrowUp}{Home}{End} {Enter}");
    await userEvent.click(radio(host, "Charlie"));
    fireEvent.keyDown(radio(host, "Bravo"), { key: "ArrowDown" });
    expect(onChange).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(checkedOf(host)).toEqual(["Bravo"]);
    expect(host.querySelectorAll("[data-checked]")).toHaveLength(1);
    expect(host.querySelectorAll("[data-gated]")).toHaveLength(3);
    expect(host.querySelectorAll("svg")).toHaveLength(1);
  });

  it("a gated group with nothing checked keeps the first radio as the tab stop with the reason", async () => {
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} disabledReason={REASON} />,
    );
    await userEvent.tab();
    expect(radio(host, "Alpha")).toHaveFocus();
    expect(radio(host, "Alpha")).toHaveAccessibleDescription(REASON);
    expect(radio(host, "Bravo")).not.toHaveAccessibleDescription(REASON);
  });

  it("a whitespace-only reason is no reason: the group is plainly disabled or live", async () => {
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} disabledReason="  " />,
    );
    expect(within(host).getByRole("radiogroup").hasAttribute("aria-disabled")).toBe(false);
    expect(host.querySelector("svg")).toBeNull();
  });

  it("a group with only plain-disabled radios has no tab stop", async () => {
    const options = OPTIONS.map((o) => ({ ...o, disabled: true }));
    const host = await mount(<RadioGroup aria-label="Rule" options={options} />);
    for (const r of within(host).getAllByRole("radio"))
      expect(r.hasAttribute("tabindex")).toBe(false);
  });

  it("arrows and Home/End call preventDefault, even when the group refuses them", async () => {
    const host = await mount(<Host value="a" />);
    radio(host, "Alpha").focus();
    for (const key of ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End", " "]) {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
      radio(host, "Alpha").dispatchEvent(event);
      expect(event.defaultPrevented, key).toBe(true);
    }
    const other = await mount(
      <RadioGroup aria-label="Gated" options={OPTIONS} disabledReason={REASON} />,
    );
    const gated = within(other).getAllByRole("radio")[0]!;
    const event = new KeyboardEvent("keydown", {
      key: "ArrowDown",
      bubbles: true,
      cancelable: true,
    });
    gated.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("Alt, Ctrl and Meta chords are ignored: no move, no check, no preventDefault; Shift acts as plain", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    radio(host, "Alpha").focus();
    for (const mod of ["altKey", "ctrlKey", "metaKey"] as const) {
      for (const key of ["ArrowDown", "ArrowRight", "Home", "End", " "]) {
        const event = new KeyboardEvent("keydown", {
          key,
          [mod]: true,
          bubbles: true,
          cancelable: true,
        });
        radio(host, "Alpha").dispatchEvent(event);
        expect(event.defaultPrevented, `${mod}+${key}`).toBe(false);
      }
    }
    expect(onChange).not.toHaveBeenCalled();
    expect(radio(host, "Alpha")).toHaveFocus();
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
    expect(checkedOf(host)).toEqual(["Bravo"]);
  });

  it("Home and End reach a locked first or last option without checking it", async () => {
    const onChange = fn();
    const options = [
      { ...OPTIONS[0]!, disabledReason: REASON },
      OPTIONS[1]!,
      { ...OPTIONS[2]!, disabledReason: REASON },
    ];
    const host = await mount(<Host value="b" options={options} onChange={onChange} />);
    radio(host, "Bravo").focus();
    await userEvent.keyboard("{Home}");
    expect(radio(host, "Alpha")).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(radio(host, "Charlie")).toHaveFocus();
    expect(checkedOf(host)).toEqual(["Bravo"]);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("a click on a refused row in a gated group does not move the tab stop off the checked radio", async () => {
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} value="b" disabledReason={REASON} />,
    );
    await userEvent.click(radio(host, "Charlie"));
    expect(radio(host, "Charlie")).toHaveFocus();
    expect(
      within(host)
        .getAllByRole("radio")
        .map((r) => r.tabIndex),
    ).toEqual([-1, 0, -1]);
  });

  it("a gated group draws one lock, after the checked option", async () => {
    const host = await mount(
      <RadioGroup aria-label="Rule" options={OPTIONS} value="b" disabledReason={REASON} />,
    );
    expect(host.querySelectorAll("svg")).toHaveLength(1);
    expect(radio(host, "Bravo").querySelector("svg")).not.toBeNull();
  });

  it("a one-radio group stays checked when its arrow wraps onto itself", async () => {
    const onChange = fn();
    const host = await mount(
      <RadioGroup aria-label="Rule" options={[OPTIONS[0]!]} value="a" onChange={onChange} />,
    );
    await userEvent.tab();
    await userEvent.keyboard("{ArrowDown}");
    expect(radio(host, "Alpha")).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("works without onChange and releases focus bookkeeping on unmount", async () => {
    const host = await mount(<RadioGroup aria-label="Rule" options={OPTIONS} />);
    await userEvent.click(radio(host, "Bravo"));
    await userEvent.keyboard("{ArrowDown}");
    expect(checkedOf(host)).toEqual([]);
  });
});

describe("RadioGroup stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("radio").length).toBeGreaterThan(0);
  });
});

describe("RadioGroup gated announcement (D09 2.2)", () => {
  it("announces the group reason on a value key, Space or a row click; nothing when allowed", async () => {
    const onChange = fn();
    const host = await mount(<Host disabledReason={REASON} value="b" onChange={onChange} />);
    await userEvent.tab();
    expect(await politeText()).toBe("");
    await userEvent.keyboard("{ArrowRight}");
    expect(await politeText()).toBe(REASON);
    clearPolite();
    const again = await mount(<Host disabledReason={REASON} value="b" onChange={onChange} />);
    await userEvent.click(within(again).getAllByRole("radio")[0]!);
    expect(await politeText()).toBe(REASON);
    expect(onChange).not.toHaveBeenCalled();
    expect(host).toBeDefined();
    clearPolite();
    const open = await mount(<Host value="b" onChange={onChange} />);
    await userEvent.click(within(open).getAllByRole("radio")[0]!);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(await politeText()).toBe("");
  });
});
