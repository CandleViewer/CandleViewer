// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  Button,
  FileDrop,
  GatedAnnounceProvider,
  formatFileSize,
  type FileDropProps,
} from "../src/index.js";
import { seriousViolations } from "./axe.js";
import * as stories from "../src/components/FileDrop.stories.js";
import { mount } from "./theme/mount.js";

// SCR-101's import (E08-D07 D14, §4.4): plain UTF-8 text, `.txt` or `.csv`, at most 64 KB, read in the client.
const KB64 = 64 * 1024;
const HINT = "or drop a .txt or .csv file here";
const HELP = ".txt or .csv, up to 64 KB";
const ACTIVE = "Drop to check the file";
const REJECT = "Drop one .txt or .csv file";
const NOT_TEXT = "This file isn't plain text.";
const oversized = (size: string): string =>
  `This file is ${size}. A watchlist file can be at most 64 KB.`;
const FULL = "Watching 200 symbols — remove some to add more";
const READ_ONLY = "Read-only — your role can't change watchlists.";

type HostProps = Partial<FileDropProps>;

function Host(props: HostProps): JSX.Element {
  return (
    <FileDrop
      label="Import…"
      accept=".txt,.csv,text/plain,text/csv"
      maxBytes={KB64}
      oversizedMessage={oversized}
      notTextMessage={NOT_TEXT}
      dropHint={HINT}
      dropActiveText={ACTIVE}
      dropRejectText={REJECT}
      help={HELP}
      onText={() => undefined}
      {...props}
    />
  );
}

const page = within(document.body);
const button = (): HTMLElement => page.getByRole("button", { name: "Import…" });
const input = (): HTMLInputElement =>
  document.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement;
const zone = (): HTMLElement =>
  document.querySelector<HTMLElement>(".cv-filedrop__zone") as HTMLElement;
const status = (): HTMLElement =>
  document.querySelector<HTMLElement>('[data-cmp="CMP-067"] > [role="status"]') as HTMLElement;
const textFile = (text: string, name = "Breakouts.txt", type = "text/plain"): File =>
  new File([text], name, { type });
const pick = (file: File): void => {
  fireEvent.change(input(), { target: { files: [file] } });
};
const fileDrag = (count: number, type = "text/plain"): object => ({
  dataTransfer: {
    items: Array.from({ length: count }, () => ({ kind: "file", type })),
    types: ["Files"],
    files: [],
  },
});

describe("FileDrop (CMP-067): the picker", () => {
  it("a real button named by its label; the native input hidden, out of the Tab order, labelled by it", async () => {
    await mount(<Host />);
    expect(input()).toHaveAttribute("hidden");
    expect(input()).toHaveAttribute("tabindex", "-1");
    expect(input()).toHaveAttribute("aria-labelledby", button().id);
    expect(input()).toHaveAttribute("accept", ".txt,.csv,text/plain,text/csv");
  });

  it("the button opens the native picker", async () => {
    await mount(<Host />);
    const click = vi.spyOn(input(), "click");
    await userEvent.click(button());
    expect(click).toHaveBeenCalledOnce();
  });

  it("the drop hint and the help line describe the button", async () => {
    await mount(<Host />);
    expect(button()).toHaveAccessibleDescription(`${HINT} ${HELP}`);
  });

  it("a picked text file is read as UTF-8 and handed to the host as text, never interpreted", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    const file = textFile("# CandleViewer\nBTCUSDT\n<b>ETHUSDT</b>");
    pick(file);
    await waitFor(() =>
      expect(onText).toHaveBeenCalledWith("# CandleViewer\nBTCUSDT\n<b>ETHUSDT</b>", file),
    );
  });

  it("a .csv with no MIME type is taken by its extension", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    pick(textFile("BTCUSDT,ETHUSDT", "majors.csv", ""));
    await waitFor(() => expect(onText).toHaveBeenCalledOnce());
  });

  it("a file over maxBytes is refused before it is read, its size in words", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    const big = textFile("BTCUSDT");
    Object.defineProperty(big, "size", { value: Math.floor(2.1 * 1024 * 1024) });
    pick(big);
    await waitFor(() => expect(page.getByText(oversized("2.1 MB"))).toBeInTheDocument());
    expect(onText).not.toHaveBeenCalled();
  });

  it("a file of another type is refused: This file isn't plain text.", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    pick(new File(["PNG"], "logo.png", { type: "image/png" }));
    await waitFor(() => expect(page.getByText(NOT_TEXT)).toBeInTheDocument());
    expect(onText).not.toHaveBeenCalled();
  });

  it("bytes that are not UTF-8 are refused as not text", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    pick(new File([new Uint8Array([0x42, 0xff, 0xfe])], "list.txt", { type: "text/plain" }));
    await waitFor(() => expect(page.getByText(NOT_TEXT)).toBeInTheDocument());
    expect(onText).not.toHaveBeenCalled();
  });

  it("the host's own rejection shows as a CMP-027 inline error", async () => {
    await mount(<Host error="This file has no symbols." />);
    const error = page.getByText("This file has no symbols.").closest('[data-cmp="CMP-027"]');
    expect(error).toHaveAttribute("data-form", "inline");
  });

  it("T2: the button stays, aria-disabled with its reason; a press opens nothing", async () => {
    await mount(<Host disabledReason={READ_ONLY} />);
    const click = vi.spyOn(input(), "click");
    const gated = page.getByRole("button", { name: "Not available Import…" });
    expect(gated).toHaveAttribute("aria-disabled", "true");
    expect(gated).toHaveAccessibleDescription(READ_ONLY);
    await userEvent.click(gated);
    expect(click).not.toHaveBeenCalled();
  });

  it("T2: the reason shows in the zone under the button (2a), its one description; no drop hint", async () => {
    await mount(<Host disabledReason={READ_ONLY} />);
    const gated = page.getByRole("button", { name: "Not available Import…" });
    const caption = page.getByText(READ_ONLY);
    expect(caption).not.toHaveClass("cv-visually-hidden");
    expect(zone()).toContainElement(caption);
    expect(gated.getAttribute("aria-describedby")).toBe(caption.id);
    expect(zone()).not.toHaveTextContent(HINT);
  });

  it("T2: the lock leads the button's label, named Not available (G-T2.1d)", async () => {
    await mount(<Host disabledReason={READ_ONLY} />);
    const gated = page.getByRole("button", { name: "Not available Import…" });
    expect(gated.firstElementChild).toContainElement(
      within(gated).getByRole("img", { name: "Not available" }),
    );
  });

  it("disabledReasonId: the button is described by the host's one notice; the zone repeats nothing", async () => {
    await mount(
      <>
        <p id="manager-notice">{READ_ONLY}</p>
        <Host disabledReason={READ_ONLY} disabledReasonId="manager-notice" />
      </>,
    );
    const gated = page.getByRole("button", { name: "Not available Import…" });
    expect(gated).toHaveAttribute("aria-describedby", "manager-notice");
    expect(page.getAllByText(READ_ONLY)).toHaveLength(1);
    expect(zone()).not.toHaveTextContent(HINT);
  });
});

