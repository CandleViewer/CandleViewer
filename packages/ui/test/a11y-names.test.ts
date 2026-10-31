// @vitest-environment jsdom
// E05-Q02 (#262) accessible-name check: the role and accessible name each v0 component's default story
// must expose, hand-encoded from the `- **A11y**:` lines of docs/plan/15-component-catalogue.md. The
// assertion is testing-library's `getByRole(role, { name })`, which computes the name from the
// accessibility tree (aria-labelledby, aria-label, content, title), not from an attribute grep.
//
// Run: pnpm --filter @candleviewer/ui exec vitest run --project unit test/a11y-names.test.ts
//
// Not in the table (reason): components whose A11y line names no fixed label, so the name is the host's
// copy or composed from props at the point of use and a table row would restate the story's args:
// CMP-007 TextInput, CMP-009 Select, CMP-011 Tag, CMP-012 Badge (count label only), CMP-016 Tooltip,
// CMP-017 Popover, CMP-020 Typography, CMP-022 Kbd, CMP-031 ColorSwatch, CMP-032 ConfidenceDots; and the
// overlays/composites whose names depend on an open state reached by a play function (CMP-040..049,
// CMP-054, CMP-059, CMP-062, CMP-063: pending E05-S04). Static (non-interactive) CMPs with no name rule
// (CMP-014/015/018/029/038/039) are covered by the storybook axe gate and the e05-q02-ds.qa.ts matrix.
import { composeStories } from "@storybook/react-vite";
import { createElement, type ComponentType } from "react";
import { describe, expect, it } from "vitest";
import { within } from "storybook/test";
import * as avatarGroup from "../src/components/AvatarGroup.stories.js";
import * as avatar from "../src/components/Avatar.stories.js";
import * as button from "../src/components/Button.stories.js";
import * as checkbox from "../src/components/Checkbox.stories.js";
import * as copyButton from "../src/components/CopyButton.stories.js";
import * as iconButton from "../src/components/IconButton.stories.js";
import * as maskedValue from "../src/components/MaskedValue.stories.js";
import * as numericStepper from "../src/components/NumericStepperInput.stories.js";
import * as progressBar from "../src/components/ProgressBar.stories.js";
import * as segmented from "../src/components/SegmentedControl.stories.js";
import * as slider from "../src/components/Slider.stories.js";
import * as toggle from "../src/components/Toggle.stories.js";
import { mount } from "./theme/mount.js";

interface Row {
  readonly cmp: string;
  readonly story: ComponentType;
  readonly role: string;
  readonly name: string | RegExp;
}

const row = (cmp: string, story: ComponentType, role: string, name: string | RegExp): Row => ({
  cmp,
  story,
  role,
  name,
});

const TABLE: readonly Row[] = [
  row("CMP-001 Button", composeStories(button).Default, "button", "Save"),
  row("CMP-002 IconButton", composeStories(iconButton).Default, "button", "Panel settings"),
  row("CMP-003 SegmentedControl", composeStories(segmented).Default, "radiogroup", "Order type"),
  row("CMP-003 SegmentedControl option", composeStories(segmented).Default, "radio", "Market"),
  row("CMP-004 Toggle", composeStories(toggle).Default, "switch", "One-click trading"),
  row(
    "CMP-005 Checkbox",
    composeStories(checkbox).Default,
    "checkbox",
    "Apply to every selected account",
  ),
  row("CMP-008 NumericStepperInput", composeStories(numericStepper).Default, "spinbutton", "Qty"),
  row("CMP-010 Slider", composeStories(slider).Default, "slider", "Leverage"),
  row("CMP-013 Avatar", composeStories(avatar).Default, "img", "Alpha Desk"),
  row("CMP-023 ProgressBar", composeStories(progressBar).Default, "progressbar", "Loading history"),
  row("CMP-025 AvatarGroup", composeStories(avatarGroup).Default, "img", /^3 accounts: /),
  row("CMP-033 CopyButton", composeStories(copyButton).Default, "button", "Copy order ID"),
  row("CMP-034 MaskedValue group", composeStories(maskedValue).Masked, "group", "API secret"),
  row(
    "CMP-034 MaskedValue toggle",
    composeStories(maskedValue).Masked,
    "button",
    "Show API secret",
  ),
];

describe("accessible names of the v0 default stories", () => {
  it.each(TABLE.map((entry) => [entry.cmp, entry] as const))(
    "%s exposes its role and name",
    async (_cmp, { story, role, name }) => {
      const host = await mount(createElement(story));
      expect(within(host).getAllByRole(role, { name }).length).toBeGreaterThan(0);
    },
  );
});

describe("CMP-034 MaskedValue while masked", () => {
  it("never puts the value in a name, label, title or live region", async () => {
    const Masked = composeStories(maskedValue).Masked;
    const value = String(Masked.args["value"]);
    expect(value.length).toBeGreaterThan(8);
    const host = await mount(createElement(Masked));
    const everything = [host, ...host.querySelectorAll<HTMLElement>("*")];
    const named = everything.flatMap((el) =>
      ["aria-label", "aria-description", "aria-valuetext", "title", "alt", "placeholder"].map(
        (attr) => el.getAttribute(attr) ?? "",
      ),
    );
    const labelledBy = everything.flatMap((el) =>
      (el.getAttribute("aria-labelledby") ?? "")
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent ?? ""),
    );
    const live = [
      ...host.querySelectorAll('[aria-live], [role="status"], [role="alert"], [role="log"]'),
    ].map((el) => el.textContent ?? "");
    for (const text of [...named, ...labelledBy, ...live]) expect(text).not.toContain(value);
    // The accessible names the tree computes, by role, for the controls the component owns.
    for (const role of ["group", "button"]) {
      for (const el of within(host).queryAllByRole(role)) {
        expect(el.getAttribute("aria-label") ?? "").not.toContain(value);
      }
    }
    expect(host.innerHTML).not.toContain(value);
  });
});
