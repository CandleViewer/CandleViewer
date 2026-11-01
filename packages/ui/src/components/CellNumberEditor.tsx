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
import { useDisabledReason, useGatedAnnounce } from "./internal/disabledReason.js";
import { FieldMessage } from "./internal/fieldParts.js";

/** What the step is: a price's or a trigger's tick, or a quantity's lot (E29-D02 §7). */
export type CellEditorUnit = "tick" | "lot";

/**
 * The editor's words: E30's merged validation strings where E30 has them (E30-D06, owner E30-D02 §14), CMP-008's
 * and D02's own, and the rest PROPOSED with their owner named.
 */
export interface CellNumberEditorCopy {
  /** The step hint (E29-D02 §7, D02:303): "Step 0.1 · ↑/↓ one tick · Shift ten". */
  readonly stepHint: (step: string, unit: CellEditorUnit) => string;
  /** CMP-008's words for text that is no number. */
  readonly notANumber: string;
  /** A price or a trigger at zero or below. PROPOSED to E30-D02 §14's owner, E29-D03 informed (BQ-11). */
  readonly notPositive: string;
  /**
   * A price off its tick, never rounded: `ticket.order.v.price.tick` (E30-D06, merged; E30-D02:373). A Trigger
   * cell's host passes `CELL_TRIGGER_OFF_TICK` here.
   */
  readonly offTick: (tick: string) => string;
  /**
   * A quantity off its lot, at zero or below its lowest, and any value below `min`: `ticket.order.v.qty.lot`
   * (E30-D06, merged; E30-D02:374).
   */
  readonly offLot: (min: string, lot: string) => string;
}

export const CELL_NUMBER_EDITOR_COPY: CellNumberEditorCopy = {
  stepHint: (step, unit) => `Step ${step} · ↑/↓ one ${unit} · Shift ten`,
  notANumber: "Enter a number.",
  notPositive: "Enter a number above zero.",
  offTick: (tick) => `Price must be a multiple of ${tick}.`,
  offLot: (min, lot) => `Minimum ${min}, step ${lot}.`,
};

/**
 * A trigger off its tick, the Trigger cell's `offTick`. PROPOSED to E30-D02 §14's owner, E29-D03 informed: E30
 * words a price's tick only.
 */
export const CELL_TRIGGER_OFF_TICK = (tick: string): string =>
  `Trigger must be a multiple of ${tick}.`;

export interface CellNumberEditorProps {
  /** The value's name, which the host makes the row's ("Price, ETHUSDT Buy on Sub-2"); the shown value follows it. */
  label: string;
  /** The live, confirmed value: the wire's decimal string. Shown until an edit starts, and under the editor during it. */
  value: string;
  /** The tick or the lot as a decimal string above zero ("0.1", "0.001"). */
  step: string;
  /** "tick" for a price or a trigger, "lot" for a quantity: the step hint's word, and CMP-100 or CMP-101. */
  unit: CellEditorUnit;
  /**
   * The lowest valid value, a quantity's floor (E29-D01 D7's lowest valid quantity; a fill raises it, D12): a step
   * down stops at it, and a typed value below it is refused.
   */
  min?: string;
  /** `Enter` on a valid value that differs from `value`: the typed decimal string, never rounded, never a number. */
  onCommit: (value: string) => void;
  /**
   * The host's own verdict on a value the editor accepts (E29-D01 D7: a stop's quantity that leaves size bare): a
   * refusal, drawn as one (`aria-invalid`, the danger boundary and its words).
   */
  validate?: (value: string) => string | undefined;
  /**
   * T2 on the commit of an open editor (E29-D02 §7, board 16; E09-D09 §2.1 step 4): the reason a valid, changed
   * value may not be sent now (a quantity up under the kill switch, an unarmed LIVE amend), or `undefined` to send
   * it. A pure function of the value. `Enter` then sends nothing and shows the reason 2a under the editor with one
   * polite announcement, never `aria-invalid`; `Esc` restores the live value.
   */
  commitGate?: (value: string) => string | undefined;
  /** Controlled editing: the host opens the editor from its grid cell or its row menu. */
  editing?: boolean;
  /**
   * Every open, close and discarded edit, controlled or not. From `true` to `false` the host suspends its grid keys
   * and its trading hotkeys (E29-D01 D12, E29-D02 §7), and a controlled host applies the change.
   */
  onEditingChange?: (editing: boolean) => void;
  /** The description during an edit (E29-D02 §7: "Editing the price. 2,500.00 stays live until you press Enter."). */
  editingDescription?: string;
  /**
   * Plain disabled, with no reason to give: native, dimmed and out of the Tab order. SCR-063 has no use for it: a
   * cell that may not be edited is T2 with its reason (#912 BQ-9).
   */
  disabled?: boolean;
  /**
   * The reason the edit is denied: disabled with a visible reason (T2, E09-D09 §2.2). The value keeps its look; the
   * reason is its description and is re-shown 2a under the cell when `Enter`, `F2` or a double-click is refused.
   */
  disabledReason?: string;
  /**
   * The id of the node in which the host already shows `disabledReason` (E09-D09 §2.2 "one notice, many pointers",
   * G-T2.5: a Viewer's or view-as panel-header notice, D02:431–435): the value is described by it, and the editor
   * renders no reason node of its own.
   */
  disabledReasonId?: string;
  density?: "comfortable" | "compact";
  /** A roving grid's stop: `-1` for a cell that is not its stop. */
  tabIndex?: 0 | -1;
  copy?: Partial<CellNumberEditorCopy>;
}

