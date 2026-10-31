import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type JSX,
  type ReactNode,
} from "react";
import { Button } from "./Button.js";
import { InlineError } from "./ErrorState.js";
import { Heading } from "./Typography.js";
import { useGatedAnnounce } from "./internal/disabledReason.js";

/** An apply target of the preview step: SCR-101's "Import into a new list", "Add to Majors". */
export interface FileDropAction {
  readonly label: string;
  readonly onSelect: () => void;
  /**
   * T2 (E08-D07 §6.6): a target that cannot take the file, such as a full list at 200, with its reason, shown under
   * it (E09-D09 §2.2 rendering 2a) as its description; its lock leads the label.
   */
  readonly disabledReason?: string;
  /** The step's main action: CMP-001 `primary`. */
  readonly primary?: boolean;
}

/** The preview before anything applies (SCR-026's pattern): what the file holds, then where it goes. */
export interface FileDropPreview {
  /** The step's heading; focus moves to it when the preview shows. */
  readonly heading: string;
  /** The host's account of the file (SCR-101's groups, E08-D07 §4.4), its strings rendered as text. */
  readonly children: ReactNode;
  readonly actions: readonly FileDropAction[];
}

export interface FileDropProps {
  /** The button's label: SCR-101's "Import…". */
  readonly label: string;
  /** The native input's `accept`, which a drop is held to as well: ".txt,.csv,text/plain,text/csv". */
  readonly accept: string;
  /** The largest file read, in bytes (SCR-101: 64 KB, E08-D07 D14). */
  readonly maxBytes: number;
  /** The words for a file over `maxBytes`, given its size in words ("2.1 MB"). */
  readonly oversizedMessage: (size: string) => string;
  /** The words for a file that is not text: a type `accept` does not take, or bytes that are not UTF-8. */
  readonly notTextMessage: string;
  /** The one file's text, decoded as UTF-8 and never interpreted here: the host parses and previews it. */
  readonly onText: (text: string, file: File) => void;
  /** The zone's words at rest, the button's description: a drop is the second way in, never the only one. */
  readonly dropHint?: string;
  /** The zone's words while one file it may take is dragged over. */
  readonly dropActiveText?: string;
  /** The zone's words while more than one file is dragged over; said once, politely, if they are dropped. */
  readonly dropRejectText?: string;
  /** A help line under the button, its description too. */
  readonly help?: string;
  /** The host's rejection after reading ("This file has no symbols."): CMP-027 inline. */
  readonly error?: string;
  /**
   * T2 (E08-D07 §6.6): the import control's reason, from CMP-079 RbacGate (no `workspaces:write`, or viewing as).
   * The button stays, focusable, with it; the zone shows it in place of its drop words (2a), its one description; a
   * drop reads nothing and says it once.
   */
  readonly disabledReason?: string;
  /**
   * The host's one notice that shows `disabledReason` (E09-D09 §2.2 "one notice, many pointers"; SCR-101 read-only):
   * the button is described by it, and the zone repeats nothing.
   */
  readonly disabledReasonId?: string;
  /** The preview step before anything applies. */
  readonly preview?: FileDropPreview;
}

const KIB = 1024;

/**
 * A file's size in words: "512 bytes", "70 KB", "2.1 MB": one decimal, dropped when it is zero, rounded up, so a
 * file over a limit never reads as within it (65,537 bytes are "64.1 KB", never "64 KB").
 */
export function formatFileSize(bytes: number): string {
  if (bytes < KIB) return `${bytes} bytes`;
  const [per, unit] = bytes < KIB * KIB ? [KIB, "KB"] : [KIB * KIB, "MB"];
  const tenths = Math.ceil((bytes * 10) / per);
  return `${tenths % 10 === 0 ? tenths / 10 : (tenths / 10).toFixed(1)} ${unit}`;
}

/** Whether `accept` takes `file`: by extension (`.txt`), by MIME type (`text/plain`) or a family (`text/*`). */
function accepts(accept: string, file: File): boolean {
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return accept
    .split(",")
    .map((token) => token.trim().toLowerCase())
    .filter((token) => token !== "")
    .some((token) =>
      token.startsWith(".")
        ? name.endsWith(token)
        : token.endsWith("/*")
          ? type.startsWith(token.slice(0, -1))
          : type === token,
    );
}

