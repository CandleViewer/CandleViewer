import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import { FileDrop, type FileDropPreview, type FileDropProps } from "./FileDrop.js";

/*
 * SCR-101's import (E08-D07 D14, §4.4). The rejections are §4.4's words; the zone's words (hint, help, the two drag
 * states) are PROPOSED for E08-D07's owner, after E15-D09 §3.3's SCR-026 drop zone ("Drop to check the file" is its
 * verbatim). Illustrative files only.
 */
const KB64 = 64 * 1024;
const FULL = "Watching 200 symbols — remove some to add more";
const READ_ONLY = "Read-only — your role can't change watchlists.";

const BASE: FileDropProps = {
  label: "Import…",
  accept: ".txt,.csv,text/plain,text/csv",
  maxBytes: KB64,
  oversizedMessage: (size) => `This file is ${size}. A watchlist file can be at most 64 KB.`,
  notTextMessage: "This file isn't plain text.",
  dropHint: "or drop a .txt or .csv file here",
  dropActiveText: "Drop to check the file",
  dropRejectText: "Drop one .txt or .csv file",
  help: ".txt or .csv, up to 64 KB",
  onText: () => undefined,
};

/** The preview groups of §4.4, as SCR-101 lists them (their symbols as plain text). */
const groups = (
  <dl style={{ margin: 0 }}>
    <dt>To add</dt>
    <dd>BTCUSDT, ETHUSDT, SOLUSDT</dd>
    <dt>Already on Majors</dt>
    <dd>XRPUSDT</dd>
    <dt>Not found on Bybit USDT perps</dt>
    <dd>FOOUSDT</dd>
    <dt>Delisted by the exchange</dt>
    <dd>LUNAUSDT</dd>
    <dt>Not a USDT perpetual symbol</dt>
    <dd>{"<script>alert(1)</script>"}</dd>
  </dl>
);

const preview = (full: boolean): FileDropPreview => ({
  heading: "Breakouts.txt",
  children: groups,
  actions: [
    { label: "Import into a new list", onSelect: () => undefined, primary: true },
    {
      label: "Add to Majors",
      onSelect: () => undefined,
      ...(full ? { disabledReason: FULL } : {}),
    },
  ],
});

/** A host that previews the text it is handed (SCR-101 parses it; here, the file's name and its lines). */
function PreviewHost(): JSX.Element {
  const [read, setRead] = useState<string | undefined>(undefined);
  return (
    <FileDrop
      {...BASE}
      onText={(text, file) => setRead(`${file.name}: ${text.split(/\r?\n/).length} lines`)}
      {...(read === undefined ? {} : { preview: { ...preview(false), heading: read } })}
    />
  );
}