const isChord = (event: KeyboardEvent): boolean => event.ctrlKey || event.metaKey || event.altKey;

/** The caret's keys: while the editor is open they move its caret, and never the grid (E29-D02 §11.1 binds them). */
const CARET_KEYS: ReadonlySet<string> = new Set(["ArrowLeft", "ArrowRight", "Home", "End"]);

/** The live value as the cell shows it: grouped at the step's places or the value's own, never fewer (no rounding). */
function shownText(value: StepDecimal | null, raw: string, step: StepDecimal): string {
  if (value === null) return raw;
  return formatDecimal(toText(widen(value, step.scale)))?.text ?? raw;
}

/** The CMP-019 `lock` that leads a reason shown 2a, named "Not available" (E09-D09 §2.2, G-T2.1d). */
function Lock(): JSX.Element {
  return (
    <span className="cv-cell-editor__lock">
      <Icon name="lock" decorative={false} label="Not available" />
    </span>
  );
}

/**
 * The cell use of CMP-100 PriceInput and CMP-101 QtyInput (E29-S02 BQ-11; E29-D02 §7): one grid cell's value,
 * edited in place as the wire's decimal string. At rest it is a read-only spin button showing the live value;
 * `Enter`, `F2` or a double-click opens the editor, a fresh field that takes focus. `↑` / `↓` step one tick or lot,
 * `Shift` ten, on a scaled BigInt; `Enter` alone commits a valid value, and `Esc`, `Tab` or a click elsewhere
 * restores the live value. Nothing is rounded: a value off the step is refused with its reason. While open, the
 * editor keeps `←`, `→`, `Home` and `End` for its caret; every other grid key and every trading hotkey is the host's
 * to suspend from `onEditingChange(true)` until `onEditingChange(false)` (E29-D01 D12).
 *
 * T2 (E09-D09 §2.2; E29-D04 §4.1, D02:429): a gated cell keeps its value's own look, with no glyph among the
 * numerals and no echo, its name and its Tab stop, with `aria-disabled` and the reason as its description (its own
 * hidden node, or the host's notice through `disabledReasonId`). A refused `Enter`, `F2` or double-click sends
 * nothing and re-shows the reason 2a under the cell, the lock leading it, with one polite announcement (G-T2.3);
 * `commitGate` refuses an open editor's commit the same way, under the editor. A gate that comes or goes never
 * remounts the focused value. The step hint, the live value, a refusal and a reason overlay the rows under the
 * cell, out of the flow, so a windowed row keeps its height (D01 D13 b).
 */
