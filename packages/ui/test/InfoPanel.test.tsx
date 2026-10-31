// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import {
  Button,
  Dialog,
  Drawer,
  InfoPanel,
  type InfoPanelProps,
  type InfoPanelTriggerProps,
} from "../src/components/index.js";
import { narrowViewport } from "./narrowViewport.js";
import { mount } from "./theme/mount.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const key = async (key: string, shiftKey = false): Promise<boolean> => {
  let kept = true;
  await act(async () => {
    kept = await fireEvent.keyDown(document.activeElement ?? document.body, { key, shiftKey });
  });
  return kept;
};
const click = async (element: Element): Promise<void> => {
  await act(async () => {
    fireEvent.click(element);
  });
};
const focus = async (element: HTMLElement): Promise<void> => {
  await act(async () => element.focus());
};
const screen = (): ReturnType<typeof within> => within(document.body);
const button = (name: string): HTMLElement => screen().getByRole("button", { name });

/** The CMP-227 chip's stand-in: a CMP-001 button spreading the trigger props. */
const chip = (props: InfoPanelTriggerProps): JSX.Element => (
  <Button variant="ghost" {...props}>
    Estimated
  </Button>
);

type Extra = Partial<Omit<InfoPanelProps, "title" | "content" | "trigger">>;

function Host(props: Extra): JSX.Element {
  return (
    <>
      <InfoPanel
        title="Iceberg detector"
        content={<p>Flags a level that refills after each print.</p>}
        relatedDetector="iceberg"
        values={<p>Refill window: 250 ms</p>}
        trigger={chip}
        {...props}
      />
      <button type="button">Next on the page</button>
    </>
  );
}

/**
 * Focuses the trigger and activates it. The trigger is a native button, whose Enter and Space are its click,
 * so this is the keyboard path too (J18); the stories press the real keys.
 */
const openWith = async (props: Extra = {}): Promise<HTMLElement> => {
  await mount(<Host {...props} />);
  const trigger = button("Estimated");
  expect(trigger.tagName).toBe("BUTTON");
  await focus(trigger);
  await click(trigger);
  return trigger;
};

