// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  SegmentedControl,
  type SegmentedControlBaseProps,
  type SegmentedOptions,
} from "../src/components/index.js";
import * as stories from "../src/components/SegmentedControl.stories.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

const REASON = "Owner only";
const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
  { value: "c", label: "Charlie" },
] as const;
const radio = (host: HTMLElement, name: string): HTMLElement =>
  within(host).getByRole("radio", { name });
const radios = (host: HTMLElement): HTMLElement[] => within(host).getAllByRole("radio");
const checkedOf = (host: HTMLElement): string[] =>
  radios(host)
    .filter((r) => r.getAttribute("aria-checked") === "true")
    .map((r) => r.textContent ?? "");
const press = (el: HTMLElement, key: string, mods: object = {}): KeyboardEvent => {
  const event = new KeyboardEvent("keydown", { key, ...mods, bubbles: true, cancelable: true });
  el.dispatchEvent(event);
  return event;
};

/** Keeps the value like a real host does. */
function Host(props: Partial<SegmentedControlBaseProps>): JSX.Element {
  const [value, setValue] = useState(props.value);
  return (
    <SegmentedControl
      aria-label="Order type"
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

describe("SegmentedControl (CMP-003)", () => {
  it("renders a named radiogroup of radios with aria-checked and one tab stop on the checked", async () => {
    const host = await mount(<Host value="b" />);
    const g = within(host).getByRole("radiogroup", { name: "Order type" });
    expect(g.dataset["cmp"]).toBe("CMP-003");
    expect(g.dataset["size"]).toBe("md");
    expect(radios(host).map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
    expect(checkedOf(host)).toEqual(["Bravo"]);
  });

  it("is named by aria-labelledby; the type requires a name and two to six options", async () => {
    const host = await mount(
      <>
        <span id="lbl">Order</span>
        <SegmentedControl aria-labelledby="lbl" options={OPTIONS} />
      </>,
    );
    expect(within(host).getByRole("radiogroup", { name: "Order" })).toBeTruthy();
    // @ts-expect-error neither aria-label nor aria-labelledby: the group would have no name.
    const unnamed = <SegmentedControl options={OPTIONS} />;
    // @ts-expect-error one option is not a choice.
    const one = <SegmentedControl aria-label="x" options={[OPTIONS[0]]} />;
    const seven = (
      <SegmentedControl
        aria-label="x"
        // @ts-expect-error seven options are too many for a segmented control.
        options={[...OPTIONS, ...OPTIONS, OPTIONS[0]]}
      />
    );
    expect([unnamed, one, seven]).toHaveLength(3);
  });

  it("emits size, density and full width as attributes", async () => {
    const host = await mount(<Host size="sm" density="compact" fullWidth />);
    const g = within(host).getByRole("radiogroup");
    expect(g.dataset["size"]).toBe("sm");
    expect(g.dataset["density"]).toBe("compact");
    expect(g.hasAttribute("data-full-width")).toBe(true);
  });

  it("names an icon-only segment by its label and hides the glyph", async () => {
    const options: SegmentedOptions = [
      { value: "asc", label: "Ascending", icon: "arrow-up" },
      { value: "desc", label: "Descending", icon: "arrow-down" },
    ];
    const host = await mount(<Host options={options} value="asc" iconOnly />);
    const asc = radio(host, "Ascending");
    expect(asc.getAttribute("aria-label")).toBe("Ascending");
    expect(asc.textContent).toBe("");
    expect(asc.querySelector("svg")).not.toBeNull();
    expect(asc.querySelector("[aria-hidden='true']")).not.toBeNull();
  });

  it("shows icon and text together unless iconOnly, and falls back to text for an option without an icon", async () => {
    const options: SegmentedOptions = [
      { value: "asc", label: "Ascending", icon: "arrow-up" },
      { value: "none", label: "Unsorted" },
    ];
    const text = await mount(<Host options={options} />);
    expect(radio(text, "Ascending").textContent).toBe("Ascending");
    expect(radio(text, "Ascending").hasAttribute("aria-label")).toBe(false);
    const only = await mount(<Host options={options} iconOnly />);
    expect(radio(only, "Unsorted").textContent).toBe("Unsorted");
  });

  it("arrows move focus and check, wrapping, in both directions", async () => {
    const onChange = fn();
    const host = await mount(<Host value="a" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(radio(host, "Bravo")).toHaveFocus();
    expect(checkedOf(host)).toEqual(["Bravo"]);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect(checkedOf(host)).toEqual(["Alpha"]);
    await userEvent.keyboard("{ArrowUp}");
    expect(checkedOf(host)).toEqual(["Charlie"]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(["b", "c", "a", "c", "b"]);
  });

  it("Home and End jump to the first and last segment and check it; Space checks the focused one", async () => {
    const onChange = fn();
    const host = await mount(<Host value="b" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{End}");
    expect(checkedOf(host)).toEqual(["Charlie"]);
    await userEvent.keyboard("{Home}");
    expect(checkedOf(host)).toEqual(["Alpha"]);
    const bare = await mount(
      <SegmentedControl aria-label="x" options={OPTIONS} onChange={onChange} />,
    );
    radio(bare, "Bravo").focus();
    await userEvent.keyboard("x{Enter}");
    expect(onChange).toHaveBeenCalledTimes(2);
    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenLastCalledWith("b");
  });

  it("does not report the value it already has", async () => {
    const onChange = fn();
    const host = await mount(
      <SegmentedControl aria-label="x" options={OPTIONS} value="a" onChange={onChange} />,
    );
    await userEvent.click(radio(host, "Alpha"));
    await userEvent.keyboard(" ");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("Tab leaves the group in both directions and re-enters on the checked segment", async () => {
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

  it("a click anywhere on the segment checks it and focuses it", async () => {
    const host = await mount(<Host value="a" />);
    await userEvent.click(within(radio(host, "Charlie")).getByText("Charlie"));
    expect(checkedOf(host)).toEqual(["Charlie"]);
    expect(radio(host, "Charlie")).toHaveFocus();
  });

  it("gives the first segment the tab stop when nothing is checked", async () => {
    const host = await mount(<Host />);
    expect(radio(host, "Alpha").tabIndex).toBe(0);
    await userEvent.tab();
    expect(radio(host, "Alpha")).toHaveFocus();
  });

  it("Alt, Ctrl and Meta chords are ignored; Shift acts as the plain key; handled keys never scroll", async () => {
    const onChange = fn();
    const host = await mount(
      <SegmentedControl aria-label="x" options={OPTIONS} value="a" onChange={onChange} />,
    );
    radio(host, "Alpha").focus();
    for (const mod of ["altKey", "ctrlKey", "metaKey"]) {
      for (const key of ["ArrowDown", "ArrowRight", "Home", "End", " "]) {
        expect(press(radio(host, "Alpha"), key, { [mod]: true }).defaultPrevented).toBe(false);
      }
    }
    expect(onChange).not.toHaveBeenCalled();
    for (const key of ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End", " "]) {
      expect(press(radio(host, "Alpha"), key).defaultPrevented, key).toBe(true);
    }
    onChange.mockClear();
    radio(host, "Alpha").focus();
    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("a plain-disabled group has no tab stop, no tabindex, and a click focuses nothing and changes nothing", async () => {
    const onChange = fn();
    const onSubmit = fn((e: { preventDefault: () => void }) => e.preventDefault());
    const host = await mount(
      <form onSubmit={onSubmit}>
        <SegmentedControl aria-label="x" options={OPTIONS} value="a" disabled onChange={onChange} />
      </form>,
    );
    expect(within(host).getByRole("radiogroup").getAttribute("aria-disabled")).toBe("true");
    for (const r of radios(host)) {
      expect(r.hasAttribute("tabindex")).toBe(false);
      expect(r.getAttribute("aria-disabled")).toBe("true");
      expect(press(r, "ArrowDown").defaultPrevented).toBe(false);
    }
    await userEvent.tab();
    await userEvent.click(radio(host, "Bravo"));
    expect(document.activeElement).toBe(document.body);
    await userEvent.keyboard("{ArrowDown} {Enter}");
    expect(onChange).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(checkedOf(host)).toEqual(["Alpha"]);
    expect(host.querySelector("svg")).toBeNull();
  });

  it("a gated group keeps the checked segment focusable with the reason, and nothing changes", async () => {
    const onChange = fn();
    const onSubmit = fn((e: { preventDefault: () => void }) => e.preventDefault());
    const host = await mount(
      <form onSubmit={onSubmit}>
        <SegmentedControl
          aria-label="x"
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
    for (const r of radios(host)) {
      expect(r.getAttribute("aria-disabled")).toBe("true");
      expect(r.hasAttribute("disabled")).toBe(false);
    }
    expect(radios(host).map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
    await userEvent.tab();
    expect(radio(host, "Bravo")).toHaveFocus();
    expect(radio(host, "Bravo")).toHaveAccessibleDescription(REASON);
    expect(radio(host, "Alpha")).not.toHaveAccessibleDescription(REASON);
    await userEvent.keyboard("{ArrowRight}{ArrowLeft}{Home}{End} {Enter}");
    for (const key of ["ArrowRight", "Home", "End", " "]) {
      expect(press(radio(host, "Bravo"), key).defaultPrevented, key).toBe(true);
    }
    await userEvent.click(radio(host, "Charlie"));
    expect(onChange).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(checkedOf(host)).toEqual(["Bravo"]);
    expect(host.querySelectorAll("[data-checked]")).toHaveLength(1);
    // One lock, after the last option and inside the track: never inside a segment (catalogue 15:73).
    expect(host.querySelectorAll("svg")).toHaveLength(1);
    const group = within(host).getByRole("radiogroup");
    const lock = group.querySelector(".cv-segmented__lock");
    expect(lock).not.toBeNull();
    expect(lock?.parentElement).toBe(group);
    expect(group.lastElementChild).toBe(lock);
    expect(lock?.getAttribute("aria-hidden")).toBe("true");
    for (const r of radios(host)) expect(r.querySelector("svg")).toBeNull();
  });

  it("the lock stays after the last option whichever segment is checked, and when none is", async () => {
    for (const value of ["a", "c", undefined]) {
      const host = await mount(
        <SegmentedControl aria-label="x" options={OPTIONS} value={value} disabledReason={REASON} />,
      );
      const group = within(host).getByRole("radiogroup");
      expect(group.lastElementChild?.classList.contains("cv-segmented__lock")).toBe(true);
      expect(group.querySelectorAll(".cv-segmented__lock")).toHaveLength(1);
    }
  });

  it("an ungated group draws no lock", async () => {
    const host = await mount(<Host value="a" />);
    expect(host.querySelector(".cv-segmented__lock")).toBeNull();
  });

  it("icon-only and gated: the name stays the label, the description is the reason, one lock", async () => {
    const options: SegmentedOptions = [
      { value: "asc", label: "Ascending", icon: "arrow-up" },
      { value: "desc", label: "Descending", icon: "arrow-down" },
    ];
    const host = await mount(
      <SegmentedControl
        aria-label="Sort order"
        options={options}
        value="asc"
        iconOnly
        disabledReason={REASON}
      />,
    );
    const asc = radio(host, "Ascending");
    expect(asc).toHaveAccessibleDescription(REASON);
    expect(asc.textContent).toBe("");
    expect(within(host).getByRole("radiogroup")).toHaveAccessibleDescription(REASON);
    expect(host.querySelectorAll(".cv-segmented__lock")).toHaveLength(1);
    expect(host.querySelectorAll("svg")).toHaveLength(3);
    expect(asc.querySelector(".cv-segmented__lock")).toBeNull();
  });

  it("each visible label carries a data-label copy source for the reserved bold width", async () => {
    const host = await mount(<Host value="a" />);
    const labels = [...host.querySelectorAll<HTMLElement>(".cv-segmented__label")];
    expect(labels.map((l) => l.dataset["label"])).toEqual(["Alpha", "Bravo", "Charlie"]);
  });

  it("a pointer press on a refused segment of a gated group sends focus to the tab stop", async () => {
    const host = await mount(
      <SegmentedControl aria-label="x" options={OPTIONS} value="b" disabledReason={REASON} />,
    );
    await userEvent.click(radio(host, "Charlie"));
    expect(radio(host, "Bravo")).toHaveFocus();
    expect(radios(host).map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
    await userEvent.tab({ shift: true });
    expect(radio(host, "Bravo")).not.toHaveFocus();
  });

  it("a gated group with nothing checked keeps the first segment as the tab stop with the reason", async () => {
    const host = await mount(
      <SegmentedControl aria-label="x" options={OPTIONS} disabledReason={REASON} />,
    );
    await userEvent.tab();
    expect(radio(host, "Alpha")).toHaveFocus();
    expect(radio(host, "Alpha")).toHaveAccessibleDescription(REASON);
  });

  it("a whitespace-only reason is no reason, and a reason wins over disabled", async () => {
    const blank = await mount(
      <SegmentedControl aria-label="x" options={OPTIONS} disabledReason="  " />,
    );
    expect(within(blank).getByRole("radiogroup").hasAttribute("aria-disabled")).toBe(false);
    const both = await mount(
      <SegmentedControl
        aria-label="x"
        options={OPTIONS}
        value="a"
        disabled
        disabledReason={REASON}
      />,
    );
    expect(radio(both, "Alpha").tabIndex).toBe(0);
    expect(radio(both, "Alpha")).toHaveAccessibleDescription(REASON);
  });
});

describe("SegmentedControl stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("radio").length).toBeGreaterThan(0);
  });
});

describe("SegmentedControl gated announcement (D09 2.2)", () => {
  it("announces the group reason on a value key or a segment click; nothing when allowed", async () => {
    const onChange = fn();
    await mount(<Host disabledReason={REASON} value="b" onChange={onChange} />);
    await userEvent.tab();
    expect(await politeText()).toBe("");
    await userEvent.keyboard("{ArrowRight}");
    expect(await politeText()).toBe(REASON);
    clearPolite();
    const again = await mount(<Host disabledReason={REASON} value="b" onChange={onChange} />);
    await userEvent.click(within(again).getAllByRole("radio")[0]!);
    expect(await politeText()).toBe(REASON);
    expect(onChange).not.toHaveBeenCalled();
    clearPolite();
    const open = await mount(<Host value="b" onChange={onChange} />);
    await userEvent.click(within(open).getAllByRole("radio")[0]!);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(await politeText()).toBe("");
  });
});