/** The file's bytes (`FileReader` where a `Blob` has no `arrayBuffer`). */
const bytesOf = (file: Blob): Promise<ArrayBuffer> =>
  typeof file.arrayBuffer === "function"
    ? file.arrayBuffer()
    : new Promise((resolve, reject) => {
        const reader = new FileReader();
        // `readAsArrayBuffer` leaves an ArrayBuffer in `result`.
        reader.onload = () => resolve(reader.result as ArrayBuffer);
        reader.onerror = () => reject(reader.error ?? new Error("read failed"));
        reader.readAsArrayBuffer(file);
      });

/** The bytes as UTF-8 text, or `undefined` when they are not text (invalid UTF-8, or a NUL byte). */
async function readText(file: File): Promise<string | undefined> {
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(await bytesOf(file));
    return text.includes("\u0000") ? undefined : text;
  } catch {
    return undefined;
  }
}

type DragState = "rest" | "active" | "reject";

/** A target with a reason (whitespace is none, as CMP-001 reads it). */
const gatedAction = (action: FileDropAction): boolean =>
  (action.disabledReason?.trim() ?? "") !== "";

/** The files a drag carries (items while it is over the zone; a drop's own `files`). */
const draggedFiles = (event: DragEvent<HTMLElement>): number =>
  Array.from(event.dataTransfer?.items ?? []).filter((item) => item.kind === "file").length;

/**
 * CMP-067 FileDrop / Import control (E08-D07 §5, D14; E15-D09 §3.3's anatomy): a real CMP-001 button fronts the
 * native `<input type="file">`, which is hidden, out of the Tab order and labelled by it, so the button is the one
 * control a keyboard or a screen reader meets. The zone around it is a second way in, never the only one: no role, no
 * Tab stop, its words the button's description; one file dragged over shows the active words and edge, more than
 * one the reject words. One file is checked (`maxBytes`, `accept`) and read as UTF-8 text, never interpreted, then
 * handed to the host, whose preview step (heading, its text, the apply targets) shows before anything applies. T2
 * (E09-D09 §2.2, 2a): the button's reason shows in the zone in place of its drop words, or in the host's notice
 * (`disabledReasonId`), and a full target's under it; each lock leads its label; a refused drop or press is said once.
 */