describe("formatFileSize", () => {
  it.each([
    [512, "512 bytes"],
    [64 * 1024, "64 KB"],
    [64 * 1024 + 1, "64.1 KB"],
    [Math.floor(2.1 * 1024 * 1024), "2.1 MB"],
  ])(
    "%i bytes read %s: rounded up, so a file over a limit never reads as within it",
    (bytes, words) => {
      expect(formatFileSize(bytes)).toBe(words);
    },
  );

  it("a file one byte over 64 KB is refused in words that are over 64 KB", async () => {
    await mount(<Host />);
    const big = textFile("BTCUSDT");
    Object.defineProperty(big, "size", { value: KB64 + 1 });
    pick(big);
    await waitFor(() => expect(page.getByText(oversized("64.1 KB"))).toBeInTheDocument());
  });
});

describe("FileDrop (CMP-067): the drop zone (additive, never the only way)", () => {
  it("the zone has no role and no Tab stop of its own", async () => {
    await mount(<Host />);
    expect(zone()).not.toHaveAttribute("role");
    expect(zone()).not.toHaveAttribute("tabindex");
  });

  it("one file dragged over: the active words and state; leaving restores the hint", async () => {
    await mount(<Host />);
    act(() => {
      fireEvent.dragEnter(zone(), fileDrag(1));
    });
    expect(zone()).toHaveAttribute("data-state", "active");
    expect(zone()).toHaveTextContent(ACTIVE);
    act(() => {
      fireEvent.dragLeave(zone(), { relatedTarget: document.body });
    });
    expect(zone()).toHaveAttribute("data-state", "rest");
    expect(zone()).toHaveTextContent(HINT);
  });

  it("two files dragged over: the reject words", async () => {
    await mount(<Host />);
    act(() => {
      fireEvent.dragOver(zone(), fileDrag(2));
    });
    expect(zone()).toHaveAttribute("data-state", "reject");
    expect(zone()).toHaveTextContent(REJECT);
  });

  it("dropping one file reads it as a pick does", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    const file = textFile("SOLUSDT");
    fireEvent.drop(zone(), { dataTransfer: { files: [file], items: [], types: ["Files"] } });
    await waitFor(() => expect(onText).toHaveBeenCalledWith("SOLUSDT", file));
  });

  it("dropping two files reads neither and says the reject words once, politely", async () => {
    const onText = vi.fn();
    await mount(<Host onText={onText} />);
    act(() => {
      fireEvent.drop(zone(), {
        dataTransfer: { files: [textFile("A"), textFile("B")], items: [], types: ["Files"] },
      });
    });
    expect(status()).toHaveTextContent(REJECT);
    expect(onText).not.toHaveBeenCalled();
  });

  it("T2: a drop reads nothing; the reason stays shown in the zone and is said once, politely", async () => {
    const onText = vi.fn();
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <Host disabledReason={READ_ONLY} onText={onText} />
      </GatedAnnounceProvider>,
    );
    act(() => {
      fireEvent.drop(zone(), {
        dataTransfer: { files: [textFile("A")], items: [], types: ["Files"] },
      });
    });
    expect(onText).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual([[READ_ONLY]]);
    expect(zone()).toHaveTextContent(READ_ONLY);
    expect(status().textContent).toBe("");
  });

  it("T2: one file dragged over shows no drop words; the zone keeps the reason", async () => {
    await mount(<Host disabledReason={READ_ONLY} />);
    act(() => {
      fireEvent.dragEnter(zone(), fileDrag(1));
    });
    expect(zone()).toHaveAttribute("data-state", "rest");
    expect(zone()).not.toHaveTextContent(ACTIVE);
    expect(zone()).toHaveTextContent(READ_ONLY);
  });
});

