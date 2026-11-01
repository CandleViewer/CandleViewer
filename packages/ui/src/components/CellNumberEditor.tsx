import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type JSX,
  type KeyboardEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
import { formatDecimal } from "./internal/decimalText.js";
import {
  checkTyped,
  compareDecimal,
  parseTyped,
  parseWire,
  stepFrom,
  toText,
  widen,
  type StepCheck,
  type StepDecimal,
} from "./internal/decimalStep.js";
import { ReasonText, useDisabledReason, useGatedAnnounce } from "./internal/disabledReason.js";
import { FieldMessage } from "./internal/fieldParts.js";

/** What the step is: a price's or a trigger's tick, or a quantity's lot (E29-D02 §7). */
export type CellEditorUnit = "tick" | "lot";

export interface CellNumberEditorCopy {
  /** The step hint (E29-D02 §7, D02:303): "Step 0.1 · ↑/↓ one tick · Shift ten". */
  readonly stepHint: (step: string, unit: CellEditorUnit) => string;
  /** CMP-008's words for text that is no number. */
  readonly notANumber: string;
  /** PROPOSED (E29-D03 with E30-D04, BQ-11): zero or less. */
  readonly notPositive: string;
  /** PROPOSED: a value off the step, which the editor never rounds. */
  readonly offStep: (step: string) => string;
  /** PROPOSED: below the lowest valid value. */
  readonly belowMin: (min: string) => string;
}

export const CELL_NUMBER_EDITOR_COPY: CellNumberEditorCopy = {
  stepHint: (step, unit) => `Step ${step} · ↑/↓ one ${unit} · Shift ten`,
  notANumber: "Enter a number.",
  notPositive: "Enter a number above zero.",
  offStep: (step) => `Enter a multiple of ${step}.`,
  belowMin: (min) => `Enter ${min} or more.`,
};

export interface CellNumberEditorProps {
  /** The value's name, which the host makes the row's ("Price, ETHUSDT Buy on Sub-2"); the shown value follows it. */
  label: string;
  /** The live, confirmed value: the wire's decimal string. Shown until an edit starts, and under the editor during it. */
  value: string;
  /** The tick or the lot as a decimal string above zero ("0.1", "0.001"). */
  step: string;
  /** "tick" for a price or a trigger, "lot" for a quantity: the step hint's word, and CMP-100 or CMP-101. */
  unit: CellEditorUnit;
  /** The lowest valid value (a decimal string): a step down stops at it, and a typed value below it is refused. */
  min?: string;
  /** `Enter` on a valid value that differs from `value`: the typed decimal string, never rounded, never a number. */
  onCommit: (value: string) => void;
  /** The host's own verdict on a value the editor accepts (E29-D01 D7: a stop's quantity that leaves size bare). */
  validate?: (value: string) => string | undefined;
  /** Controlled editing: the host opens the editor from its grid cell or its row menu. */
  editing?: boolean;
  /**
   * Every open, close and discarded edit, controlled or not: the host suppresses its trading hotkeys while an edit is
   * open (E29-D02 §7), and a controlled host applies the change.
   */
  onEditingChange?: (editing: boolean) => void;
  /** The description during an edit (E29-D02 §7: "Editing the price. 2,500.00 stays live until you press Enter."). */
  editingDescription?: string;
  disabled?: boolean;
  /** The visible reason the edit is denied: disabled-with-reason (T2, E09-D09 §2.2), rendered 2b in the cell. */
  disabledReason?: string;
  density?: "comfortable" | "compact";
  /** A roving grid's stop: `-1` for a cell that is not its stop. */
  tabIndex?: 0 | -1;
  copy?: Partial<CellNumberEditorCopy>;
}

const isChord = (event: KeyboardEvent): boolean => event.ctrlKey || event.metaKey || event.altKey;

/** The live value as the cell shows it: grouped at the step's places or the value's own, never fewer (no rounding). */
function shownText(value: StepDecimal | null, raw: string, step: StepDecimal): string {
  if (value === null) return raw;
  return formatDecimal(toText(widen(value, step.scale)))?.text ?? raw;
}

/**
 * The cell use of CMP-100 PriceInput and CMP-101 QtyInput (E29-S02 BQ-11; E29-D02 §7): one grid cell's value,
 * edited in place as the wire's decimal string. At rest it is a read-only spin button showing the live value;
 * `Enter`, `F2` or a double-click opens the editor, a fresh field that takes focus. `↑` / `↓` step one tick or lot,
 * `Shift` ten, on a scaled BigInt; `Enter` alone commits a valid value, and `Esc`, `Tab` or a click elsewhere
 * restores the live value. Nothing is rounded: a value off the step is refused with its reason. Gated (T2), it keeps
 * its name and its place in the Tab order with `aria-disabled`, a lock glyph and the reason echoed (2b).
 */
