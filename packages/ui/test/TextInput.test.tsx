// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, waitFor, within } from "storybook/test";
import { describe, it } from "vitest";
import { Icon } from "../src/icons/Icon.js";
import { TextInput } from "../src/components/index.js";
import * as stories from "../src/components/TextInput.stories.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
const get = (host: HTMLElement, name = "Username"): HTMLInputElement =>
  within(host).getByRole("textbox", { name }) as HTMLInputElement;

describe("TextInput (CMP-007)", () => {
  it("renders a native text input named by aria-label, never the placeholder", async () => {
    const host = await mount(<TextInput aria-label="Username" placeholder="trader_01" />);
    const field = get(host);
    expect(field.tagName).toBe("INPUT");
    expect(field.type).toBe("text");
    expect(field).not.toHaveAttribute("aria-invalid");
    expect(field).not.toHaveAttribute("aria-disabled");
    expect(host.querySelector("[data-cmp]")?.getAttribute("data-cmp")).toBe("CMP-007");
  });

  it("is named by an external label (htmlFor)", async () => {
    const host = await mount(
      <>
        <label htmlFor="u">Username</label>
        <TextInput id="u" />
      </>,
    );
    expect(get(host)).toHaveAccessibleName("Username");
  });

  it("works uncontrolled and controlled, with native type, inputMode and maxLength", async () => {
    const onChange = fn();
    const Controlled = (): JSX.Element => {
      const [v, setV] = useState("a");
      return (
        <TextInput
          aria-label="C"
          value={v}
          maxLength={3}
          inputMode="numeric"
          type="url"
          onChange={(e) => {
            onChange(e.target.value);
            setV(e.target.value);
          }}
        />
      );
    };
    const host = await mount(
      <>
        <TextInput aria-label="U" defaultValue="x" />
        <Controlled />
      </>,
    );
    await userEvent.type(get(host, "U"), "yz");
    expect(get(host, "U")).toHaveValue("xyz");
    await userEvent.type(get(host, "C"), "bcd");
    expect(get(host, "C")).toHaveValue("abc");
    expect(onChange).toHaveBeenLastCalledWith("abc");
    expect(get(host, "C")).toHaveAttribute("inputmode", "numeric");
    expect(get(host, "C")).toHaveAttribute("type", "url");
  });

  it("emits density and forwards other attributes", async () => {
    const host = await mount(<TextInput aria-label="U" density="compact" data-testid="x" />);
    expect(host.querySelector("[data-density]")).toHaveAttribute("data-density", "compact");
    expect(get(host, "U")).toHaveAttribute("data-testid", "x");
  });

  it("invalid: aria-invalid, the glyph and the message, described before the help", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <TextInput aria-label="U" aria-describedby="help" invalid errorMessage="Enter it." />
      </>,
    );
    const field = get(host, "U");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).not.toHaveAttribute("aria-errormessage");
    expect(field).toHaveAccessibleDescription("Enter it. Help");
    expect(field.getAttribute("aria-describedby")?.split(" ")[1]).toBe("help");
    expect(host.querySelector(".cv-field__glyph svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("the message node is a polite live region in the DOM at mount, empty while valid", async () => {
    const host = await mount(<TextInput aria-label="U" errorMessage="Enter it." />);
    const node = host.querySelector<HTMLElement>(".cv-field__message");
    expect(node).toHaveAttribute("aria-live", "polite");
    expect(node?.childNodes.length).toBe(0);
    expect(get(host, "U").getAttribute("aria-describedby")).toBe(node?.id);
  });

  it("the same live node receives the message when the field becomes invalid", async () => {
    const Toggle = (): JSX.Element => {
      const [invalid, setInvalid] = useState(false);
      return (
        <>
          <TextInput aria-label="U" invalid={invalid} errorMessage="Enter it." />
          <button type="button" onClick={() => setInvalid(true)}>
            validate
          </button>
        </>
      );
    };
    const host = await mount(<Toggle />);
    const node = host.querySelector(".cv-field__message");
    expect(node?.textContent).toBe("");
    await userEvent.click(within(host).getByRole("button"));
    expect(host.querySelector(".cv-field__message")).toBe(node);
    expect(node?.textContent).toBe("Enter it.");
  });

  it("invalid without a message shows the boundary and aria-invalid only", async () => {
    const host = await mount(<TextInput aria-label="U" invalid />);
    expect(get(host, "U")).toHaveAttribute("aria-invalid", "true");
    expect(host.querySelector(".cv-field__glyph")).toBeNull();
  });

  it("a suffix joins the description, and an affix renders inside the well", async () => {
    const host = await mount(
      <TextInput aria-label="Price" prefix={<Icon name="info" />} suffix="USDT" />,
    );
    expect(get(host, "Price")).toHaveAccessibleDescription(/^\s*USDT$/);
    const well = host.querySelector(".cv-field");
    expect(well).toHaveAttribute("data-lead");
    expect(well).toHaveAttribute("data-trail");
  });

  it("plain disabled uses the native attribute and leaves the Tab order", async () => {
    const host = await mount(<TextInput aria-label="U" disabled />);
    expect(get(host, "U").disabled).toBe(true);
    await userEvent.tab();
    expect(get(host, "U")).not.toHaveFocus();
  });

  it("read-only is focusable, native readonly, and refuses typing", async () => {
    const host = await mount(<TextInput aria-label="U" defaultValue="v" readOnly />);
    await userEvent.tab();
    expect(get(host, "U")).toHaveFocus();
    await userEvent.keyboard("abc");
    expect(get(host, "U")).toHaveValue("v");
    expect(get(host, "U")).toHaveAttribute("readonly");
    expect(host.querySelector(".cv-field")).toHaveAttribute("data-readonly");
  });

  it("T2: aria-disabled + readonly, lock before the input, the reason alone described", async () => {
    const onChange = fn();
    const host = await mount(
      <>
        <span id="help">Help</span>
        <TextInput
          aria-label="U"
          aria-describedby="help"
          defaultValue="v"
          suffix="USDT"
          invalid
          errorMessage="Bad."
          disabled
          disabledReason={REASON}
          onChange={onChange}
        />
      </>,
    );
    const field = get(host, "U");
    expect(field.disabled).toBe(false);
    expect(field).toHaveAttribute("aria-disabled", "true");
    expect(field).toHaveAttribute("readonly");
    expect(field).toHaveAccessibleDescription(REASON);
    const lock = within(host).getByRole("img", { name: "Not available" });
    expect(lock.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.tab();
    expect(field).toHaveFocus();
    await userEvent.keyboard("abc{Enter}{ArrowLeft}");
    expect(field).toHaveValue("v");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("T2: the reason is announced once per focus visit, not on Tab, Esc or a free key, and again after a blur", async () => {
    const host = await mount(
      <>
        <TextInput aria-label="U" defaultValue="v" disabledReason={REASON} />
        <button type="button">next</button>
      </>,
    );
    const status = within(host).getByRole("status");
    const writes: string[] = [];
    new MutationObserver(() => writes.push(status.textContent ?? "")).observe(status, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    expect(status).toHaveTextContent("");
    await userEvent.tab();
    await userEvent.keyboard("{Escape}{ArrowLeft}{Home}{Control>}c{/Control}");
    expect(status).toHaveTextContent("");
    await userEvent.keyboard("a");
    expect(status).toHaveTextContent(REASON);
    await Promise.resolve();
    const afterFirst = writes.length;
    await userEvent.keyboard("b{Backspace}{Enter}");
    await Promise.resolve();
    expect(status).toHaveTextContent(REASON);
    expect(writes.length).toBe(afterFirst);
    await userEvent.tab();
    expect(status).toHaveTextContent("");
    await userEvent.tab({ shift: true });
    expect(status).toHaveTextContent("");
    await userEvent.keyboard("{Delete}");
    expect(status).toHaveTextContent(REASON);
  });

  it("T2: paste and cut are refused and announce; no status node exists when not gated", async () => {
    const gated = await mount(
      <TextInput aria-label="U" defaultValue="v" disabledReason={REASON} />,
    );
    const status = within(gated).getByRole("status");
    await userEvent.click(get(gated, "U"));
    fireEvent.cut(get(gated, "U"));
    await waitFor(() => expect(status).toHaveTextContent(REASON));
    await userEvent.tab();
    expect(status).toHaveTextContent("");
    await userEvent.click(get(gated, "U"));
    fireEvent.paste(get(gated, "U"));
    expect(get(gated, "U")).toHaveValue("v");
    await waitFor(() => expect(status).toHaveTextContent(REASON));
    const plain = await mount(<TextInput aria-label="P" />);
    expect(within(plain).queryByRole("status")).toBeNull();
  });

  it("T2: Enter does not submit the enclosing form, while a plain field still does", async () => {
    const onSubmit = fn((e: { preventDefault: () => void }) => e.preventDefault());
    const host = await mount(
      <form onSubmit={onSubmit}>
        <TextInput aria-label="G" disabledReason={REASON} />
        <TextInput aria-label="P" />
        <button type="submit">go</button>
      </form>,
    );
    await userEvent.click(get(host, "G"));
    await userEvent.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.click(get(host, "P"));
    await userEvent.keyboard("{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("combines error, help and unit in that order in aria-describedby", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <TextInput
          aria-label="U"
          aria-describedby="help"
          suffix="USDT"
          invalid
          errorMessage="Bad."
        />
      </>,
    );
    const ids = get(host, "U").getAttribute("aria-describedby")?.split(" ") ?? [];
    expect(ids).toHaveLength(3);
    expect(ids[0]).toBe(host.querySelector(".cv-field__message")?.id);
    expect(ids[1]).toBe("help");
    expect(ids[2]).toBe(host.querySelector(".cv-field__trail")?.id);
    expect(get(host, "U")).toHaveAccessibleDescription("Bad. Help USDT");
  });

  it("keeps the caller's key and blur handlers, also when gated", async () => {
    const onKeyDown = fn();
    const onBlur = fn();
    await mount(
      <TextInput aria-label="U" disabledReason={REASON} onKeyDown={onKeyDown} onBlur={onBlur} />,
    );
    await userEvent.tab();
    await userEvent.keyboard("a");
    await userEvent.tab();
    expect(onKeyDown.mock.calls.map(([e]) => (e as { key: string }).key)).toEqual(["a", "Tab"]);
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  it("an empty or blank reason is no reason: plain disabled", async () => {
    const host = await mount(<TextInput aria-label="U" disabled disabledReason="  " />);
    expect(get(host, "U").disabled).toBe(true);
    expect(host.querySelector(".cv-visually-hidden:not([role])")).toBeNull();
    expect(within(host).queryByRole("img")).toBeNull();
  });

  it("renders the reason as plain text, never markup", async () => {
    const host = await mount(<TextInput aria-label="U" disabledReason="<b>no</b>" />);
    expect(host.querySelector("b")).toBeNull();
    expect(get(host, "U")).toHaveAccessibleDescription("<b>no</b>");
  });

  it("a press on the well's padding or an affix focuses the input", async () => {
    const host = await mount(<TextInput aria-label="U" suffix="USDT" />);
    await userEvent.click(host.querySelector(".cv-field__affix") as HTMLElement);
    expect(get(host, "U")).toHaveFocus();
    await userEvent.click(get(host, "U"));
    expect(get(host, "U")).toHaveFocus();
  });

  it("only the primary button forwards a press to the input", async () => {
    const host = await mount(<TextInput aria-label="U" suffix="USDT" />);
    const affix = host.querySelector(".cv-field__affix") as HTMLElement;
    expect(fireEvent.mouseDown(affix, { button: 2 })).toBe(true);
    expect(get(host, "U")).not.toHaveFocus();
    expect(fireEvent.mouseDown(affix, { button: 0 })).toBe(false);
    expect(get(host, "U")).toHaveFocus();
  });
});

describe("TextInput stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("textbox").length).toBeGreaterThan(0);
  });
});
