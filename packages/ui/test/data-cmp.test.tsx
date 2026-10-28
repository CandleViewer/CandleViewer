// @vitest-environment jsdom
import type { JSX } from "react";
import { describe, expect, it } from "vitest";
import {
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  Dialog,
  FormField,
  FormSection,
  IconButton,
  NumericStepperInput,
  RadioGroup,
  SearchBox,
  SegmentedControl,
  Select,
  Slider,
  Tabs,
  TextInput,
  Toast,
  Toggle,
} from "../src/index.js";
import type { SegmentedOptions } from "../src/index.js";
import { mount } from "./theme/mount.js";

const options = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
];
const segments: SegmentedOptions = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
];
const noop = (): void => undefined;

const atoms: [string, () => JSX.Element][] = [
  ["CMP-001", () => <Button>Save</Button>],
  ["CMP-002", () => <IconButton icon="lock" label="Settings" />],
  [
    "CMP-003",
    () => <SegmentedControl aria-label="View" options={segments} value="a" onChange={noop} />,
  ],
  ["CMP-004", () => <Toggle label="Armed" />],
  ["CMP-005", () => <Checkbox label="Reduce only" />],
  ["CMP-006", () => <RadioGroup aria-label="Mode" options={options} value="a" onChange={noop} />],
  ["CMP-007", () => <TextInput aria-label="Name" value="" onChange={noop} />],
  [
    "CMP-008",
    () => <NumericStepperInput label="Size" value={1} step={1} precision={0} onChange={noop} />,
  ],
  ["CMP-009", () => <Select aria-label="Pick" options={options} value="a" onChange={noop} />],
  [
    "CMP-010",
    () => <Slider aria-label="Level" value={1} min={0} max={5} step={1} onChange={noop} />,
  ],
  [
    "CMP-040",
    () => (
      <FormField label="Name">
        <TextInput />
      </FormField>
    ),
  ],
  ["CMP-054", () => <SearchBox label="Search users" value="alex" onChange={noop} onClear={noop} />],
  [
    "CMP-065",
    () => (
      <FormSection title="Offsets">
        <FormField label="Name">
          <TextInput />
        </FormField>
      </FormSection>
    ),
  ],
];

describe("control atoms carry their catalogue id", () => {
  it.each(atoms)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });
});

const molecules: [string, () => JSX.Element][] = [
  [
    "CMP-042",
    () => (
      <Tabs
        aria-label="Sections"
        tabs={[{ id: "a", label: "Alpha" }]}
        value="a"
        onChange={noop}
        renderPanel={() => null}
      />
    ),
  ],
  ["CMP-045", () => <Toast title="Session extended" />],
  ["CMP-050", () => <Card title="Accounts">Body</Card>],
];

describe("molecules carry their catalogue id", () => {
  it.each(molecules)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });

  it("CMP-043 marks exactly one root with data-cmp (in its portalled layer)", async () => {
    await mount(<Dialog open title="Go to date" onOpenChange={noop} />);
    expect(document.querySelectorAll('[data-cmp="CMP-043"]')).toHaveLength(1);
  });

  it("CMP-044 marks exactly one root with data-cmp (inside its CMP-043 layer)", async () => {
    await mount(
      <ConfirmDialog
        open
        title="Freeze sub_001?"
        confirmLabel="Freeze sub_001"
        onConfirm={noop}
        onCancel={noop}
      />,
    );
    expect(document.querySelectorAll('[data-cmp="CMP-044"]')).toHaveLength(1);
  });
});
