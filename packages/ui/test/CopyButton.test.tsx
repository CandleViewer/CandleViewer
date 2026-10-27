// @vitest-environment jsdom
import { act, type JSX } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, fireEvent, fn, within } from "storybook/test";
import { CopyButton, useCopy, type UseCopyResult } from "../src/components/index.js";
import { COPY_RESET_MS } from "../src/components/CopyButton.js";
import { mount } from "./theme/mount.js";

/** A stand-in that looks like a secret: it must never appear anywhere in the document. */
const VALUE = "sk-demo-4f9c2e7a1b";
const writeText = vi.fn<(text: string) => Promise<void>>();

const installClipboard = (): void => {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
};

beforeEach(() => {
  vi.useFakeTimers();
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  installClipboard();
});

afterEach(() => {
  vi.useRealTimers();
  Reflect.deleteProperty(navigator, "clipboard");
});

/** Press as a click does, and let the clipboard promise settle inside act. */
const press = async (el: HTMLElement): Promise<void> => {
  await act(async () => {
    fireEvent.click(el);
  });
};
const advance = async (ms: number): Promise<void> => {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
};
const button = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("button", { name: "Copy API key" });
const status = (host: HTMLElement): HTMLElement => within(host).getByRole("status");
const glyph = (host: HTMLElement): string =>
  host.querySelector(".cv-copy-button")?.getAttribute("data-state") ?? "";

/** The DOM-wide scan: the value is in no text node and no attribute of the whole document. */
const expectValueAbsent = (): void => {
  expect(document.documentElement.outerHTML).not.toContain(VALUE);
  for (const el of document.querySelectorAll("*")) {
    for (const attr of el.attributes) expect(attr.value).not.toContain(VALUE);
  }
};

