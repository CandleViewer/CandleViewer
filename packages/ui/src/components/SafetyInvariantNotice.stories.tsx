import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { Button } from "./Button.js";
import { SafetyInvariantNotice } from "./SafetyInvariantNotice.js";

/** The rule editors' sentences, verbatim: E36-D05 FS-1 and FS-2 (`rules.editor.notice.native_stop_1` / `_2`). */
const LEAD = "Every position keeps a native stop — you can move it, not delete it.";
const CLAUSE =
  "Rules can tighten it, never remove it — the stop is held by the exchange, not by this app.";

/** Theme and density come from the toolbars: compact flows the two sentences as one line, comfortable as two. */
const meta: Meta<typeof SafetyInvariantNotice> = {
  title: "Atoms/SafetyInvariantNotice",
  component: SafetyInvariantNotice,
  args: { lead: LEAD, clause: CLAUSE },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: "48rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SafetyInvariantNotice>;

/** Default: a note with the two sentences, the ⓘ glyph hidden from assistive technology; nothing to press. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const note = within(canvasElement).getByRole("note");
    await expect(note).toHaveTextContent(`${LEAD} ${CLAUSE}`);
    await expect(within(note).queryAllByRole("button")).toHaveLength(0);
  },
};

/** InRuleEditor: pinned directly above the action bar, in view at the moment of Arm (E36-D03; E37-D05 §3.9). */
export const InRuleEditor: Story = {
  render: (args) => (
    <div style={{ display: "grid", gap: "var(--space-inset-sm)" }}>
      <SafetyInvariantNotice {...args} />
      <div
        role="group"
        aria-label="Rule actions"
        style={{ display: "flex", gap: "var(--space-inset-sm)" }}
      >
        <Button variant="secondary">Save draft</Button>
        <Button variant="secondary">Validate</Button>
        <Button variant="secondary">Simulate</Button>
        <Button>Arm…</Button>
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const note = within(canvasElement).getByRole("note");
    const bar = within(canvasElement).getByRole("group", { name: "Rule actions" });
    await expect(note.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await expect(note.contains(document.activeElement)).toBe(false);
  },
};