export function FileDrop({
  label,
  accept,
  maxBytes,
  oversizedMessage,
  notTextMessage,
  onText,
  dropHint,
  dropActiveText,
  dropRejectText,
  help,
  error,
  disabledReason,
  disabledReasonId,
  preview,
}: FileDropProps): JSX.Element {
  const buttonId = useId();
  const hintId = useId();
  const helpId = useId();
  const headingId = useId();
  const reasonId = useId();
  const actionBase = useId();
  const input = useRef<HTMLInputElement>(null);
  const announceGated = useGatedAnnounce();
  const reason = disabledReason?.trim() || undefined;
  const noticeId = disabledReasonId?.trim() || undefined;
  const [drag, setDrag] = useState<DragState>("rest");
  const [rejected, setRejected] = useState<string | undefined>(undefined);
  // The polite line for a drop of more than one file (the reject words), once each.
  const [said, setSaid] = useState<{ readonly n: number; readonly text: string }>({
    n: 0,
    text: "",
  });
  const say = (text: string): void => setSaid((prev) => ({ n: prev.n + 1, text }));

  const take = async (file: File): Promise<void> => {
    setRejected(undefined);
    if (file.size > maxBytes) {
      setRejected(oversizedMessage(formatFileSize(file.size)));
      return;
    }
    if (!accepts(accept, file)) {
      setRejected(notTextMessage);
      return;
    }
    const text = await readText(file);
    if (text === undefined) setRejected(notTextMessage);
    else onText(text, file);
  };

  const onPick = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.currentTarget.files?.[0];
    // The same file picked again is a new pick.
    event.currentTarget.value = "";
    if (file !== undefined) void take(file);
  };

  const onDragOver = (event: DragEvent<HTMLDivElement>): void => {
    const files = draggedFiles(event);
    if (files === 0) return;
    // Taken by the zone either way, so the browser never opens a file dropped here.
    event.preventDefault();
    if (reason === undefined) setDrag(files === 1 ? "active" : "reject");
  };
  const onDragLeave = (event: DragEvent<HTMLDivElement>): void => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) setDrag("rest");
  };
  const onDrop = (event: DragEvent<HTMLDivElement>): void => {
    setDrag("rest");
    const files = Array.from(event.dataTransfer?.files ?? []);
    // A drop with no file (text, a link, a page's image) is ignored: nothing is read and nothing is followed.
    if (files.length === 0) return;
    event.preventDefault();
    // T2: the reason stays shown at the zone (or in the host's notice) and is said once, as a refused press is.
    if (reason !== undefined) announceGated(reason);
    else if (files.length > 1) {
      if (dropRejectText !== undefined) say(dropRejectText);
    } else if (files[0] !== undefined) void take(files[0]);
  };

  // The preview's heading takes focus as the step shows (E08-D07 §6.5).
  const heading = preview?.heading;
  useEffect(() => {
    if (heading !== undefined) document.getElementById(headingId)?.focus();
  }, [heading, headingId]);

  // T2: no drop words (a drop takes nothing); the reason alone describes the button (E09-D09 §9.2).
  const words =
    reason !== undefined
      ? undefined
      : drag === "active"
        ? dropActiveText
        : drag === "reject"
          ? dropRejectText
          : dropHint;
  const describedBy =
    reason !== undefined
      ? undefined
      : [words === undefined ? "" : hintId, help === undefined ? "" : helpId]
          .filter(Boolean)
          .join(" ") || undefined;
  const shownError = rejected ?? error;

  return (
    <div className="cv-filedrop" data-cmp="CMP-067">
      <div
        className="cv-filedrop__zone"
        data-state={drag}
        onDragEnter={onDragOver}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        <Button
          id={buttonId}
          variant="secondary"
          aria-describedby={describedBy}
          {...(reason === undefined
            ? {}
            : { disabledReason: reason, disabledReasonId: noticeId ?? reasonId })}
          onClick={() => input.current?.click()}
        >
          {label}
        </Button>
        <input
          ref={input}
          type="file"
          accept={accept}
          hidden
          tabIndex={-1}
          aria-labelledby={buttonId}
          onChange={onPick}
        />
        {words === undefined ? null : (
          <p id={hintId} className="cv-filedrop__hint">
            {words}
          </p>
        )}
        {reason === undefined || noticeId !== undefined ? null : (
          <p id={reasonId} className="cv-filedrop__reason">
            {reason}
          </p>
        )}
        {help === undefined ? null : (
          <p id={helpId} className="cv-filedrop__help">
            {help}
          </p>
        )}
      </div>
      {shownError === undefined ? null : <InlineError message={shownError} live="polite" />}
      <span role="status" className="cv-visually-hidden">
        {said.text === "" ? null : <span key={said.n}>{said.text}</span>}
      </span>
      {preview === undefined ? null : (
        <section className="cv-filedrop__preview" aria-labelledby={headingId}>
          <Heading level={3} variant="heading-sm" id={headingId} tabIndex={-1}>
            {preview.heading}
          </Heading>
          <div className="cv-filedrop__preview-body">{preview.children}</div>
          <div
            className="cv-filedrop__actions"
            data-gated={preview.actions.some(gatedAction) ? "" : undefined}
          >
            {preview.actions.map((action, index) => {
              const why = action.disabledReason?.trim() || undefined;
              const whyId = `${actionBase}-${index}`;
              // One wrapper whatever the gate, so a target that fills or frees never re-parents its button.
              return (
                <span key={action.label} className="cv-filedrop__action">
                  <Button
                    variant={action.primary === true ? "primary" : "secondary"}
                    {...(why === undefined ? {} : { disabledReason: why, disabledReasonId: whyId })}
                    onClick={() => action.onSelect()}
                  >
                    {action.label}
                  </Button>
                  {why === undefined ? null : (
                    <span id={whyId} className="cv-filedrop__reason">
                      {why}
                    </span>
                  )}
                </span>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
