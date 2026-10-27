// @vitest-environment jsdom
import type { JSX } from "react";
import { describe, expect, it } from "vitest";
import { Button, IconButton, RadioGroup, Select, Slider, TextInput, Toggle } from "../src/index.js";
import { mount } from "./theme/mount.js";

const options = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Bravo" },
];
const noop = (): void => undefined;

// CMP-003, CMP-005 and CMP-008 add their rows with their own PRs (#4757, #4738, #4761).
const atoms: [string, () => JSX.Element][] = [
  ["CMP-001", () => <Button>Save</Button>],
  ["CMP-002", () => <IconButton icon="lock" label="Settings" />],
  ["CMP-004", () => <Toggle label="Armed" />],
  ["CMP-006", () => <RadioGroup aria-label="Mode" options={options} value="a" onChange={noop} />],
  ["CMP-007", () => <TextInput aria-label="Name" value="" onChange={noop} />],
  ["CMP-009", () => <Select aria-label="Pick" options={options} value="a" onChange={noop} />],
  [
    "CMP-010",
    () => <Slider aria-label="Level" value={1} min={0} max={5} step={1} onChange={noop} />,
  ],
];

describe("control atoms carry their catalogue id", () => {
  it.each(atoms)("%s marks exactly one root with data-cmp", async (id, render) => {
    const host = await mount(render());
    expect(host.querySelectorAll(`[data-cmp="${id}"]`)).toHaveLength(1);
  });
});