export function CellNumberEditor({
  label,
  value,
  step,
  unit,
  min,
  onCommit,
  validate,
  commitGate,
  editing: editingProp,
  onEditingChange,
  editingDescription,
  disabled,
  disabledReason,
  disabledReasonId,
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
  const reason = useDisabledReason(disabled, disabledReason, disabledReasonId);
  const announce = useGatedAnnounce();
  const blocked = reason.gated || reason.disabled || live === null;
  const [own, setOwn] = useState(false);
  const held = editingProp ?? own;
  const editing = held && !blocked;
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  /** A commit the gate refused: its reason stays under the editor until the text changes (G-T2.3). */
  const [gatedPress, setGatedPress] = useState(false);
  /** A refused activation at rest: the reason stays under the cell until focus leaves it (G-T2.3). */
  const [reshown, setReshown] = useState(false);
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
  const gateId = useId();
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
      setGatedPress(false);
    }
  }
  // A gate that lifts takes its re-shown reason with it: one that comes back shows nothing until a press.
  if (reshown && !reason.gated) setReshown(false);

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
      setReshown(true); // G-T2.3: nothing changes; the reason is re-shown 2a and said once more, politely
      announce(reason.reason);
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
    const lowest = min ?? step;
    switch (check.kind) {
      case "empty":
      case "not_a_number":
        return copy.notANumber;
      case "not_positive":
        return unit === "lot" ? copy.offLot(lowest, step) : copy.notPositive;
      case "off_step":
        return unit === "lot" ? copy.offLot(lowest, step) : copy.offTick(step);
      case "below_min":
        return copy.offLot(lowest, step);
    }
  }

  /** The gate's reason for typed text that would be sent, else `undefined` (no gate, junk, or the live value). */
  function gateOf(text: string): string | undefined {
    if (commitGate === undefined) return undefined;
    const check = checkTyped(text, stepValue, minValue);
    if (check.kind !== "ok" || (live !== null && compareDecimal(check.value, live) === 0)) {
      return undefined;
    }
    const said = commitGate(toText(check.value))?.trim();
    return said === "" ? undefined : said;
  }

  function commit(): void {
    setGatedPress(false);
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
    const gate = gateOf(draft);
    if (gate !== undefined) {
      // T2 on the commit: nothing is sent, the reason shows 2a under the editor and is said once, politely
      setError(null);
      setGatedPress(true);
      announce(gate);
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
    setGatedPress(false);
  }

  const onEditKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.nativeEvent.isComposing || isChord(event)) return;
    if (CARET_KEYS.has(event.key)) {
      event.stopPropagation(); // the caret moves (no preventDefault); the grid never moves under an open edit
      return;
    }
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
    setGatedPress(false);
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
    const gateReason = gatedPress ? gateOf(draft) : undefined;
    const describedBy = [
      editingDescription === undefined ? "" : descriptionId,
      hintId,
      messageId,
      gateId,
    ]
      .filter((id) => id !== "")
      .join(" ");
    // The note under the editor is not a CMP-016 tooltip: an open tooltip takes the first `Esc` as its own layer
    // (conventions 32), and here `Esc` must restore the live value at once (D01 D12).
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
        <span className="cv-cell-editor__note">
          <span className="cv-cell-editor__live" aria-hidden="true">
            {shown}
          </span>
          <FieldMessage id={messageId} message={error ?? undefined} />
          <span
            className="cv-cell-editor__reason"
            data-shown={gateReason === undefined ? undefined : ""}
          >
            {gateReason === undefined ? null : <Lock />}
            <span id={gateId}>{gateReason}</span>
          </span>
          <span id={hintId} className="cv-cell-editor__hint">
            {copy.stepHint(step, unit)}
          </span>
        </span>
        {editingDescription === undefined ? null : (
          <span id={descriptionId} className="cv-visually-hidden">
            {editingDescription}
          </span>
        )}
      </span>
    );
  }

  const reasonShown = reshown && reason.gated;
  // One tree whether gated or not: a gate that comes or goes on the focused value never remounts it (`05` §3.4.3).
  return (
    <span {...root}>
      <span className="cv-cell-editor__well">
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
          onBlur={() => setReshown(false)}
        />
      </span>
      {reason.gated && !reason.external ? (
        // The reason node, in the DOM from the gate's first render and the value's description: hidden, and shown
        // 2a in place (never re-mounted) once a refused activation re-shows it.
        <span className={reasonShown ? "cv-cell-editor__note" : "cv-visually-hidden"}>
          <span className="cv-cell-editor__reason" data-shown={reasonShown ? "" : undefined}>
            {reasonShown ? <Lock /> : null}
            <span id={reason.reasonId}>{reason.reason}</span>
          </span>
        </span>
      ) : null}
      {reasonShown && reason.external ? (
        // The host's notice is the description: this is only its re-show at the point of action
        <span className="cv-cell-editor__note" aria-hidden="true">
          <span className="cv-cell-editor__reason" data-shown="">
            <Lock />
            <span>{reason.reason}</span>
          </span>
        </span>
      ) : null}
    </span>
  );
}
