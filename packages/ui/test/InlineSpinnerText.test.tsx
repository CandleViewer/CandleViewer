// @vitest-environment jsdom
import { act, useLayoutEffect } from "react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, fn, userEvent, within } from "storybook/test";
import { InlineSpinnerText } from "../src/components/index.js";
import { SLOW_AFTER_MS } from "../src/components/InlineSpinnerText.js";
import { mount } from "./theme/mount.js";

const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const root = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>(".cv-inline-spinner-text");
  if (el === null) throw new Error("nothing rendered");
  return el;
};

describe("InlineSpinnerText (CMP-038)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("one polite atomic status wraps the hidden spinner and the words", async () => {
    const host = await mount(<InlineSpinnerText label="Loading positions" />);
    const status = within(host).getByRole("status");
    expect(within(host).getAllByRole("status")).toHaveLength(1);
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-atomic", "true");
    expect(status).toHaveTextContent("Loading positions");
    const spinner = status.querySelector<HTMLElement>(".cv-spinner");
    expect(spinner).toHaveAttribute("aria-hidden", "true");
    expect(spinner?.dataset["size"]).toBe("sm");
    expect(root(host).dataset["cmp"]).toBe("CMP-038");
    expect(root(host).dataset["phase"]).toBe("waiting");
  });

  it("mounts the status empty and inserts the label after mount", async () => {
    const seen: string[] = [];
    function Probe(): null {
      useLayoutEffect(() => {
        seen.push(document.querySelector('[role="status"]')?.textContent ?? "missing");
      }, []);
      return null;
    }
    const host = await mount(
      <>
        <InlineSpinnerText label="Loading" />
        <Probe />
      </>,
    );
    expect(seen).toEqual([""]);
    expect(within(host).getByRole("status")).toHaveTextContent("Loading");
  });

  it("slowLabel replaces the label at 5 s, not before, and nothing changes after", async () => {
    const host = await mount(
      <InlineSpinnerText label="Loading" slowLabel="Still loading… the server is slow to answer" />,
    );
    const status = within(host).getByRole("status");
    await advance(SLOW_AFTER_MS - 1);
    expect(status).toHaveTextContent(/^Loading$/);
    expect(root(host).dataset["phase"]).toBe("waiting");
    await advance(1);
    expect(status).toHaveTextContent("Still loading… the server is slow to answer");
    expect(root(host).dataset["phase"]).toBe("slow");
    const text = status.textContent;
    // No time cap and no elapsed counter: the slow text holds.
    await advance(60_000);
    expect(status.textContent).toBe(text);
  });

  it.each([
    ["label", { kind: "load", label: "Loading trades" }],
    ["kind", { kind: "export", label: "Loading" }],
  ] as const)("a new %s resets the slow phase and restarts the 5 s timer", async (_, next) => {
    const { createRoot } = await import("react-dom/client");
    const host = document.body.appendChild(document.createElement("div"));
    const r = createRoot(host);
    const onCancel = fn();
    await act(async () =>
      r.render(
        <InlineSpinnerText kind="load" label="Loading" slowLabel="Still…" onCancel={onCancel} />,
      ),
    );
    await advance(SLOW_AFTER_MS);
    const status = within(host).getByRole("status");
    expect(status).toHaveTextContent("Still…");
    await act(async () =>
      r.render(<InlineSpinnerText {...next} slowLabel="Still…" onCancel={onCancel} />),
    );
    expect(status).toHaveTextContent(next.label);
    expect(host.querySelector<HTMLElement>(".cv-inline-spinner-text")?.dataset["phase"]).toBe(
      "waiting",
    );
    expect(within(host).queryByRole("button")).toBeNull();
    await advance(SLOW_AFTER_MS - 1);
    expect(status).toHaveTextContent(next.label);
    await advance(1);
    expect(status).toHaveTextContent("Still…");
    expect(within(host).getByRole("button", { name: "Cancel" })).toBeTruthy();
    await act(async () => r.unmount());
  });

  it("without slowLabel the label holds through the slow phase", async () => {
    const host = await mount(<InlineSpinnerText label="Loading" />);
    await advance(SLOW_AFTER_MS);
    expect(within(host).getByRole("status")).toHaveTextContent(/^Loading$/);
  });

  it("clears its timer on unmount", async () => {
    const { createRoot } = await import("react-dom/client");
    const r = createRoot(document.body.appendChild(document.createElement("div")));
    await act(async () => r.render(<InlineSpinnerText label="Loading" />));
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => r.unmount());
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["load", "export", "replay"] as const)(
    "a %s offers Cancel from the slow path on, outside the status, without taking focus",
    async (kind) => {
      const onCancel = fn();
      const host = await mount(
        <InlineSpinnerText kind={kind} label="Loading" onCancel={onCancel} cancelLabel="Stop" />,
      );
      expect(within(host).queryByRole("button")).toBeNull();
      await advance(SLOW_AFTER_MS);
      const cancel = within(host).getByRole("button", { name: "Stop" });
      expect(cancel.dataset["cmp"]).toBe("CMP-001");
      expect(cancel.dataset["variant"]).toBe("ghost");
      expect(cancel.dataset["size"]).toBe("sm");
      expect(document.body).toHaveFocus();
      expect(within(host).getByRole("status")).not.toHaveTextContent("Stop");
      act(() => cancel.click());
      expect(onCancel).toHaveBeenCalledTimes(1);
    },
  );

  it("Cancel defaults to the word 'Cancel'", async () => {
    const host = await mount(<InlineSpinnerText kind="load" label="Loading" onCancel={fn()} />);
    await advance(SLOW_AFTER_MS);
    expect(within(host).getByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it.each(["submit", "wait"] as const)(
    "a %s never offers Cancel, even when a JavaScript caller passes onCancel",
    async (kind) => {
      const loose = { kind, label: "Submitting", onCancel: fn() } as unknown as Parameters<
        typeof InlineSpinnerText
      >[0];
      const host = await mount(<InlineSpinnerText {...loose} />);
      await advance(SLOW_AFTER_MS * 2);
      expect(within(host).queryByRole("button")).toBeNull();
      expect(root(host).dataset["kind"]).toBe(kind);
    },
  );

  it("keeps Cancel off a submit at the type level", () => {
    // @ts-expect-error a submit never offers Cancel (C-2.10)
    const submit = <InlineSpinnerText kind="submit" label="x" onCancel={fn()} />;
    // @ts-expect-error the default kind is a plain wait, with no Cancel
    const plain = <InlineSpinnerText label="x" onCancel={fn()} />;
    expect([submit, plain]).toHaveLength(2);
  });

  it("Cancel follows the text in the Tab order and activates with Enter", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onCancel = fn();
    const host = await mount(
      <InlineSpinnerText kind="replay" label="Loading" onCancel={onCancel} />,
    );
    await advance(SLOW_AFTER_MS);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.tab();
    expect(within(host).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
