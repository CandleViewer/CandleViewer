// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import { SearchBox } from "../src/components/index.js";
import * as stories from "../src/components/SearchBox.stories.js";
import { mount } from "./theme/mount.js";

const LABEL = "Search users";

const Host = ({
  initial = "",
  onClear,
  onEscape,
  disabled = false,
}: {
  readonly initial?: string;
  readonly onClear?: () => void;
  readonly onEscape?: () => void;
  readonly disabled?: boolean;
}): JSX.Element => {
  const [value, setValue] = useState(initial);
  return (
    // The wrapper stands in for a dialog that closes on a bubbled Esc.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a test listener, not a widget
    <div
      onKeyDown={(event) => {
        if (event.key === "Escape") onEscape?.();
      }}
    >
      <SearchBox
        label={LABEL}
        placeholder="Search by name"
        value={value}
        onChange={setValue}
        onClear={() => {
          onClear?.();
          setValue("");
        }}
        disabled={disabled}
      />
    </div>
  );
};

describe("SearchBox (CMP-054)", () => {
  it("is a native searchbox named by the mandatory label, never by the placeholder", async () => {
    const host = await mount(<Host />);
    const field = within(host).getByRole("searchbox", { name: LABEL });
    expect(field).toHaveAttribute("type", "search");
    expect(field).toHaveAttribute("aria-label", LABEL);
    expect(field).toHaveAttribute("placeholder", "Search by name");
    expect(host.querySelector('[data-cmp="CMP-054"]')).not.toBeNull();
  });

  it("draws the search glyph as decoration only", async () => {
    const host = await mount(<Host />);
    const glyph = host.querySelector(".cv-field__lead svg");
    expect(glyph).toHaveAttribute("aria-hidden", "true");
  });

  it("shows the clear button only with a value", async () => {
    const host = await mount(<Host />);
    expect(within(host).queryByRole("button", { name: "Clear search" })).toBeNull();
    await userEvent.type(within(host).getByRole("searchbox"), "al");
    expect(within(host).getByRole("button", { name: "Clear search" })).toBeInTheDocument();
  });

  it("reports each typed query through onChange", async () => {
    const onChange = vi.fn();
    const host = await mount(
      <SearchBox label={LABEL} value="" onChange={onChange} onClear={() => undefined} />,
    );
    await userEvent.type(within(host).getByRole("searchbox"), "a");
    expect(onChange).toHaveBeenCalledWith("a", expect.anything());
  });

  it("Tab reaches the field, then the clear button", async () => {
    const host = await mount(<Host initial="alex" />);
    await userEvent.tab();
    expect(within(host).getByRole("searchbox")).toHaveFocus();
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "Clear search" })).toHaveFocus();
  });

  it("the clear button clears and returns focus to the field", async () => {
    const onClear = vi.fn();
    const host = await mount(<Host initial="alex" onClear={onClear} />);
    await userEvent.click(within(host).getByRole("button", { name: "Clear search" }));
    const field = within(host).getByRole("searchbox");
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(within(host).queryByRole("button", { name: "Clear search" })).toBeNull();
  });

  it("Enter on the clear button clears and returns focus to the field", async () => {
    const host = await mount(<Host initial="alex" />);
    within(host).getByRole("button", { name: "Clear search" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(within(host).getByRole("searchbox")).toHaveValue("");
    expect(within(host).getByRole("searchbox")).toHaveFocus();
  });

  it("Esc clears a non-empty query and keeps focus; it bubbles only once the query is empty", async () => {
    const onEscape = vi.fn();
    const onClear = vi.fn();
    const host = await mount(<Host initial="alex" onEscape={onEscape} onClear={onClear} />);
    const field = within(host).getByRole("searchbox");
    field.focus();
    await userEvent.keyboard("{Escape}");
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onEscape).not.toHaveBeenCalled();
    await userEvent.keyboard("{Escape}");
    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("leaves Esc to a host handler that prevented it", async () => {
    const onClear = vi.fn();
    const host = await mount(
      <SearchBox
        label={LABEL}
        value="alex"
        onChange={() => undefined}
        onClear={onClear}
        onKeyDown={(event) => event.preventDefault()}
      />,
    );
    within(host).getByRole("searchbox").focus();
    await userEvent.keyboard("{Escape}");
    expect(onClear).not.toHaveBeenCalled();
  });

  it("plain disabled: native disabled, out of the Tab order", async () => {
    const host = await mount(<Host disabled />);
    expect(within(host).getByRole("searchbox")).toBeDisabled();
    await userEvent.tab();
    expect(within(host).getByRole("searchbox")).not.toHaveFocus();
  });

  it("a press on the well focuses the field", async () => {
    const host = await mount(<Host />);
    const well = host.querySelector<HTMLElement>(".cv-field");
    expect(well).not.toBeNull();
    if (well !== null) await userEvent.click(well);
    expect(within(host).getByRole("searchbox")).toHaveFocus();
  });
});

describe("SearchBox stories", () => {
  const composed = composeStories(stories);
  it.each(Object.entries(composed))("%s renders a search field", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-054"]').length).toBeGreaterThan(0);
  });
});
