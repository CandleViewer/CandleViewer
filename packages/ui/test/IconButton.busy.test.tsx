// @vitest-environment jsdom
/**
 * E42-S02 (#1023): CMP-002's `busy` (E42-D03 U-7). The row's actions trigger stays mounted while its write is in
 * flight: named by the busy words ("Disabling alex…"), `aria-busy="true"`, a CMP-014 spinner in place of its glyph,
 * still focusable, so focus returns to it when the dialog closes; a press does nothing and says nothing.
 */
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { GatedAnnounceProvider, IconButton } from "../src/components/index.js";
import { visibleTabbables } from "../src/components/internal/focusTrap.js";
import { mount } from "./theme/mount.js";

const BUSY = "Disabling alex…";

describe("IconButton (CMP-002) busy", () => {
  it("takes the busy words as its name, aria-busy and a spinner in place of its glyph", async () => {
    const host = await mount(
      <IconButton icon="more-horizontal" variant="ghost" label="Actions for alex" busy={BUSY} />,
    );
    const button = within(host).getByRole("button", { name: BUSY });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-label", BUSY);
    expect(button.querySelector('[data-cmp="CMP-014"]')).not.toBeNull();
    // The glyph is gone: the spinner's arc is the only drawing, and it is hidden from AT.
    expect(button.querySelectorAll("svg")).toHaveLength(1);
    expect(button.querySelector('[data-cmp="CMP-014"]')).toHaveAttribute("aria-hidden", "true");
  });

  it("stays focusable and in the Tab order: never native disabled, never aria-disabled", async () => {
    const host = await mount(
      <IconButton icon="more-horizontal" label="Actions for alex" busy={BUSY} />,
    );
    const button = within(host).getByRole("button", { name: BUSY });
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(visibleTabbables(host)).toEqual([button]);
  });

  it("a click, Enter or Space does nothing and announces nothing", async () => {
    const onClick = fn();
    const announce = fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <IconButton icon="more-horizontal" label="Actions for alex" busy={BUSY} onClick={onClick} />
      </GatedAnnounceProvider>,
    );
    const button = within(host).getByRole("button", { name: BUSY });
    await userEvent.click(button);
    await act(async () => button.focus());
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onClick).not.toHaveBeenCalled();
    expect(announce).not.toHaveBeenCalled();
  });

  it("its own key handler still sees every key (a grid moves rows from it)", async () => {
    const onKeyDown = fn();
    const host = await mount(
      <IconButton
        icon="more-horizontal"
        label="Actions for alex"
        busy={BUSY}
        onKeyDown={onKeyDown}
      />,
    );
    fireEvent.keyDown(within(host).getByRole("button", { name: BUSY }), { key: "ArrowDown" });
    expect(onKeyDown).toHaveBeenCalledTimes(1);
  });

  it("whitespace is no busy name: the button is as it was", async () => {
    const onClick = fn();
    const host = await mount(
      <IconButton icon="more-horizontal" label="Actions for alex" busy="  " onClick={onClick} />,
    );
    const button = within(host).getByRole("button", { name: "Actions for alex" });
    expect(button).not.toHaveAttribute("aria-busy");
    expect(button.querySelector('[data-cmp="CMP-014"]')).toBeNull();
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is the same element through busy and back, so focus that was on it stays", async () => {
    function Host(): JSX.Element {
      const [busy, setBusy] = useState<string | undefined>(undefined);
      return (
        <>
          <IconButton
            icon="more-horizontal"
            label="Actions for alex"
            {...(busy === undefined ? {} : { busy })}
          />
          <button
            type="button"
            onClick={() => setBusy((b) => (b === undefined ? BUSY : undefined))}
          >
            Toggle
          </button>
        </>
      );
    }
    const host = await mount(<Host />);
    const before = within(host).getByRole("button", { name: "Actions for alex" });
    await act(async () => before.focus());
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Toggle" }));
    });
    const during = within(host).getByRole("button", { name: BUSY });
    expect(during).toBe(before);
    expect(during).toHaveFocus();
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Toggle" }));
    });
    expect(within(host).getByRole("button", { name: "Actions for alex" })).toBe(before);
  });
});