describe("FileDrop (CMP-067): the preview step before anything applies", () => {
  const PreviewHost = ({ full = false }: { readonly full?: boolean }): JSX.Element => {
    const [applied, setApplied] = useState("");
    return (
      <>
        <Host
          preview={{
            heading: "Breakouts.txt",
            children: <p>{"<script>"} is not a USDT perpetual symbol</p>,
            actions: [
              { label: "Import into a new list", onSelect: () => setApplied("new"), primary: true },
              {
                label: "Add to Majors",
                onSelect: () => setApplied("majors"),
                ...(full ? { disabledReason: FULL } : {}),
              },
            ],
          }}
        />
        <output>{applied}</output>
      </>
    );
  };

  it("the preview's heading takes focus when it shows", async () => {
    await mount(<PreviewHost />);
    expect(page.getByRole("heading", { name: "Breakouts.txt" })).toHaveFocus();
  });

  it("the host's content renders as text, never as markup", async () => {
    await mount(<PreviewHost />);
    expect(page.getByText("<script> is not a USDT perpetual symbol")).toBeInTheDocument();
    expect(document.querySelector('[data-cmp="CMP-067"] script')).toBeNull();
  });

  it("an apply action runs on press", async () => {
    await mount(<PreviewHost />);
    await userEvent.click(page.getByRole("button", { name: "Import into a new list" }));
    expect(document.querySelector("output")).toHaveTextContent("new");
  });

  it("a full target is T2 with its reason and applies nothing", async () => {
    await mount(<PreviewHost full />);
    const add = page.getByRole("button", { name: "Not available Add to Majors" });
    expect(add).toHaveAttribute("aria-disabled", "true");
    expect(add).toHaveAccessibleDescription(FULL);
    await userEvent.click(add);
    expect(document.querySelector("output")).toHaveTextContent("");
  });

  it("a full target shows its reason under it (2a), the button's one description, its lock leading", async () => {
    await mount(<PreviewHost full />);
    const add = page.getByRole("button", { name: "Not available Add to Majors" });
    const caption = page.getByText(FULL);
    expect(caption).not.toHaveClass("cv-visually-hidden");
    expect(add.getAttribute("aria-describedby")).toBe(caption.id);
    expect(add.compareDocumentPosition(caption)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(add.firstElementChild).toContainElement(
      within(add).getByRole("img", { name: "Not available" }),
    );
  });

  it("a press on a full target says its reason once", async () => {
    const announce = vi.fn<(text: string) => void>();
    await mount(
      <GatedAnnounceProvider announce={announce}>
        <PreviewHost full />
      </GatedAnnounceProvider>,
    );
    await userEvent.click(page.getByRole("button", { name: "Not available Add to Majors" }));
    expect(announce.mock.calls).toEqual([[FULL]]);
  });

  it("axe: the zone, a rejection and a preview with a T2 target", async () => {
    const host = await mount(
      <>
        <Host error="This file has no symbols." />
        <PreviewHost full />
        <Button>After</Button>
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

// Each story's play in jsdom (the storybook project runs them in Chromium, with axe): DragOver drags a real
// DataTransfer, which jsdom has not.
describe("FileDrop stories", () => {
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      if (name === "DragOver") continue;
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  });
});

// The orchestrator's design read on #5146 (item 6): every catalogued component's stories cover hover and keyboard
// focus (`.claude/rules/30-frontend-react.md`), and host text renders in the design-system font, never the serif.
describe("FileDrop stories: hover, focus and the stories' font", () => {
  it("has a Hover and a FocusVisible story", () => {
    expect(Object.keys(composeStories(stories))).toEqual(
      expect.arrayContaining(["Hover", "FocusVisible"]),
    );
  });

  it("host text renders in the design-system font (the host's preview)", async () => {
    const { ImportPreview } = composeStories(stories);
    const host = await mount(<ImportPreview />);
    const text = host.querySelector<HTMLElement>(".cv-filedrop__preview-body dl");
    expect(text).not.toBeNull();
    expect(text?.closest<HTMLElement>('[style*="font-family"]')?.style.fontFamily).toContain(
      "var(--font-family-ui)",
    );
  });
});
