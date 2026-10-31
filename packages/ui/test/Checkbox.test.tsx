// @vitest-environment jsdom
import { act, type JSX } from "react";
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Checkbox, GatedAnnounceProvider } from "../src/components/index.js";
import * as stories from "../src/components/Checkbox.stories.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

const REASON = "Owner only";
const get = (host: HTMLElement, name = "Agree"): HTMLInputElement =>
  within(host).getByRole("checkbox", { name }) as HTMLInputElement;

describe("Checkbox (CMP-005)", () => {
  it("renders a native checkbox named by its visible label", async () => {
    const host = await mount(<Checkbox label="Agree" />);
    const c = get(host);
    expect(c.type).toBe("checkbox");
    expect(c.checked).toBe(false);
    expect(c).not.toHaveAttribute("aria-checked");
    expect(host.querySelector<HTMLElement>("[data-cmp]")?.dataset["cmp"]).toBe("CMP-005");
    expect(host.querySelector(".cv-checkbox__glyph")).toBeNull();
  });

  it("toggles on Space and label click, not on Enter (uncontrolled)", async () => {
    const onChange = fn();
    const host = await mount(<Checkbox label="Agree" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(get(host).checked).toBe(true);
    await userEvent.keyboard("{Enter}");
    expect(get(host).checked).toBe(true);
    fireEvent.click(within(host).getByText("Agree"));
    expect(onChange.mock.calls).toEqual([[true], [false]]);
  });

  it("controlled: follows `checked`, only emits", async () => {
    const onChange = fn();
    const host = await mount(<Checkbox label="Agree" checked={false} onChange={onChange} />);
    await userEvent.click(get(host));
    expect(onChange).toHaveBeenCalledWith(true);
    expect(get(host).checked).toBe(false);
  });

  it("checked draws the check glyph, decorative", async () => {
    const host = await mount(<Checkbox label="Agree" defaultChecked />);
    expect(host.querySelector(".cv-checkbox__glyph svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(host.querySelector(".cv-checkbox")?.getAttribute("data-state")).toBe("checked");
  });

  it("indeterminate: minus glyph, DOM property set (no aria-checked), next activation emits true", async () => {
    const onChange = fn();
    const host = await mount(<Checkbox label="Agree" indeterminate onChange={onChange} />);
    const c = get(host);
    expect(c).not.toHaveAttribute("aria-checked");
    expect(c).toBePartiallyChecked();
    expect(host.querySelector(".cv-checkbox")?.getAttribute("data-state")).toBe("mixed");
    await userEvent.click(c);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("a held indeterminate prop re-asserts the property after a native click clears it", async () => {
    const host = await mount(<Checkbox label="Agree" indeterminate />);
    const c = get(host);
    await userEvent.click(c);
    expect(c.indeterminate).toBe(true);
  });

  it("a gated mixed box stays mixed after a click and after Space", async () => {
    const host = await mount(<Checkbox label="Agree" indeterminate disabledReason="No" />);
    const c = get(host);
    await userEvent.click(c);
    expect(c.indeterminate).toBe(true);
    c.focus();
    await userEvent.keyboard(" ");
    expect(c.indeterminate).toBe(true);
    expect(c).toBePartiallyChecked();
  });

  it("a mixed box whose consumer holds indeterminate stays mixed after two clicks", async () => {
    const host = await mount(<Checkbox label="Agree" indeterminate />);
    const c = get(host);
    await userEvent.click(c);
    await userEvent.click(c);
    expect(c.indeterminate).toBe(true);
    expect(c).toBePartiallyChecked();
  });

  it("the whole row is the target: the control cell and the row gap toggle, a gated row does not", async () => {
    const onChange = fn();
    const host = await mount(<Checkbox label="Agree" onChange={onChange} />);
    await act(async () =>
      fireEvent.click(host.querySelector(".cv-choice__control") as HTMLElement),
    );
    await act(async () => fireEvent.click(host.querySelector(".cv-choice__target") as HTMLElement));
    expect(onChange.mock.calls).toEqual([[true], [false]]);
    const gated = fn();
    const g = await mount(<Checkbox label="Agree" disabledReason="No" onChange={gated} />);
    await act(async () => fireEvent.click(g.querySelector(".cv-choice__control") as HTMLElement));
    await act(async () => fireEvent.click(g.querySelector(".cv-choice__target") as HTMLElement));
    expect(gated).not.toHaveBeenCalled();
    expect(get(g).checked).toBe(false);
  });

  it("emits data-density on the row", async () => {
    const host = await mount(<Checkbox label="Agree" density="comfortable" />);
    expect(host.querySelector<HTMLElement>(".cv-choice")?.dataset["density"]).toBe("comfortable");
  });

  it("plain disabled uses the native attribute, leaves the Tab order and fires nothing", async () => {
    const onChange = fn();
    const host = await mount(<Checkbox label="Agree" disabled onChange={onChange} />);
    expect(get(host).disabled).toBe(true);
    await userEvent.tab();
    expect(get(host)).not.toHaveFocus();
    await userEvent.click(get(host));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("disabled with a reason: focusable, aria-disabled, described at mount, value cannot change", async () => {
    const onChange = fn();
    const host = await mount(
      <Checkbox
        label="Agree"
        defaultChecked
        disabled
        disabledReason={REASON}
        onChange={onChange}
      />,
    );
    const c = get(host);
    expect(c.disabled).toBe(false);
    expect(c).toHaveAttribute("aria-disabled", "true");
    expect(c).toHaveAccessibleDescription(REASON);
    expect(host.querySelector(".cv-choice__lock svg")?.getAttribute("aria-hidden")).toBe("true");
    await userEvent.tab();
    expect(c).toHaveFocus();
    await userEvent.keyboard(" ");
    await userEvent.click(c);
    fireEvent.click(within(host).getByText("Agree"));
    expect(onChange).not.toHaveBeenCalled();
    expect(c.checked).toBe(true);
  });

  it("renders the reason as plain text; a whitespace-only reason is no reason", async () => {
    const host = await mount(<Checkbox label="Agree" disabledReason="<b>no</b>" />);
    expect(host.querySelector("b")).toBeNull();
    const blank = await mount(<Checkbox label="Agree2" disabledReason="  " />);
    expect(get(blank, "Agree2")).not.toHaveAttribute("aria-disabled");
  });

  it("merges a caller's aria-describedby with the reason", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <Checkbox label="Agree" aria-describedby="help" disabledReason={REASON} />
      </>,
    );
    expect(get(host)).toHaveAccessibleDescription(`Help ${REASON}`);
  });
});

describe("Checkbox stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("checkbox").length).toBeGreaterThan(0);
  });
});

describe("Checkbox gated announcement (D09 2.2)", () => {
  it("announces the reason on a gated click or Space, announces nothing when allowed", async () => {
    const onChange = fn();
    const host = await mount(
      <Checkbox label="Agree" disabledReason={REASON} onChange={onChange} />,
    );
    await userEvent.click(within(host).getByRole("checkbox", { name: "Agree" }));
    expect(await politeText()).toBe(REASON);
    clearPolite();
    await mount(<Checkbox label="Agree" disabledReason={REASON} onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(await politeText()).toBe(REASON);
    expect(onChange).not.toHaveBeenCalled();
    clearPolite();
    const open = await mount(<Checkbox label="Agree" onChange={onChange} />);
    await userEvent.click(within(open).getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(await politeText()).toBe("");
  });
});

// E09-D09 §2.2 rendering 2a with the reason node the host's (a caption under the row, or a read-only panel's one
// notice): E08-S08's ColumnPicker points its locked and read-only boxes at it.
describe("Checkbox disabledReasonId: the reason shown by the host (2a)", () => {
  const Captioned = ({ onChange }: { readonly onChange?: (on: boolean) => void }): JSX.Element => (
    <>
      <Checkbox
        label="Symbol"
        checked
        disabledReason={REASON}
        disabledReasonId="symbol-reason"
        {...(onChange === undefined ? {} : { onChange })}
      />
      <p id="symbol-reason">{REASON}</p>
    </>
  );

  it("is described by the host's node alone: no copy of its own and no echo", async () => {
    const host = await mount(<Captioned />);
    const c = get(host, "Not available Symbol");
    expect(c).toHaveAttribute("aria-disabled", "true");
    expect(c).toHaveAttribute("aria-describedby", "symbol-reason");
    expect(c).toHaveAccessibleDescription(REASON);
    expect(within(host).getAllByText(REASON)).toHaveLength(1);
    expect(document.querySelector('[data-cmp="CMP-016"]')).toBeNull();
  });

  it("its lock leads the label, named Not available, and no lock trails the row", async () => {
    const host = await mount(<Captioned />);
    const label = host.querySelector<HTMLElement>(".cv-choice__label") as HTMLElement;
    const lock = within(label).getByRole("img", { name: "Not available" });
    expect(label.firstElementChild).toContainElement(lock);
    expect(host.querySelectorAll(".cv-choice__lock")).toHaveLength(1);
  });

  it("a press changes nothing and announces the reason once", async () => {
    const onChange = fn();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <Captioned onChange={onChange} />
      </GatedAnnounceProvider>,
    );
    await userEvent.click(get(host, "Not available Symbol"));
    expect(onChange).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[REASON]]);
  });
});