describe("CopyButton (CMP-033)", () => {
  it("a ghost md CMP-002 with the copy glyph, named by label, and an empty status at mount", async () => {
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" />);
    const el = button(host);
    expect(el.dataset["cmp"]).toBe("CMP-002");
    expect(el.dataset["variant"]).toBe("ghost");
    expect(el.dataset["size"]).toBe("md");
    expect(el).toHaveAttribute("type", "button");
    expect(host.querySelector(".cv-copy-button")?.getAttribute("data-cmp")).toBe("CMP-033");
    expect(glyph(host)).toBe("idle");
    expect(status(host)).toBeEmptyDOMElement();
    expect(status(host)).toHaveAttribute("aria-live", "polite");
    expectValueAbsent();
  });

  it("copies the in-memory value, shows check, says Copied, calls onCopied without the value", async () => {
    const onCopied = fn();
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" onCopied={onCopied} />);
    const before = button(host).querySelector("svg")?.outerHTML;
    await press(button(host));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith(VALUE);
    expect(glyph(host)).toBe("copied");
    expect(button(host).querySelector("svg")?.outerHTML).not.toBe(before);
    expect(status(host)).toHaveTextContent(/^Copied$/);
    expect(onCopied).toHaveBeenCalledTimes(1);
    expect(onCopied).toHaveBeenCalledWith();
    // The name never changes and never carries the value.
    expect(button(host)).toHaveAccessibleName("Copy API key");
    expectValueAbsent();
  });

  it("reverts silently after 2 s: glyph back, status emptied", async () => {
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" />);
    await press(button(host));
    await advance(COPY_RESET_MS - 1);
    expect(glyph(host)).toBe("copied");
    await advance(1);
    expect(glyph(host)).toBe("idle");
    expect(status(host)).toBeEmptyDOMElement();
  });

  it("a second press while copied re-announces and restarts the 2 s", async () => {
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" />);
    await press(button(host));
    await advance(1500);
    await press(button(host));
    expect(writeText).toHaveBeenCalledTimes(2);
    expect(status(host)).toHaveTextContent("Copied");
    await advance(1500);
    expect(glyph(host)).toBe("copied");
    await advance(500);
    expect(glyph(host)).toBe("idle");
  });

  it("failure (E20): a refused write shows the error glyph and says Copy failed; no onCopied", async () => {
    writeText.mockRejectedValue(new DOMException(`denied ${VALUE}`, "NotAllowedError"));
    const errors = vi.spyOn(console, "error");
    const onCopied = fn();
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" onCopied={onCopied} />);
    await press(button(host));
    expect(glyph(host)).toBe("failed");
    expect(status(host)).toHaveTextContent(/^Copy failed$/);
    expect(onCopied).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled();
    expectValueAbsent();
    await advance(COPY_RESET_MS);
    expect(glyph(host)).toBe("idle");
    expect(status(host)).toBeEmptyDOMElement();
    errors.mockRestore();
  });

  it("failure: no clipboard API (an insecure context) is a failed copy, not a throw", async () => {
    Reflect.deleteProperty(navigator, "clipboard");
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" />);
    if ("clipboard" in navigator) {
      // jsdom versions that ship a clipboard: shadow it with an undefined own property.
      Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    }
    await press(button(host));
    expect(glyph(host)).toBe("failed");
    expect(status(host)).toHaveTextContent("Copy failed");
  });

  it("the status text is only ever empty, Copied or Copy failed", async () => {
    const seen = new Set<string>();
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" />);
    const observer = new MutationObserver(() => seen.add(status(host).textContent ?? ""));
    observer.observe(status(host), { childList: true, characterData: true, subtree: true });
    await press(button(host));
    await advance(COPY_RESET_MS);
    writeText.mockRejectedValue(new Error("no"));
    await press(button(host));
    await advance(COPY_RESET_MS);
    observer.disconnect();
    for (const text of seen) expect(["", "Copied", "Copy failed"]).toContain(text);
    expect(seen.has("Copied")).toBe(true);
  });

  it("ignores held-Enter repeats: one write per activation", async () => {
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" />);
    const repeat = fireEvent.keyDown(button(host), { key: "Enter", repeat: true });
    const repeatSpace = fireEvent.keyDown(button(host), { key: " ", repeat: true });
    const first = fireEvent.keyDown(button(host), { key: "Enter" });
    // A cancelled keydown is what stops the browser's synthetic click.
    expect(repeat).toBe(false);
    expect(repeatSpace).toBe(false);
    expect(first).toBe(true);
  });

  it("disabled: natively disabled through CMP-002, never copies", async () => {
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" disabled />);
    expect(button(host)).toBeDisabled();
    await press(button(host));
    expect(writeText).not.toHaveBeenCalled();
    expect(status(host)).toBeEmptyDOMElement();
  });

  it("density reaches the nested button", async () => {
    const host = await mount(<CopyButton value={VALUE} label="Copy API key" density="compact" />);
    expect(button(host).dataset["density"]).toBe("compact");
  });

  it("unmounting mid-write sets no state, starts no timer and calls no onCopied", async () => {
    let resolve: () => void = () => undefined;
    writeText.mockImplementation(
      () =>
        new Promise<void>((r) => {
          resolve = r;
        }),
    );
    const onCopied = fn();
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () =>
      root.render(<CopyButton value={VALUE} label="Copy API key" onCopied={onCopied} />),
    );
    await act(async () => {
      fireEvent.click(button(host));
    });
    await act(async () => root.unmount());
    await act(async () => {
      resolve();
    });
    expect(vi.getTimerCount()).toBe(0);
    expect(onCopied).not.toHaveBeenCalled();
  });

  it("unmounting while copied clears the 2 s timer", async () => {
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    await act(async () => root.render(<CopyButton value={VALUE} label="Copy API key" />));
    await press(button(host));
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => root.unmount());
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("useCopy (ruling 9)", () => {
  let api: UseCopyResult | undefined;
  function Probe({ onCopied }: { onCopied?: () => void }): JSX.Element {
    api = useCopy(onCopied === undefined ? {} : { onCopied });
    return <span data-status={api.status}>{api.message}</span>;
  }

  it("copy resolves true and drives the 2 s status; the message never holds the value", async () => {
    const onCopied = fn();
    const host = await mount(<Probe onCopied={onCopied} />);
    let ok: boolean | undefined;
    await act(async () => {
      ok = await api?.copy(VALUE);
    });
    expect(ok).toBe(true);
    expect(api?.status).toBe("copied");
    expect(api?.message).toBe("Copied");
    expect(onCopied).toHaveBeenCalledTimes(1);
    expect(host.innerHTML).not.toContain(VALUE);
    await advance(COPY_RESET_MS);
    expect(api?.status).toBe("idle");
    expect(api?.message).toBe("");
  });

  it("copy resolves false on a refused write and never rejects", async () => {
    writeText.mockRejectedValue(new Error(VALUE));
    await mount(<Probe />);
    let ok: boolean | undefined;
    await act(async () => {
      ok = await api?.copy(VALUE);
    });
    expect(ok).toBe(false);
    expect(api?.status).toBe("failed");
    expect(api?.message).toBe("Copy failed");
  });
});