export function CellNumberEditor({
  label,
  value,
  step,
  unit,
  min,
  onCommit,
  validate,
  editing: editingProp,
  onEditingChange,
  editingDescription,
  disabled,
  disabledReason,
  density,
  tabIndex = 0,
  copy: copyOverride,
}: CellNumberEditorProps): JSX.Element {
  const copy: CellNumberEditorCopy = { ...CELL_NUMBER_EDITOR_COPY, ...copyOverride };
  const parsedStep = parseWire(step);
  const stepValue: StepDecimal =
    parsedStep !== null && parsedStep.units > 0n ? parsedStep : { units: 1n, scale: 0 };
  const minValue = min === undefined ? undefined : (parseWire(min) ?? undefined);
  const live = parseWire(value);
  const reason = useDisabledReason(disabled, disabledReason);
  const announce = useGatedAnnounce();
  const blocked = reason.gated || reason.disabled || live === null;
  const [own, setOwn] = useState(false);
  const held = editingProp ?? own;
  const editing = held && !blocked;
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const displayRef = useRef<HTMLInputElement>(null);
  const editRef = useRef<HTMLInputElement>(null);
  /** Set while `Enter` or `Esc` closes the editor, so a blur its unmount may raise restores nothing twice. */
  const closing = useRef(false);
  /** Set when a close returns focus to the cell's value (`Enter`, `Esc`); a blur leaves focus where it went. */
  const refocus = useRef(false);
  const latest = useRef({ onEditingChange, controlled: editingProp !== undefined });
  const descriptionId = useId();
  const hintId = useId();
  const messageId = useId();
  const shown = shownText(live, value, stepValue);
  const plain = live === null ? value : toText(widen(live, stepValue.scale));

  useLayoutEffect(() => {
    latest.current = { onEditingChange, controlled: editingProp !== undefined };
  });

  /** Opens or closes: held here when uncontrolled, and always told to the host. Stable across renders. */
  const setEditing = useCallback((next: boolean): void => {
    if (!latest.current.controlled) setOwn(next);
    latest.current.onEditingChange?.(next);
  }, []);

  // Every edit starts from the live value at the step's places, whoever opened it; an earlier message goes.
  const [seenOpen, setSeenOpen] = useState(editing);
  if (seenOpen !== editing) {
    setSeenOpen(editing);
    if (editing) {
      setDraft(plain);
      setError(null);
    }
  }

  // The editor is a fresh field: it takes focus when it opens, so its name and description are read once. Closed by
  // `Enter` or `Esc`, focus comes back to the cell's value.
  useLayoutEffect(() => {
    if (editing) {
      closing.current = false;
      editRef.current?.focus();
      editRef.current?.select();
    } else if (refocus.current) {
      refocus.current = false;
      displayRef.current?.focus();
    }
  }, [editing]);

  // An edit under way when the cell becomes gated or disabled is discarded, never committed (CMP-008's rule). The
  // editor that held focus is gone: focus stays on the cell's value, never on the body (`05` §3.4.3).
  const discarded = held && blocked;
  useEffect(() => {
    if (!discarded) return;
    const doc = displayRef.current?.ownerDocument;
    if (doc !== undefined && (doc.activeElement === null || doc.activeElement === doc.body)) {
      displayRef.current?.focus();
    }
    setEditing(false);
  }, [discarded, setEditing]);

  if (parsedStep === null || parsedStep.units <= 0n) {
    throw new RangeError(
      `CellNumberEditor: step must be a decimal string above zero, not "${step}"`,
    );
  }

  const open = (): void => {
    if (reason.gated) {
      announce(reason.reason); // G-T2.3: nothing changes; the reason is said once more, politely
      return;
    }
    if (!blocked) setEditing(true);
  };

  const close = (returnFocus: boolean): void => {
    closing.current = true;
    refocus.current = returnFocus;
    setEditing(false);
  };

  function messageOf(check: Exclude<StepCheck, { kind: "ok" }>): string {
    switch (check.kind) {
      case "empty":
      case "not_a_number":
        return copy.notANumber;
      case "not_positive":
        return copy.notPositive;
      case "off_step":
        return copy.offStep(step);
      case "below_min":
        return copy.belowMin(min ?? step);
    }
  }

  function commit(): void {
    const check = checkTyped(draft, stepValue, minValue);
    if (check.kind !== "ok") {
      setError(messageOf(check));
      return;
    }
    const text = toText(check.value);
    const refusal = validate?.(text);
    if (refusal !== undefined && refusal !== "") {
      setError(refusal);
      return;
    }
    const changed = live === null || compareDecimal(check.value, live) !== 0;
    close(true);
    if (changed) onCommit(text);
  }

  /** A step starts from clean typed text, else from the live value (as CMP-008's does). */
  function stepDraft(direction: "up" | "down", times: number): void {
    const typed = parseTyped(draft);
    const from = typed !== null && typed.units > 0n ? typed : (live ?? stepValue);
    setDraft(toText(stepFrom(from, stepValue, direction, times, minValue)));
    setError(null);
  }

  const onEditKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.nativeEvent.isComposing || isChord(event)) return;
    if (event.key === "Enter") commit();
    else if (event.key === "Escape") close(true);
    else if (event.key === "ArrowUp" || event.key === "ArrowDown")
      stepDraft(event.key === "ArrowUp" ? "up" : "down", event.shiftKey ? 10 : 1);
    else return;
    // The editor owns these keys while it is open: the grid neither moves nor leaves its interaction mode.
    event.preventDefault();
    event.stopPropagation();
  };

  const onDisplayKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (isChord(event) || event.shiftKey || (event.key !== "Enter" && event.key !== "F2")) return;
    event.preventDefault();
    event.stopPropagation();
    open();
  };

  const onInput = (event: ChangeEvent<HTMLInputElement>): void => {
    const text = event.target.value;
    setDraft(text);
    // A shown message keeps its words while the text is still refused, then clears silently (CMP-008's rule).
    if (error !== null && checkTyped(text, stepValue, minValue).kind === "ok") setError(null);
  };

  const root = {
    className: "cv-cell-editor",
    "data-cmp": unit === "tick" ? "CMP-100" : "CMP-101",
    "data-use": "cell",
    "data-density": density,
    "data-editing": editing ? "" : undefined,
    "data-invalid": editing && error !== null ? "" : undefined,
    "data-gated": reason.gated ? "" : undefined,
    "data-disabled": reason.disabled ? "" : undefined,
  };

  if (editing) {
    const describedBy = [editingDescription === undefined ? "" : descriptionId, hintId, messageId]
      .filter((id) => id !== "")
      .join(" ");
    // The step hint is a caption, not a CMP-016 tooltip: an open tooltip takes the first `Esc` as
    // its own layer (conventions 32), and here `Esc` must restore the live value at once (D01 D12).
    return (
      <span {...root}>
        <span className="cv-cell-editor__well">
          <input
            ref={editRef}
            key="editing"
            type="text"
            role="spinbutton"
            inputMode="decimal"
            autoComplete="off"
            spellCheck={false}
            className="cv-cell-editor__input"
            size={Math.max(draft.length, plain.length) + 1}
            value={draft}
            aria-label={label}
            aria-valuetext={draft === "" ? undefined : draft}
            aria-invalid={error !== null ? true : undefined}
            aria-describedby={describedBy}
            onChange={onInput}
            onKeyDown={onEditKeyDown}
            onBlur={() => {
              if (!closing.current) close(false); // `Tab` away or a click elsewhere restores the live value
            }}
          />
        </span>
        <span className="cv-cell-editor__live" aria-hidden="true">
          {shown}
        </span>
        <span id={hintId} className="cv-cell-editor__hint">
          {copy.stepHint(step, unit)}
        </span>
        {editingDescription === undefined ? null : (
          <span id={descriptionId} className="cv-visually-hidden">
            {editingDescription}
          </span>
        )}
        <FieldMessage id={messageId} message={error ?? undefined} />
      </span>
    );
  }

  const display = (
    <input
      ref={displayRef}
      key="display"
      type="text"
      role="spinbutton"
      readOnly
      tabIndex={reason.disabled ? undefined : tabIndex}
      disabled={reason.disabled}
      className="cv-cell-editor__input cv-focus-ring"
      size={Math.max(shown.length, 1) + 1}
      value={shown}
      aria-label={label}
      aria-valuetext={shown}
      aria-disabled={reason.ariaDisabled}
      aria-describedby={reason.ariaDescribedBy}
      onKeyDown={onDisplayKeyDown}
      onDoubleClick={open}
    />
  );
  return (
    <span {...root}>
      <span className="cv-cell-editor__well">
        {reason.gated ? (
          <span className="cv-cell-editor__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        {reason.gated ? <ReasonEcho text={reason.reason}>{display}</ReasonEcho> : display}
      </span>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </span>
  );
}
