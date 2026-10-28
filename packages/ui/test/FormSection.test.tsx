// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type FormEvent, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import { Button, FormField, FormSection, TextInput } from "../src/components/index.js";
import * as stories from "../src/components/FormSection.stories.js";
import { mount } from "./theme/mount.js";

const TITLE = "Default SL/TP offsets";
const DESCRIPTION = "Applied to new orders.";
const REASON = "Your role can't change settings.";
const ERROR = "Enter an offset.";

const TwoFields = (): JSX.Element => (
  <>
    <FormField label="Stop-loss offset" help="Ticks from entry.">
      <TextInput defaultValue="40" />
    </FormField>
    <FormField label="Take-profit offset">
      <TextInput defaultValue="80" />
    </FormField>
  </>
);

describe("FormSection (CMP-065)", () => {
  it("is a fieldset group named by the h3 inside its legend and described by the description", async () => {
    const host = await mount(
      <FormSection title={TITLE} description={DESCRIPTION}>
        <TwoFields />
      </FormSection>,
    );
    const group = within(host).getByRole("group", { name: TITLE });
    expect(group.tagName).toBe("FIELDSET");
    expect(group).toHaveAccessibleDescription(DESCRIPTION);
    const heading = within(host).getByRole("heading", { level: 3, name: TITLE });
    expect(heading.closest("legend")).not.toBeNull();
    expect(within(host).queryByRole("button")).toBeNull();
    expect(group).toHaveAttribute("data-cmp", "CMP-065");
  });

  it("takes headingLevel 2 and 4", async () => {
    const host = await mount(
      <>
        <FormSection title="Two" headingLevel={2}>
          <TwoFields />
        </FormSection>
        <FormSection title="Four" headingLevel={4}>
          <TwoFields />
        </FormSection>
      </>,
    );
    expect(within(host).getByRole("heading", { level: 2, name: "Two" })).toBeInTheDocument();
    expect(within(host).getByRole("heading", { level: 4, name: "Four" })).toBeInTheDocument();
  });

  it("collapsible: a disclosure button inside the heading toggles the body, and focus stays", async () => {
    const onOpenChange = vi.fn();
    const host = await mount(
      <FormSection title={TITLE} collapsible onOpenChange={onOpenChange}>
        <TwoFields />
      </FormSection>,
    );
    const toggle = within(host).getByRole("button", { name: TITLE });
    expect(toggle.closest("h3")).not.toBeNull();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const body = host.ownerDocument.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(body).not.toBeNull();
    expect(body).toBeVisible();
    toggle.focus();
    await userEvent.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    expect(body).not.toBeVisible();
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    await userEvent.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(onOpenChange).toHaveBeenLastCalledWith(true);
  });

  it("collapsed fields leave the Tab order", async () => {
    const host = await mount(
      <>
        <FormSection title={TITLE} collapsible defaultOpen={false}>
          <TwoFields />
        </FormSection>
        <button type="button">After</button>
      </>,
    );
    const toggle = within(host).getByRole("button", { name: TITLE });
    toggle.focus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "After" })).toHaveFocus();
    expect(within(host).queryAllByRole("textbox")).toHaveLength(0);
  });

  it("follows a controlled open prop", async () => {
    const host = await mount(
      <FormSection title={TITLE} collapsible open={false}>
        <TwoFields />
      </FormSection>,
    );
    const toggle = within(host).getByRole("button", { name: TITLE });
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("errors within: a collapsed section counts the invalid FormFields, as the button's description", async () => {
    const host = await mount(
      <FormSection title={TITLE} collapsible defaultOpen={false}>
        <FormField label="A" error={ERROR}>
          <TextInput />
        </FormField>
        <FormField label="B" error={ERROR}>
          <TextInput />
        </FormField>
        <FormField label="C">
          <TextInput />
        </FormField>
      </FormSection>,
    );
    const toggle = within(host).getByRole("button", { name: TITLE });
    expect(toggle).toHaveAccessibleDescription("2 problems");
    // The count is not part of the group's name.
    expect(within(host).getByRole("group", { name: TITLE })).toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).not.toHaveAttribute("aria-describedby");
    expect(within(host).queryByText("2 problems")).toBeNull();
  });

  it("errorCount overrides the count, in the singular too", async () => {
    const host = await mount(
      <FormSection title={TITLE} collapsible defaultOpen={false} errorCount={1}>
        <TwoFields />
      </FormSection>,
    );
    expect(within(host).getByRole("button", { name: TITLE })).toHaveAccessibleDescription(
      "1 problem",
    );
  });

  it("plain disabled: a disabled fieldset; the fields are disabled and the toggle still works", async () => {
    const host = await mount(
      <FormSection title={TITLE} collapsible disabled>
        <TwoFields />
      </FormSection>,
    );
    expect(within(host).getByRole("group", { name: TITLE })).toBeDisabled();
    for (const field of within(host).getAllByRole("textbox")) expect(field).toBeDisabled();
    const toggle = within(host).getByRole("button", { name: TITLE });
    expect(toggle).toBeEnabled();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("T2: one notice under the heading that every gated field points at; no reason line per field", async () => {
    const host = await mount(
      <FormSection title={TITLE} description={DESCRIPTION} disabledReason={REASON}>
        <TwoFields />
      </FormSection>,
    );
    const notices = within(host).getAllByText(REASON);
    expect(notices).toHaveLength(1);
    const noticeId = notices[0]?.id ?? "";
    expect(noticeId).not.toBe("");
    const fields = within(host).getAllByRole("textbox");
    expect(fields).toHaveLength(2);
    for (const field of fields) {
      expect(field).toHaveAttribute("aria-disabled", "true");
      expect(field).toHaveAttribute("readonly");
      expect(field).not.toBeDisabled();
      expect(field).toHaveAttribute("aria-describedby", noticeId);
    }
    expect(within(host).getAllByRole("img", { name: "Not available" })).toHaveLength(2);
    // The help line stays visible but leaves the description while gated.
    expect(within(host).getByText("Ticks from entry.")).toBeVisible();
  });

  it("T2: a gated field never validates, so it never shows an error", async () => {
    const host = await mount(
      <FormSection title={TITLE} disabledReason={REASON}>
        <FormField label="A" error={ERROR}>
          <TextInput />
        </FormField>
      </FormSection>,
    );
    expect(within(host).getByRole("textbox")).not.toHaveAttribute("aria-invalid");
    expect(within(host).queryByText(ERROR)).toBeNull();
  });

  it("a whitespace-only reason is no reason", async () => {
    const host = await mount(
      <FormSection title={TITLE} disabledReason="  ">
        <TwoFields />
      </FormSection>,
    );
    for (const field of within(host).getAllByRole("textbox")) {
      expect(field).not.toHaveAttribute("aria-disabled");
    }
  });
});

const SubmitHost = (): JSX.Element => {
  const [error, setError] = useState<string | undefined>(undefined);
  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setError(ERROR);
  };
  return (
    <form noValidate onSubmit={submit}>
      <FormSection title="Advanced" collapsible defaultOpen={false}>
        <FormField label="Trailing offset" error={error}>
          <TextInput />
        </FormField>
      </FormSection>
      <Button type="submit">Save</Button>
    </form>
  );
};