describe("InfoPanel (CMP-069) drawer", () => {
  it("closed: the trigger only, a button that opens a dialog, collapsed", async () => {
    await mount(<Host />);
    const trigger = button("Estimated");
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-controls");
    expect(screen().queryByRole("dialog")).toBeNull();
  });

  it("J18: activating the trigger opens a non-modal drawer, focus on its heading", async () => {
    const trigger = await openWith();
    const drawer = screen().getByRole("dialog", { name: "Iceberg detector" });
    expect(drawer).not.toHaveAttribute("aria-modal");
    expect(drawer).toHaveAttribute("data-cmp", "CMP-046");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", drawer.id);
    expect(within(drawer).getByRole("heading", { name: "Iceberg detector" })).toHaveFocus();
    const panel = drawer.querySelector('[data-cmp="CMP-069"]');
    expect(panel).toHaveAttribute("data-detector", "iceberg");
    expect(within(drawer).getByText("Flags a level that refills after each print.")).toBeVisible();
    expect(within(drawer).getByText("Refill window: 250 ms")).toBeVisible();
  });

  it("Esc closes it and focus goes back to the trigger", async () => {
    const onOpenChange = vi.fn();
    const trigger = await openWith({ onOpenChange });
    await key("Escape");
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("Tab past its last control leaves it open and moves on to the page", async () => {
    await openWith();
    await focus(button("Close Iceberg detector"));
    await key("Tab");
    expect(button("Next on the page")).toHaveFocus();
    expect(screen().getByRole("dialog", { name: "Iceberg detector" })).toBeVisible();
  });

  it("loading: aria-busy on the body, CMP-015 rows in place of the values, the static text kept", async () => {
    await openWith({ loading: true });
    const drawer = screen().getByRole("dialog", { name: "Iceberg detector" });
    expect(drawer.querySelector(".cv-drawer__body")).toHaveAttribute("aria-busy", "true");
    expect(drawer.querySelector('[data-cmp="CMP-015"]')).toHaveAttribute("data-surface", "overlay");
    expect(within(drawer).queryByText("Refill window: 250 ms")).toBeNull();
    expect(within(drawer).getByText("Flags a level that refills after each print.")).toBeVisible();
  });

  it("error: a polite CMP-027 with Retry in place of the values, the static text kept", async () => {
    const onRetry = vi.fn();
    await openWith({ error: "Couldn't load the current values.", onRetry });
    const drawer = screen().getByRole("dialog", { name: "Iceberg detector" });
    const status = within(drawer).getByRole("status");
    expect(status.closest('[data-cmp="CMP-027"]')).not.toBeNull();
    expect(within(drawer).queryByText("Refill window: 250 ms")).toBeNull();
    expect(drawer.querySelector(".cv-drawer__body")).not.toHaveAttribute("aria-busy");
    await click(within(drawer).getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("an error without onRetry has no Retry", async () => {
    await openWith({ error: "Couldn't load the current values." });
    expect(screen().queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("controlled: the host's open wins; the trigger asks through onOpenChange", async () => {
    function Controlled(): JSX.Element {
      const [open, setOpen] = useState(true);
      return <Host open={open} onOpenChange={setOpen} side="left" width={360} />;
    }
    await mount(<Controlled />);
    const drawer = screen().getByRole("dialog", { name: "Iceberg detector" });
    expect(drawer).toHaveAttribute("data-side", "left");
    expect(drawer.style.getPropertyValue("--cv-drawer-width")).toBe("360px");
    await click(button("Estimated"));
    expect(screen().queryByRole("dialog")).toBeNull();
  });
});

describe("InfoPanel (CMP-069) inline", () => {
  it("closed: the trigger, collapsed and controlling the panel; nothing else renders", async () => {
    const host = await mount(<Host variant="inline" />);
    const trigger = button("Estimated");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).not.toHaveAttribute("aria-haspopup");
    expect(trigger.getAttribute("aria-controls")).not.toBe("");
    expect(host.querySelector('[data-cmp="CMP-069"]')).toBeNull();
  });

  it("activating the trigger opens it under the trigger, focus on its heading (a region)", async () => {
    const trigger = await openWith({ variant: "inline", headingLevel: 4 });
    const region = screen().getByRole("region", { name: "Iceberg detector" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", region.id);
    expect(region).toHaveAttribute("data-variant", "inline");
    expect(region).toHaveAttribute("data-detector", "iceberg");
    expect(within(region).getByRole("heading", { level: 4 })).toHaveFocus();
    expect(screen().queryByRole("dialog")).toBeNull();
  });

  it("the trigger closes it again; Esc inside closes it with focus back on the trigger", async () => {
    const trigger = await openWith({ variant: "inline" });
    await click(trigger);
    expect(screen().queryByRole("region")).toBeNull();
    await click(trigger);
    expect(await key("Escape")).toBe(false);
    expect(screen().queryByRole("region")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("Esc inside an open-at-mount panel finds its trigger by aria-controls", async () => {
    await mount(<Host variant="inline" defaultOpen />);
    // Open at mount: focus stays where it was (no user open moved it).
    expect(screen().getByRole("heading", { name: "Iceberg detector" })).not.toHaveFocus();
    await focus(screen().getByRole("heading", { name: "Iceberg detector" }));
    await key("Escape");
    expect(button("Estimated")).toHaveFocus();
  });

  it("loading: aria-busy on the values part only, base-surface rows; the heading and text stay", async () => {
    await mount(<Host variant="inline" defaultOpen loading />);
    const region = screen().getByRole("region", { name: "Iceberg detector" });
    expect(region).not.toHaveAttribute("aria-busy");
    const values = region.querySelector(".cv-info-panel__values");
    expect(values).toHaveAttribute("aria-busy", "true");
    expect(values?.querySelector('[data-cmp="CMP-015"]')).not.toHaveAttribute("data-surface");
    expect(within(region).getByText("Flags a level that refills after each print.")).toBeVisible();
  });

  it("not loading: no aria-busy anywhere in the region", async () => {
    await mount(<Host variant="inline" defaultOpen />);
    const region = screen().getByRole("region", { name: "Iceberg detector" });
    expect(region.querySelector("[aria-busy]")).toBeNull();
  });

  it("a click a controlled host ignores never makes a later programmatic open take focus", async () => {
    function Ignoring(): JSX.Element {
      const [open, setOpen] = useState(false);
      return (
        <>
          <Host variant="inline" open={open} onOpenChange={() => undefined} />
          <button type="button" onClick={() => setOpen(true)}>
            Open from the host
          </button>
        </>
      );
    }
    await mount(<Ignoring />);
    const trigger = button("Estimated");
    await focus(trigger);
    await click(trigger);
    expect(screen().queryByRole("region")).toBeNull();
    const external = button("Open from the host");
    await focus(external);
    await click(external);
    expect(screen().getByRole("region", { name: "Iceberg detector" })).toBeVisible();
    expect(screen().getByRole("heading", { name: "Iceberg detector" })).not.toHaveFocus();
    expect(external).toHaveFocus();
  });

  it("controlled: the trigger's open, taken by the host, moves focus to the heading", async () => {
    function Taking(): JSX.Element {
      const [open, setOpen] = useState(false);
      return <Host variant="inline" open={open} onOpenChange={setOpen} />;
    }
    await mount(<Taking />);
    await focus(button("Estimated"));
    await click(button("Estimated"));
    expect(screen().getByRole("heading", { name: "Iceberg detector" })).toHaveFocus();
  });

  it("inside a modal Dialog: Esc collapses the panel first, the next Esc closes the dialog", async () => {
    const onDialog = vi.fn();
    await mount(
      <Dialog open title="Detector settings" onOpenChange={onDialog}>
        <Host variant="inline" />
      </Dialog>,
    );
    const dialog = screen().getByRole("dialog", { name: "Detector settings" });
    const trigger = within(dialog).getByRole("button", { name: "Estimated" });
    await focus(trigger);
    await click(trigger);
    expect(within(dialog).getByRole("heading", { name: "Iceberg detector" })).toHaveFocus();
    expect(await key("Escape")).toBe(false);
    expect(within(dialog).queryByRole("region")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(onDialog).not.toHaveBeenCalled();
    await key("Escape");
    expect(onDialog).toHaveBeenLastCalledWith(false, "escape");
  });

  it("inside a modal Drawer: Esc collapses the panel, the drawer stays open", async () => {
    const onDrawer = vi.fn();
    await mount(
      <Drawer open title="Detector settings" onOpenChange={onDrawer}>
        <Host variant="inline" />
      </Drawer>,
    );
    const drawer = screen().getByRole("dialog", { name: "Detector settings" });
    const trigger = within(drawer).getByRole("button", { name: "Estimated" });
    await focus(trigger);
    await click(trigger);
    await key("Escape");
    expect(within(drawer).queryByRole("region")).toBeNull();
    expect(onDrawer).not.toHaveBeenCalled();
    expect(drawer).toBeVisible();
  });

  it("an Esc from outside the region (a sibling on the page) is not the panel's", async () => {
    await mount(<Host variant="inline" defaultOpen />);
    await focus(button("Next on the page"));
    expect(await key("Escape")).toBe(true);
    expect(screen().getByRole("region", { name: "Iceberg detector" })).toBeVisible();
  });

  it("an Esc another handler already took is left alone", async () => {
    await mount(
      <Host
        variant="inline"
        defaultOpen
        values={
          <input
            aria-label="Filter"
            onKeyDown={(event) => {
              if (event.key === "Escape") event.preventDefault();
            }}
          />
        }
      />,
    );
    await focus(screen().getByRole("textbox", { name: "Filter" }));
    await key("Escape");
    expect(screen().getByRole("region", { name: "Iceberg detector" })).toBeVisible();
  });
});

// #5144 ruling A (ledger row A54): the drawer form covers the page at 720 CSS px or less, so it is modal.
describe("InfoPanel (CMP-069) drawer at the narrow breakpoint", () => {
  it("narrow: aria-modal, Tab stays inside, Esc closes and focus returns to the trigger", async () => {
    narrowViewport(true);
    const trigger = await openWith();
    const dialog = screen().getByRole("dialog", { name: "Iceberg detector" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen().getByText("Next on the page").closest("[inert], [aria-hidden]")).not.toBeNull();
    await focus(button("Close Iceberg detector"));
    await key("Tab");
    expect(dialog.contains(document.activeElement)).toBe(true);
    // The close button's tooltip takes the first Esc; focus back on the heading for the drawer's own.
    await focus(screen().getByRole("heading", { name: "Iceberg detector" }));
    await key("Escape");
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("wide: unchanged: no aria-modal, Tab flows on to the page", async () => {
    narrowViewport(false);
    await openWith();
    expect(screen().getByRole("dialog", { name: "Iceberg detector" })).not.toHaveAttribute(
      "aria-modal",
    );
    await focus(button("Close Iceberg detector"));
    await key("Tab");
    expect(button("Next on the page")).toHaveFocus();
  });

  it("the inline form is not a drawer over the page: untouched at narrow", async () => {
    narrowViewport(true);
    await openWith({ variant: "inline" });
    expect(screen().queryByRole("dialog")).toBeNull();
    expect(button("Next on the page").closest("[inert], [aria-hidden]")).toBeNull();
  });
});
