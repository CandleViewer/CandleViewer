import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type FormEvent, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { Button } from "./Button.js";
import { FormField } from "./FormField.js";
import { FormSection } from "./FormSection.js";
import { TextInput } from "./TextInput.js";

const TITLE = "Default SL/TP offsets";
const DESCRIPTION = "Applied to new orders when the ticket leaves them blank.";
const REASON = "Your role can't change settings.";

const Fields = (): JSX.Element => (
  <>
    <FormField label="Stop-loss offset" help="Ticks from the entry price.">
      <TextInput defaultValue="40" />
    </FormField>
    <FormField label="Take-profit offset">
      <TextInput defaultValue="80" />
    </FormField>
  </>
);

/** Theme and density come from the toolbars; every state below renders at each of the 3 x 2 combinations. */
const meta: Meta<typeof FormSection> = {
  title: "Molecules/FormSection",
  component: FormSection,
  args: { title: TITLE, description: DESCRIPTION, children: <Fields /> },
  decorators: [
    (Story) => (
      <div style={{ width: "24rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof FormSection>;

/** A group named by its legend's h3; the description is the group's description. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const group = canvas.getByRole("group", { name: TITLE });
    await expect(group).toHaveAccessibleDescription(DESCRIPTION);
    await expect(canvas.getByRole("heading", { level: 3, name: TITLE })).toBeVisible();
  },
};

export const HeadingLevel2: Story = {
  args: { headingLevel: 2 },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("heading", { level: 2 })).toBeVisible();
  },
};

/** Collapsible, expanded: the APG Disclosure button inside the heading; Enter toggles and focus stays. */
export const Collapsible: Story = {
  args: { collapsible: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("button", { name: TITLE });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    toggle.focus();
    await userEvent.keyboard("{Enter}");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(toggle).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
  },
};

/** Collapsed: the fields leave the layout and the Tab order. */
export const Collapsed: Story = {
  args: { collapsible: true, defaultOpen: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = canvas.getByRole("button", { name: TITLE });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByRole("textbox")).toBeNull();
    toggle.focus();
    await userEvent.tab();
    await expect(toggle).not.toHaveFocus();
    await expect(canvasElement.contains(canvasElement.ownerDocument.activeElement)).toBe(false);
  },
};

/** Errors within: a collapsed section names its count on the heading line, the button's description. */
export const WithErrors: Story = {
  args: { collapsible: true, defaultOpen: false, errorCount: 2 },
  play: async ({ canvasElement }) => {
    const toggle = within(canvasElement).getByRole("button", { name: TITLE });
    await expect(toggle).toHaveAccessibleDescription("2 problems");
  },
};

/** Plain disabled: `<fieldset disabled>`, for everyone in the state; the fields dim and leave the Tab order. */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    for (const field of within(canvasElement).getAllByRole("textbox")) {
      await expect(field).toBeDisabled();
    }
  },
};

/** T2: one notice under the heading, many pointers; each field keeps the lock and renders no reason of its own. */
export const DisabledWithReason: Story = {
  args: { disabledReason: REASON },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByText(REASON)).toHaveLength(1);
    for (const field of canvas.getAllByRole("textbox")) {
      await expect(field).toHaveAttribute("aria-disabled", "true");
      await expect(field).toHaveAccessibleDescription(REASON);
    }
    await expect(canvas.getAllByRole("img", { name: "Not available" })).toHaveLength(2);
  },
};

/** A wrapped heading, description and notice: they wrap, never clip. */
export const LongText: Story = {
  args: {
    title: "Default stop-loss and take-profit offsets for every account in this group",
    description: `${DESCRIPTION} ${DESCRIPTION}`,
    disabledReason: "Your role can't change settings for accounts assigned to another manager.",
    collapsible: true,
  },
};

const SubmitHost = (): JSX.Element => {
  const [error, setError] = useState<string | undefined>(undefined);
  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    setError("Enter an offset.");
  };
  return (
    <form noValidate onSubmit={submit} style={{ display: "grid", gap: "var(--space-stack-md)" }}>
      <FormSection title="Advanced" collapsible defaultOpen={false}>
        <FormField label="Trailing offset" error={error}>
          <TextInput defaultValue="" />
        </FormField>
      </FormSection>
      <Button type="submit">Save</Button>
    </form>
  );
};

/** Submit around a collapsed, invalid field: the section opens and focus reaches the field. */
export const OpensOnSubmit: Story = {
  render: () => <SubmitHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    const field = canvas.getByRole("textbox", { name: "Trailing offset" });
    await expect(canvas.getByRole("button", { name: "Advanced" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(field).toHaveFocus();
  },
};

const NativeHost = (): JSX.Element => (
  <form onSubmit={(event) => event.preventDefault()}>
    <FormSection title="Advanced" collapsible defaultOpen={false}>
      <FormField label="Trailing offset" required>
        <TextInput defaultValue="" required />
      </FormField>
    </FormSection>
    <Button type="submit">Save</Button>
  </form>
);

/** Native constraint validation: the section opens before the browser moves focus to the field it reports. */
export const OpensOnNativeInvalid: Story = {
  render: () => <NativeHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Save" }));
    await expect(canvas.getByRole("button", { name: "Advanced" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(canvas.getByRole("textbox", { name: "Trailing offset" })).toBeVisible();
  },
};

const col = { display: "grid", gap: "var(--space-stack-lg)" } as const;

/** Every catalogued state on one canvas, for the visual matrix (E05-T04). */
export const AllStates: Story = {
  render: () => (
    <div style={col}>
      <FormSection title="Default" description={DESCRIPTION}>
        <Fields />
      </FormSection>
      <FormSection title="Collapsible" collapsible>
        <Fields />
      </FormSection>
      <FormSection title="Collapsed" collapsible defaultOpen={false}>
        <Fields />
      </FormSection>
      <FormSection title="Errors within" collapsible defaultOpen={false} errorCount={2}>
        <Fields />
      </FormSection>
      <FormSection title="Disabled" disabled>
        <Fields />
      </FormSection>
      <FormSection title="Disabled with reason" disabledReason={REASON}>
        <Fields />
      </FormSection>
    </div>
  ),
};
