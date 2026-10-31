// @vitest-environment jsdom
import { act } from "react";
import { composeStories } from "@storybook/react-vite";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Toggle } from "../src/components/index.js";
import * as stories from "../src/components/Toggle.stories.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

const REASON = "Owner only";
const get = (host: HTMLElement, name = "Arm"): HTMLButtonElement =>
  within(host).getByRole("switch", { name }) as HTMLButtonElement;

describe("Toggle (CMP-004)", () => {
  it("renders a native button with role switch, off, named by its visible label", async () => {
    const host = await mount(<Toggle label="Arm" />);
    const s = get(host);
    expect(s.tagName).toBe("BUTTON");
    expect(s).toHaveAttribute("aria-checked", "false");
    expect(host.querySelector<HTMLElement>("[data-cmp]")?.dataset["cmp"]).toBe("CMP-004");
  });

  it("emits the opposite value on click, Space and Enter (uncontrolled)", async () => {
    const onChange = fn();
    const host = await mount(<Toggle label="Arm" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(get(host)).toHaveAttribute("aria-checked", "true");
    await userEvent.keyboard("{Enter}");
    await userEvent.click(get(host));
    expect(onChange.mock.calls).toEqual([[true], [false], [true]]);
  });

  it("a click on the label toggles the switch", async () => {
    const onChange = fn();
    const host = await mount(<Toggle label="Arm" onChange={onChange} />);
    fireEvent.click(within(host).getByText("Arm"));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("the whole row is the target: the control cell and the row gap toggle, a gated row does not", async () => {
    const onChange = fn();
    const host = await mount(<Toggle label="Arm" onChange={onChange} />);
    await act(async () =>
      fireEvent.click(host.querySelector(".cv-choice__control") as HTMLElement),
    );
    await act(async () => fireEvent.click(host.querySelector(".cv-choice__target") as HTMLElement));
    expect(onChange.mock.calls).toEqual([[true], [false]]);
    const gated = fn();
    const g = await mount(<Toggle label="Arm" disabledReason="No" onChange={gated} />);
    await act(async () => fireEvent.click(g.querySelector(".cv-choice__control") as HTMLElement));
    await act(async () => fireEvent.click(g.querySelector(".cv-choice__target") as HTMLElement));
    expect(gated).not.toHaveBeenCalled();
    expect(get(g)).toHaveAttribute("aria-checked", "false");
  });

  it("controlled: follows `checked`, only emits", async () => {
    const onChange = fn();
    const host = await mount(<Toggle label="Arm" checked={false} onChange={onChange} />);
    await userEvent.click(get(host));
    expect(onChange).toHaveBeenCalledWith(true);
    expect(get(host)).toHaveAttribute("aria-checked", "false");
  });

  it("labelPosition left puts the label before the track; hidden names the switch by aria-label", async () => {
    const left = await mount(<Toggle label="Arm" labelPosition="left" />);
    const row = left.querySelector(".cv-choice");
    expect(row?.firstElementChild?.tagName).toBe("LABEL");
    const hidden = await mount(<Toggle label="Quiet" labelPosition="hidden" />);
    expect(get(hidden, "Quiet")).toHaveAttribute("aria-label", "Quiet");
    expect(hidden.querySelector("label")).toBeNull();
  });

  it("critical leads with a decorative warning glyph and marks the row", async () => {
    const host = await mount(<Toggle label="Arm" critical />);
    expect(host.querySelector(".cv-choice")?.hasAttribute("data-critical")).toBe(true);
    expect(host.querySelector("label svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(get(host)).toHaveAccessibleName("Arm");
  });

  it("emits data-density on the row", async () => {
    const host = await mount(<Toggle label="Arm" density="compact" />);
    expect(host.querySelector<HTMLElement>(".cv-choice")?.dataset["density"]).toBe("compact");
  });

  it("plain disabled uses the native attribute, leaves the Tab order and fires nothing", async () => {
    const onChange = fn();
    const host = await mount(<Toggle label="Arm" disabled onChange={onChange} />);
    expect(get(host).disabled).toBe(true);
    await userEvent.tab();
    expect(get(host)).not.toHaveFocus();
    fireEvent.click(get(host));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("disabled with a reason: focusable, aria-disabled, reason described at mount, no change", async () => {
    const onChange = fn();
    const host = await mount(
      <Toggle label="Arm" defaultChecked disabled disabledReason={REASON} onChange={onChange} />,
    );
    const s = get(host);
    expect(s.disabled).toBe(false);
    expect(s).toHaveAttribute("aria-disabled", "true");
    expect(s).toHaveAccessibleDescription(REASON);
    expect(host.querySelector(".cv-choice__lock svg")?.getAttribute("aria-hidden")).toBe("true");
    await userEvent.tab();
    expect(s).toHaveFocus();
    await userEvent.keyboard("{Enter} ");
    await userEvent.click(s);
    expect(onChange).not.toHaveBeenCalled();
    expect(s).toHaveAttribute("aria-checked", "true");
  });

  it("renders the reason as plain text; a whitespace-only reason is no reason", async () => {
    const host = await mount(<Toggle label="Arm" disabledReason="<b>no</b>" />);
    expect(host.querySelector("b")).toBeNull();
    const blank = await mount(<Toggle label="Arm2" disabledReason="  " />);
    expect(get(blank, "Arm2")).not.toHaveAttribute("aria-disabled");
  });

  it("merges a caller's aria-describedby with the reason", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <Toggle label="Arm" aria-describedby="help" disabledReason={REASON} />
      </>,
    );
    expect(get(host)).toHaveAccessibleDescription(`Help ${REASON}`);
  });
});

describe("Toggle stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("switch").length).toBeGreaterThan(0);
  });
});

describe("Toggle gated announcement (D09 2.2)", () => {
  it("announces the reason on a gated click or Space, announces nothing when allowed", async () => {
    const onChange = fn();
    const host = await mount(<Toggle label="Arm" disabledReason={REASON} onChange={onChange} />);
    const t = within(host).getByRole("switch", { name: "Arm" });
    await userEvent.click(t);
    expect(await politeText()).toBe(REASON);
    clearPolite();
    const g2 = await mount(<Toggle label="Arm" disabledReason={REASON} onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard(" ");
    expect(await politeText()).toBe(REASON);
    expect(within(g2).getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(onChange).not.toHaveBeenCalled();
    clearPolite();
    const open = await mount(<Toggle label="Arm" onChange={onChange} />);
    await userEvent.click(within(open).getByRole("switch"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(await politeText()).toBe("");
  });
});