describe("FormSection opens on submit (CMP-065, G14)", () => {
  it("opens around an invalid field after a submit, and focus reaches the field", async () => {
    const host = await mount(<SubmitHost />);
    const toggle = within(host).getByRole("button", { name: "Advanced" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(within(host).getByRole("button", { name: "Save" }));
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const field = within(host).getByRole("textbox", { name: "Trailing offset" });
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveFocus();
  });

  it("does not open on a submit with no invalid field, nor on a later error once the user toggles", async () => {
    const Host = (): JSX.Element => {
      const [error, setError] = useState<string | undefined>(undefined);
      return (
        <form noValidate onSubmit={(event) => event.preventDefault()}>
          <FormSection title="Advanced" collapsible defaultOpen={false}>
            <FormField label="Trailing offset" error={error}>
              <TextInput />
            </FormField>
          </FormSection>
          <Button type="submit">Save</Button>
          <Button onClick={() => setError(ERROR)}>Fail</Button>
        </form>
      );
    };
    const host = await mount(<Host />);
    const toggle = within(host).getByRole("button", { name: "Advanced" });
    await userEvent.click(within(host).getByRole("button", { name: "Save" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    await userEvent.click(toggle);
    await userEvent.click(within(host).getByRole("button", { name: "Fail" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAccessibleDescription("1 problem");
  });

  it("opens at once on a native constraint failure inside it", async () => {
    const host = await mount(
      <form onSubmit={(event) => event.preventDefault()}>
        <FormSection title="Advanced" collapsible defaultOpen={false}>
          <FormField label="Trailing offset">
            <TextInput required defaultValue="" />
          </FormField>
        </FormSection>
      </form>,
    );
    const form = host.querySelector("form");
    await act(async () => {
      form?.reportValidity();
    });
    expect(within(host).getByRole("button", { name: "Advanced" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("an expanded section stays as it is on a submit", async () => {
    const onOpenChange = vi.fn();
    const host = await mount(
      <form noValidate onSubmit={(event) => event.preventDefault()}>
        <FormSection title="Advanced" collapsible onOpenChange={onOpenChange}>
          <FormField label="Trailing offset" error={ERROR}>
            <TextInput />
          </FormField>
        </FormSection>
        <Button type="submit">Save</Button>
      </form>,
    );
    await userEvent.click(within(host).getByRole("button", { name: "Save" }));
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});

describe("FormSection stories", () => {
  const composed = composeStories(stories);
  it.each(Object.entries(composed))("%s renders a section", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-065"]').length).toBeGreaterThan(0);
  });
});
