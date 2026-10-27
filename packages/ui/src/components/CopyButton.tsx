import { useCallback, useEffect, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { IconButton } from "./IconButton.js";

/** How long the copied (or failed) state holds before it reverts silently (CMP-033 States line, E20). */
export const COPY_RESET_MS = 2000;

/** idle: nothing to say; copied: the last write succeeded; failed: the clipboard refused it (E20). */
export type CopyStatus = "idle" | "copied" | "failed";

/** The only words the status region ever holds: never the copied value. */
const MESSAGES: Readonly<Record<CopyStatus, string>> = {
  idle: "",
  copied: "Copied",
  failed: "Copy failed",
};

export interface UseCopyOptions {
  /**
   * Called after a successful write of the latest press. It receives nothing: the value never travels
   * further. Not called when the host unmounts mid-write or a later press superseded this one.
   */
  onCopied?: () => void;
}

export interface UseCopyResult {
  readonly status: CopyStatus;
  /** The status region's text: "", "Copied" or "Copy failed"; never the value. */
  readonly message: string;
  /** Writes `value` to the clipboard; resolves `true` on success. Never rejects and never logs. */
  readonly copy: (value: string) => Promise<boolean>;
}

/**
 * The clipboard write plus a 2 s status (ruling 9): CMP-033 and its hosts (CMP-034, CMP-089, CMP-091) share
 * it. The value is read at call time from memory and handed only to `navigator.clipboard.writeText`; it is
 * never kept in state, so it never reaches the DOM, an attribute, the status text or a log.
 *
 * The last press wins: a write that resolves after a later press started changes nothing and calls no
 * `onCopied`, and an unmount mid-write skips `onCopied` too. A repeat press empties only the message (so the
 * status is a new announcement) while the glyph state holds, so nothing blinks.
 */
export function useCopy({ onCopied }: UseCopyOptions = {}): UseCopyResult {
  // The glyph state and the live message are separate: a repeat press resets only the message.
  const [status, setStatus] = useState<CopyStatus>("idle");
  const [message, setMessage] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const generation = useRef(0);
  const mounted = useRef(true);
  const latest = useRef(onCopied);
  useEffect(() => {
    latest.current = onCopied;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTimeout(timer.current);
    };
  }, []);

  const copy = useCallback(async (value: string): Promise<boolean> => {
    const press = ++generation.current;
    clearTimeout(timer.current);
    // Empty the region first, so a second copy while "Copied" shows is a new announcement.
    setMessage("");
    let ok: boolean;
    try {
      // `navigator.clipboard` is absent outside a secure context: that is a failed copy, not a throw.
      const clipboard = (navigator as Partial<Navigator>).clipboard;
      if (clipboard === undefined) throw new Error("clipboard unavailable");
      // No timeout on purpose: a hung write (a permission prompt left open) keeps this press pending. A repeat
      // press while "Copied" shows has already emptied the status and cleared the reset timer, so the glyph
      // stays `copied` with an empty status until this write settles and the latest press decides.
      await clipboard.writeText(value);
      ok = true;
    } catch {
      // Swallowed on purpose: an error here may carry the value, and it must never reach a log.
      ok = false;
    }
    // Unmounted, or superseded by a later press: that press owns the status and the timer.
    if (!mounted.current || press !== generation.current) return ok;
    const next: CopyStatus = ok ? "copied" : "failed";
    setStatus(next);
    setMessage(MESSAGES[next]);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setStatus("idle");
      setMessage("");
    }, COPY_RESET_MS);
    if (ok) latest.current?.();
    return ok;
  }, []);

  return { status, message, copy };
}

export interface CopyButtonProps {
  /** The value to copy, held in memory only: never rendered, never an attribute (C-2.7). */
  value: string;
  /** What is copied, as the button's accessible name, e.g. "Copy order ID"; unchanged when copied. */
  label: string;
  /** Called after a successful copy, with no argument. */
  onCopied?: () => void;
  /** Plain disabled, dimmed by the nested CMP-002 only (E21: copying is never gated). */
  disabled?: boolean;
  /** Emits `data-density` on the nested button; absent = inherit. */
  density?: "comfortable" | "compact";
}

const GLYPH = { idle: "copy", copied: "check", failed: "error" } as const;

/**
 * CMP-033 CopyButton: a ghost md CMP-002 with the `copy` glyph. A press writes `value` to the clipboard,
 * swaps to `check` for 2 s and speaks "Copied" through an always-mounted, empty-by-default polite status;
 * a refused write shows the `error` glyph and speaks "Copy failed" (E20). Held-Enter repeats are ignored.
 */
export function CopyButton({
  value,
  label,
  onCopied,
  disabled,
  density,
}: CopyButtonProps): JSX.Element {
  const { status, message, copy } = useCopy(onCopied === undefined ? {} : { onCopied });
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    // One announcement per activation: a held Enter clicks on every keydown repeat, so repeats are
    // cancelled. Space clicks on keyup (once per press), so its repeats need nothing.
    if (event.repeat && event.key === "Enter") event.preventDefault();
  };
  return (
    <span className="cv-copy-button" data-cmp="CMP-033" data-state={status}>
      <IconButton
        icon={GLYPH[status]}
        label={label}
        variant="ghost"
        size="md"
        {...(disabled === undefined ? {} : { disabled })}
        {...(density === undefined ? {} : { density })}
        onKeyDown={onKeyDown}
        onClick={() => {
          void copy(value);
        }}
      />
      <span className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {message}
      </span>
    </span>
  );
}
