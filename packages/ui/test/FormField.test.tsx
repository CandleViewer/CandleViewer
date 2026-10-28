// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { FormField, NumericStepperInput, Select, TextInput } from "../src/components/index.js";
import * as stories from "../src/components/FormField.stories.js";
import { mount } from "./theme/mount.js";

const ERROR = "Enter your username.";
const HELP = "Letters, digits and underscores.";
const REASON = "Your role can't change settings.";
const noop = (): void => undefined;
const options = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
];
const ids = (el: Element, attr: string): string[] => (el.getAttribute(attr) ?? "").split(" ");

describe("FormField (CMP-040)", () => {
  // Gherkin "Form field wires label, help and error".
  it("wires the label, the help and the error to the control", async () => {
    const host = await mount(
      <FormField label="Username" help={HELP} error={ERROR}>
        <TextInput defaultValue="" placeholder="e.g. trader_01" />
      </FormField>,
    );
    const field = within(host).getByRole("textbox", { name: "Username" });
    const label = within(host).getByText("Username");
    expect(label.tagName).toBe("LABEL");
    expect(label).toHaveAttribute("for", field.id);
    expect(field).toHaveAttribute("aria-invalid", "true");
    const [errorId, helpId] = ids(field, "aria-describedby");
    expect(host.ownerDocument.getElementById(errorId ?? "")).toHaveTextContent(ERROR);
    expect(host.ownerDocument.getElementById(helpId ?? "")).toHaveTextContent(HELP);
    expect(field).toHaveAccessibleDescription(`${ERROR} ${HELP}`);
    expect(host.querySelector("[data-cmp]")?.getAttribute("data-cmp")).toBe("CMP-040");
  });

  it("keeps the label when a value is typed: the placeholder is never the name", async () => {
    const host = await mount(
      <FormField label="Username">
        <TextInput placeholder="e.g. trader_01" />
      </FormField>,
    );
    const field = within(host).getByRole("textbox", { name: "Username" });
    await userEvent.type(field, "abc");
    expect(within(host).getByText("Username")).toBeVisible();
    expect(field).toHaveAccessibleName("Username");
  });

  it("pre-renders one polite, atomic error node and renders each message once", async () => {
    const Host = (): JSX.Element => {
      const [error, setError] = useState<string | undefined>(undefined);
      return (
        <>
          <FormField label="Username" error={error}>
            <TextInput onBlur={() => setError(ERROR)} />
          </FormField>
          <button type="button">Next</button>
        </>
      );
    };
    const host = await mount(<Host />);
    const field = within(host).getByRole("textbox");
    const errorId = ids(field, "aria-describedby")[0] ?? "";
    const node = host.ownerDocument.getElementById(errorId);
    expect(node).toHaveAttribute("aria-live", "polite");
    expect(node).toHaveAttribute("aria-atomic", "true");
    expect(node).toBeEmptyDOMElement();
    expect(field).not.toHaveAttribute("aria-invalid");
    await userEvent.click(field);
    await userEvent.tab();
    // The same node, filled: a swap, not a new region.
    expect(host.ownerDocument.getElementById(errorId)).toBe(node);
    expect(node).toHaveTextContent(ERROR);
    expect(within(host).getAllByText(ERROR)).toHaveLength(1);
    expect(host.querySelectorAll("[aria-live]")).toHaveLength(1);
  });

  it("sets aria-required for required and draws no asterisk", async () => {
    const host = await mount(
      <FormField label="Username" required>
        <TextInput />
      </FormField>,
    );
    expect(within(host).getByRole("textbox")).toHaveAttribute("aria-required", "true");
    expect(host).not.toHaveTextContent("*");
  });

  it("names an optional field with its marker", async () => {
    const host = await mount(
      <FormField label="Display name" optional>
        <TextInput />
      </FormField>,
    );
    expect(within(host).getByRole("textbox")).toHaveAccessibleName("Display name (optional)");
  });

  it("T2: the reason alone describes the control, once, and the field never validates", async () => {
    const host = await mount(
      <FormField label="Username" help={HELP} error={ERROR} disabledReason={REASON}>
        <TextInput defaultValue="trader_01" />
      </FormField>,
    );
    const field = within(host).getByRole("textbox", { name: "Username" });
    expect(field).toHaveAttribute("aria-disabled", "true");
    expect(field).toHaveAttribute("readonly");
    expect(field).not.toHaveAttribute("disabled");
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(field).toHaveAccessibleDescription(REASON);
    expect(within(host).getAllByText(REASON)).toHaveLength(1);
    expect(within(host).queryByText(ERROR)).toBeNull();
    // The help leaves the chain; its line stays visible.
    expect(within(host).getByText(HELP)).toBeVisible();
    expect(within(host).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    await userEvent.tab();
    expect(field).toHaveFocus();
    await userEvent.keyboard("x");
    expect(field).toHaveValue("trader_01");
    expect(within(host).getByRole("status")).toHaveTextContent(REASON);
  });

  it("plain disabled disables the control natively and dims the field", async () => {
    const host = await mount(
      <FormField label="Username" disabled>
        <TextInput />
      </FormField>,
    );
    expect(within(host).getByRole("textbox")).toBeDisabled();
    expect(host.querySelector(".cv-formfield")).toHaveAttribute("data-disabled");
  });

  it("names a Select through aria-labelledby, and a label press focuses it", async () => {
    const host = await mount(
      <FormField label="Order type" help={HELP} error={ERROR} required>
        <Select options={options} value="a" onChange={noop} />
      </FormField>,
    );
    const combo = within(host).getByRole("combobox", { name: "Order type" });
    const label = within(host).getByText("Order type");
    expect(combo).toHaveAttribute("aria-labelledby", label.id);
    expect(label).not.toHaveAttribute("for");
    expect(combo).toHaveAttribute("aria-invalid", "true");
    expect(combo).toHaveAttribute("aria-required", "true");
    expect(combo).toHaveAccessibleDescription(`${ERROR} ${HELP}`);
    expect(within(host).getAllByText(ERROR)).toHaveLength(1);
    await userEvent.click(label);
    expect(combo).toHaveFocus();
  });

  it("a host's labelId names a child it wires itself", async () => {
    const host = await mount(
      <FormField label="Mode" labelId="mode-label">
        <div role="radiogroup" aria-labelledby="mode-label" />
      </FormField>,
    );
    expect(within(host).getByRole("radiogroup")).toHaveAccessibleName("Mode");
  });

  it("a stepper's parse error renders once, in the field's line", async () => {
    const host = await mount(
      <FormField label="Leverage" help={HELP}>
        <NumericStepperInput
          label="Leverage"
          value={10}
          max={100}
          step={1}
          precision={0}
          onChange={noop}
        />
      </FormField>,
    );
    const spin = within(host).getByRole("spinbutton", { name: "Leverage" });
    expect(spin).not.toHaveAttribute("aria-label");
    await userEvent.clear(spin);
    await userEvent.type(spin, "500");
    await userEvent.tab();
    expect(spin).toHaveAttribute("aria-invalid", "true");
    expect(within(host).getAllByText("Maximum 100")).toHaveLength(1);
    // Error, help, then the stepper's own (empty) rounding note.
    expect(spin).toHaveAccessibleDescription(/^Maximum 100 Letters, digits and underscores\.\s?$/);
    expect(within(host).getByRole("button", { name: "Increase Leverage" })).toBeInTheDocument();
  });

  it("a field reason gates the stepper's buttons too", async () => {
    const host = await mount(
      <FormField label="Leverage" disabledReason={REASON}>
        <NumericStepperInput label="Leverage" value={10} step={1} precision={0} onChange={noop} />
      </FormField>,
    );
    const up = within(host).getByRole("button", { name: "Increase Leverage" });
    expect(up).toHaveAttribute("aria-disabled", "true");
    expect(up).toHaveAccessibleDescription(REASON);
    expect(within(host).getAllByText(REASON)).toHaveLength(1);
  });

  it("a control id given through htmlFor is the label's target", async () => {
    const host = await mount(
      <FormField label="Username" htmlFor="user">
        <TextInput />
      </FormField>,
    );
    expect(within(host).getByRole("textbox")).toHaveAttribute("id", "user");
  });

  it("the field's id wins over a text input's own, so the label still names it", async () => {
    const host = await mount(
      <FormField label="Username">
        <TextInput id="mine" />
      </FormField>,
    );
    const field = within(host).getByRole("textbox", { name: "Username" });
    expect(field).not.toHaveAttribute("id", "mine");
    expect(within(host).getByText("Username")).toHaveAttribute("for", field.id);
  });

  it("the field's id wins over a stepper's own, so the label still names it", async () => {
    const host = await mount(
      <FormField label="Leverage">
        <NumericStepperInput
          id="mine"
          label="Leverage"
          value={10}
          step={1}
          precision={0}
          onChange={noop}
        />
      </FormField>,
    );
    const spin = within(host).getByRole("spinbutton", { name: "Leverage" });
    expect(spin).not.toHaveAttribute("id", "mine");
    expect(within(host).getByText("Leverage")).toHaveAttribute("for", spin.id);
  });

  it("T2 suppresses an atom's own invalid verdict and message", async () => {
    const host = await mount(
      <FormField label="Username" disabledReason={REASON}>
        <TextInput invalid errorMessage={ERROR} defaultValue="trader_01" />
      </FormField>,
    );
    const field = within(host).getByRole("textbox", { name: "Username" });
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(field).toHaveAccessibleDescription(REASON);
    expect(within(host).queryByText(ERROR)).toBeNull();
  });

  it("a Select's own aria-label names it inside a field; the label stays unlinked", async () => {
    const host = await mount(
      <FormField label="Order type">
        <Select aria-label="Type of order" options={options} value="a" onChange={noop} />
      </FormField>,
    );
    const combo = within(host).getByRole("combobox", { name: "Type of order" });
    expect(combo).not.toHaveAttribute("aria-labelledby");
    expect(within(host).getByText("Order type")).not.toHaveAttribute("for");
  });

  it("a plain-disabled field disables a Select and keeps it named", async () => {
    const host = await mount(
      <FormField label="Order type" disabled>
        <Select options={options} value="a" onChange={noop} />
      </FormField>,
    );
    const combo = within(host).getByRole("combobox", { name: "Order type" });
    expect(combo).toHaveAttribute("aria-disabled", "true");
    expect(combo).not.toHaveAttribute("tabindex");
  });

  it("inline layout marks the root and carries the host's label column width", async () => {
    const host = await mount(
      <FormField label="Qty" layout="inline" labelWidth="56px">
        <TextInput />
      </FormField>,
    );
    const root = host.querySelector(".cv-formfield") as HTMLElement;
    expect(root).toHaveAttribute("data-layout", "inline");
    expect(root.style.getPropertyValue("--cv-formfield-label-width")).toBe("56px");
  });

  it("outside a field the atoms keep their own lines", async () => {
    const host = await mount(
      <TextInput aria-label="Solo" invalid errorMessage={ERROR} disabledReason={REASON} />,
    );
    const field = within(host).getByRole("textbox");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(REASON);
    expect(within(host).getByText(ERROR)).toBeInTheDocument();
  });
});

describe("FormField stories", () => {
  const composed = composeStories(stories);
  it.each(Object.entries(composed))("%s renders a labelled field", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-040"]').length).toBeGreaterThan(0);
  });
});