const meta: Meta<typeof FileDrop> = {
  title: "Molecules/FileDrop",
  component: FileDrop,
  args: BASE,
  decorators: [
    (Story) => (
      <div style={{ width: "30rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof FileDrop>;

const pick = (canvasElement: HTMLElement, file: File): void => {
  const input = canvasElement.querySelector<HTMLInputElement>('input[type="file"]');
  if (input !== null) fireEvent.change(input, { target: { files: [file] } });
};

/** At rest: a real "Import…" button fronting the hidden native input, the zone's words its description. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Import…" });
    await expect(button).toHaveAccessibleDescription(
      "or drop a .txt or .csv file here .txt or .csv, up to 64 KB",
    );
  },
};

/**
 * One file dragged over the zone: the words and the edge change, never colour alone. The play drags a real
 * `DataTransfer` (a browser's), so the jsdom run of the plays leaves this one to the storybook project.
 */
export const DragOver: Story = {
  play: async ({ canvasElement }) => {
    const zone = canvasElement.querySelector<HTMLElement>(".cv-filedrop__zone");
    if (zone === null) return;
    const transfer = new DataTransfer();
    transfer.items.add(new File(["BTCUSDT"], "Breakouts.txt", { type: "text/plain" }));
    zone.dispatchEvent(
      new DragEvent("dragenter", { bubbles: true, cancelable: true, dataTransfer: transfer }),
    );
    await waitFor(() => expect(zone).toHaveAttribute("data-state", "active"));
    await expect(zone).toHaveTextContent("Drop to check the file");
  },
};

/** The host's rejection after reading (§4.4): CMP-027 inline. */
export const ErrorStory: Story = {
  name: "Error",
  args: { error: "This file has no symbols." },
  play: async ({ canvasElement }) => {
    await waitFor(() =>
      expect(within(canvasElement).getByText("This file has no symbols.")).toBeInTheDocument(),
    );
  },
};

/** A file over 64 KB is refused before it is read, its size in words (§4.4). */
export const Oversized: Story = {
  play: async ({ canvasElement }) => {
    pick(
      canvasElement,
      new File([new Uint8Array(Math.floor(2.1 * 1024 * 1024))], "Everything.txt"),
    );
    await waitFor(() =>
      expect(
        within(canvasElement).getByText(
          "This file is 2.1 MB. A watchlist file can be at most 64 KB.",
        ),
      ).toBeInTheDocument(),
    );
  },
};

/** A file that is not plain text is refused (§4.4). */
export const NotText: Story = {
  play: async ({ canvasElement }) => {
    pick(canvasElement, new File(["PNG"], "chart.png", { type: "image/png" }));
    await waitFor(() =>
      expect(within(canvasElement).getByText("This file isn't plain text.")).toBeInTheDocument(),
    );
  },
};

/** The preview before anything applies (SCR-026's pattern): its heading takes focus; the file's strings are text. */
export const ImportPreview: Story = {
  args: { preview: preview(false) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Breakouts.txt" })).toHaveFocus();
    await expect(canvas.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  },
};

/** A picked file is read and handed to the host, whose preview then shows. */
export const PickToPreview: Story = {
  render: () => <PreviewHost />,
  play: async ({ canvasElement }) => {
    pick(
      canvasElement,
      new File(["BTCUSDT\nETHUSDT\nSOLUSDT"], "Breakouts.txt", { type: "text/plain" }),
    );
    await waitFor(() =>
      expect(
        within(canvasElement).getByRole("heading", { name: "Breakouts.txt: 3 lines" }),
      ).toHaveFocus(),
    );
  },
};

/**
 * Read-only (D13) with no host notice: "Import…" stays, T2, its lock leading the label; the zone shows the sentence in
 * place of its drop words (2a), the button's one description; a press opens nothing.
 */
export const ReadOnly: Story = {
  args: { disabledReason: READ_ONLY },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Not available Import…" });
    await expect(button).toHaveAttribute("aria-disabled", "true");
    await expect(button).toHaveAccessibleDescription(READ_ONLY);
    await expect(within(canvasElement).queryByText("or drop a .txt or .csv file here")).toBeNull();
    await userEvent.click(button);
  },
};

/** Read-only (D13) as SCR-101 draws it: the host's one notice describes "Import…" (`disabledReasonId`). */
export const ReadOnlyNotice: Story = {
  args: { disabledReason: READ_ONLY, disabledReasonId: "manager-read-only" },
  render: (args) => (
    <>
      <p id="manager-read-only" style={{ margin: "0 0 0.5rem" }}>
        {READ_ONLY}
      </p>
      <FileDrop {...args} />
    </>
  ),
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Not available Import…" });
    await expect(button).toHaveAttribute("aria-describedby", "manager-read-only");
    await expect(within(canvasElement).getAllByText(READ_ONLY)).toHaveLength(1);
  },
};

/**
 * A full target (D10): "Add to Majors" at 200 is T2, its lock leading the label and the cap's sentence under it (2a);
 * a new list still takes the file.
 */
export const TargetFull: Story = {
  args: { preview: preview(true) },
  play: async ({ canvasElement }) => {
    const add = within(canvasElement).getByRole("button", { name: "Not available Add to Majors" });
    await expect(add).toHaveAttribute("aria-disabled", "true");
    await expect(add).toHaveAccessibleDescription(FULL);
    await expect(within(canvasElement).getByText(FULL)).toBeVisible();
  },
};
