import type { generated } from "@candleviewer/protocol";
import { useEffect, useId, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { Icon } from "../icons/Icon.js";
import { cx } from "./internal/cx.js";
import { ReasonText } from "./internal/disabledReason.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { focusFieldInput, useRefusalAnnounce } from "./internal/fieldParts.js";
import { useLayer, useLayerPortal } from "./internal/layers.js";
import { useAnchoredPosition } from "./internal/useAnchoredPosition.js";

type VocabularySignal = generated.rest.components["schemas"]["RuleVocabulary"]["signals"][number];

/** The seven picker categories (E36-D01 R2, `15` CMP-157) in the order the groups take: `replay` last. */
export const METRIC_CATEGORIES = [
  "price",
  "orderflow",
  "book",
  "derivatives",
  "position",
  "account",
  "replay",
] as const;

export type MetricCategory = (typeof METRIC_CATEGORIES)[number];

/** One served signal as the picker shows it: the host maps the vocabulary and derives the category. */
export interface MetricPickerOption {
  /** The signal's id: what a choice passes to `onChange`. */
  readonly id: string;
  /** The signal's `display_name`. */
  readonly label: string;
  /** Line 1 reads "label · unit"; a unitless signal shows the label alone. */
  readonly unit?: string | undefined;
  /** Line 2. */
  readonly description: string;
  readonly category: MetricCategory;
  /** Line 1 carries `estimatedText`, and the option's name is `estimatedName(label)`. */
  readonly estimated: boolean;
  /** `false`: the option is reached and explained (`unavailableText`), never chosen. */
  readonly available: boolean;
  /** The served `unavailable_reason`, for the host's `unavailableText`. */
  readonly unavailableReason?: string | undefined;
  /** The served `recorder_action`: an unavailable option that has one offers Start recording. */
  readonly recorderAction?: VocabularySignal["recorder_action"];
}

export interface MetricPickerComboboxProps {
  /** The chosen signal's id, `null` before a choice; the well shows its label (else the id itself). */
  readonly value: string | null;
  /** A choice passes the option's id; an unavailable option is never chosen. */
  readonly onChange: (id: string, option: MetricPickerOption) => void;
  readonly options: readonly MetricPickerOption[];
  /** One category's group alone; omitted, every category with a match, in `METRIC_CATEGORIES` order. */
  readonly category?: MetricCategory | undefined;
  /** Start recording on an unavailable option: one press, one call, with that option. */
  readonly onStartRecording: (option: MetricPickerOption) => void;
  /**
   * T2 for Start recording (E09-D09 §2.2): the host's §3.1 sentence, e.g. `rbac.owner_only` with the verb "start
   * recording". The stop keeps its label behind the CMP-019 `lock`, is reached and described, and never calls.
   */
  readonly startRecordingReason?: string | undefined;
  /** A group's heading with its count of shown options. */
  readonly groupLabel: (category: MetricCategory, count: number) => string;
  /** The word after an estimated option's unit (E36-D05 `rules.editor.row.estimated`). */
  readonly estimatedText: string;
  /** An estimated option's accessible name (E36-D05 `rules.editor.name.estimated`). */
  readonly estimatedName: (label: string) => string;
  /**
   * An unavailable option's clause (E36-D05 `rules.editor.row.unavailable`). With a recorder action its last
   * `startRecordingText` words are the Start recording stop; without them the stop follows the clause.
   */
  readonly unavailableText: (option: MetricPickerOption) => string;
  /** The stop's label (E36-D05 `rules.editor.row.start_recording`). */
  readonly startRecordingText: string;
  /** Said politely once per settled query (E36-D05 `rules.editor.announce.metrics`). */
  readonly countText: (count: number) => string;
  /** The status row, and what is said, when a query matches nothing. */
  readonly noResultsText: string;
  readonly placeholder?: string;
  readonly disabled?: boolean;
  /** T2 for the whole picker (CMP-079 hands it down): the lock leads the value and the list never opens. */
  readonly disabledReason?: string | undefined;
  /** The name outside a CMP-040 FormField, given to the input and the list. */
  readonly "aria-label"?: string;
  readonly "aria-labelledby"?: string;
  /** The rest after the last keystroke before the query settles, ms; default 500 (CMP-048's). */
  readonly settleMs?: number;
}

const SETTLE_MS = 500;
/** The keys a gated input refuses besides the editing ones: those that would open the list. */
const GATED_KEYS: ReadonlySet<string> = new Set(["ArrowDown", "ArrowUp"]);
/** The active stop: an option (-1: the text) and its part, the option itself (0) or its Start recording (1). */
type Active = { readonly index: number; readonly part: 0 | 1; readonly pointer: boolean };
const TEXT: Active = { index: -1, part: 0, pointer: false };

/** A query matches the label or the description (E36-D02 §7: type-ahead over both), case-insensitively. */
const matches = (option: MetricPickerOption, query: string): boolean =>
  query === "" ||
  option.label.toLowerCase().includes(query) ||
  option.description.toLowerCase().includes(query);

const hasStop = (option: MetricPickerOption | undefined): option is MetricPickerOption =>
  option !== undefined && !option.available && option.recorderAction !== undefined;

/** The label with its matched part in `type.ui.body-strong`: weight, not colour (CMP-048's mark). */
function marked(label: string, query: string): JSX.Element | string {
  const at = query === "" ? -1 : label.toLowerCase().indexOf(query);
  if (at < 0) return label;
  const end = at + query.length;
  return (
    <>
      {label.slice(0, at)}
      <span className="cv-combobox__match">{label.slice(at, end)}</span>
      {label.slice(end)}
    </>
  );
}

/** The clause around its stop: the stop is the clause's last `action` words, else it follows the clause. */
function aroundStop(clause: string, action: string): readonly [string, string] {
  const at = action === "" ? -1 : clause.lastIndexOf(action);
  return at < 0 ? [`${clause} `, ""] : [clause.slice(0, at), clause.slice(at + action.length)];
}

/**
 * CMP-157: CMP-048's combobox pattern over the metric vocabulary (E36-D02 §7). Focus stays in the input and
 * `aria-activedescendant` names the active stop. The options sit in the seven category groups (`role="group"`,
 * each named by its heading with its count), `replay` last. Line 1 reads "label · unit", then the estimated word
 * (a text node), then an unavailable option's clause; line 2 is the description. An unavailable option is
 * `aria-disabled`, arrow-reachable and never chosen; its Start recording is a second stop inside the row, reached
 * by `→` and left by `←`, and one press is one `onStartRecording` call (none while it is T2). Typing waits for the
 * settle; the count, or the no-results sentence, is said politely once per settled query.
 */
export function MetricPickerCombobox(props: MetricPickerComboboxProps): JSX.Element {
  const { value, options, category, settleMs = SETTLE_MS } = props;
  const control = useFieldControl(props.disabled, props.disabledReason, false, undefined);
  const { reason } = control;
  const unavailable = reason.gated || reason.disabled;
  const gate = props.startRecordingReason?.trim() || undefined;
  const ariaLabel = props["aria-label"];
  const ariaLabelledBy = props["aria-labelledby"];
  const labelledBy =
    ariaLabelledBy ?? (ariaLabel === undefined ? control.field?.labelId : undefined);
  const listId = useId();
  const portalRoot = useLayerPortal();
  const well = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  // The typed query; null while not editing, when the well shows the chosen option's label.
  const [text, setText] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(TEXT);
  const [settled, setSettled] = useState(true);
  // A refused press says its reason; the count re-keys the node, so every press is said again.
  const [recall, setRecall] = useState<{ readonly text: string; readonly n: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const query = (text ?? "").trim().toLowerCase();
  let start = 0;
  const groups = METRIC_CATEGORIES.flatMap((c) => {
    const list =
      category === undefined || c === category
        ? options.filter((o) => o.category === c && matches(o, query))
        : [];
    if (list.length === 0) return [];
    const group = { category: c, list, start };
    start += list.length;
    return [group];
  });
  const all = groups.flatMap((g) => g.list);
  const none = all.length === 0 && query !== "";
  const expanded = open && settled && !unavailable && (all.length > 0 || none);
  const current = expanded && active.index < all.length ? active.index : -1;
  // Start recording stays active only while its option still offers it (the host may refresh the options).
  const part = current >= 0 && hasStop(all[current]) ? active.part : 0;
  // Said once per settled query: the region empties on a keystroke and fills as the query settles.
  const said =
    !open || !settled ? undefined : none ? props.noResultsText : props.countText(all.length);
  const chosen = options.find((o) => o.id === value);
  const optionId = (index: number): string => `${listId}-${String(index)}`;

  const close = (): void => {
    clearTimeout(timer.current);
    setSettled(true);
    setOpen(false);
    setActive(TEXT);
    setRecall(null);
  };
  const leave = (): void => {
    close();
    setText(null); // leaving never chooses: the well shows the chosen label again
  };
  const edit = (next: string): void => {
    setText(next);
    close(); // a fresh query: no timer, no active option, nothing recalled; then it opens
    setSettled(false);
    setOpen(true);
    timer.current = setTimeout(() => setSettled(true), settleMs);
  };
  const say = (words: string): void =>
    setRecall((prev) => ({ text: words, n: (prev?.n ?? 0) + 1 }));
  const choose = (index: number): void => {
    const option = all[index];
    if (option === undefined) return;
    if (!option.available) return say(props.unavailableText(option)); // E09-D09 §9.3: nothing staged
    props.onChange(option.id, option);
    leave();
  };
  const record = (index: number): void => {
    const option = all[index];
    if (!hasStop(option)) return;
    if (gate !== undefined) return say(gate);
    props.onStartRecording(option);
  };
  const move = (index: number, to: 0 | 1, pointer: boolean): void => {
    if (index !== current || to !== part) setActive({ index, part: to, pointer });
  };

  const handleKey = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.nativeEvent.isComposing || unavailable) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey) return; // chords are the host's
    const { key, altKey } = event;
    if (key === "ArrowDown" || key === "ArrowUp") {
      event.preventDefault();
      if (altKey && key === "ArrowUp") return close();
      // An arrow opens at once: the query settles now, and a pending settle is dropped.
      clearTimeout(timer.current);
      setSettled(true);
      setOpen(true);
      if (altKey) return; // Alt+↓ opens without moving
      // ↓ from the text reaches the first option; ↑ on the first returns to the text; no wrap.
      const index = key === "ArrowDown" ? Math.min(current + 1, all.length - 1) : current - 1;
      setActive({ index: Math.max(index, -1), part: 0, pointer: false });
    } else if ((key === "ArrowRight" || key === "ArrowLeft") && current >= 0 && !altKey) {
      // The option's second stop: → reaches Start recording, ← returns; on the text they move the caret.
      const to = key === "ArrowRight" ? 1 : 0;
      if (to === part || (to === 1 && !hasStop(all[current]))) return;
      event.preventDefault();
      setActive({ index: current, part: to, pointer: false });
    } else if ((key === "Home" || key === "End") && current >= 0 && !altKey) {
      event.preventDefault(); // within an open list they jump (E36-D02 §7); on the text, the caret's
      setActive({ index: key === "Home" ? 0 : all.length - 1, part: 0, pointer: false });
    } else if (key === "Enter" && current >= 0 && !altKey) {
      event.preventDefault(); // with none active, Enter is the host's
      if (part === 1) record(current);
      else choose(current);
    } else if (key === "Escape") {
      // The list is the topmost layer and this is its own handler: it stops here; a second Esc bubbles.
      if (expanded) {
        event.preventDefault();
        event.stopPropagation();
      }
      close();
    }
  };

  // A key move scrolls the active row into view; a hover never moves the list under the pointer.
  useEffect(() => {
    if (current >= 0 && !active.pointer)
      document
        .getElementById(`${listId}-${String(current)}`)
        ?.closest(".cv-select__row")
        ?.scrollIntoView({ block: "nearest" });
  }, [active, current, listId]);
  useEffect(() => () => clearTimeout(timer.current), []);
  useAnchoredPosition({
    open: expanded,
    reference: well,
    floating: popup,
    side: "bottom",
    fit: true,
  });
  useLayer(expanded, { element: popup, modal: false, onEscape: close });
  const refusal = useRefusalAnnounce(reason, { onKeyDown: handleKey, onBlur: leave }, GATED_KEYS);

  const row = (option: MetricPickerOption, index: number): JSX.Element => {
    const id = optionId(index);
    const stop = hasStop(option);
    const clause = option.available ? undefined : props.unavailableText(option);
    const [before, after]: readonly [string, string] =
      clause === undefined
        ? ["", ""]
        : stop
          ? aroundStop(clause, props.startRecordingText)
          : [clause, ""];
    const at = index === current;
    return (
      // CMP-009's row: a presentational pointer target around the option, its stop and its lines.
      <div
        key={option.id}
        role="presentation"
        className="cv-select__row cv-metricpicker__row"
        data-lines={2}
        data-active={at && part === 0 ? "" : undefined}
        data-unavailable={option.available ? undefined : ""}
        onMouseMove={() => move(index, 0, true)}
        onClick={() => {
          move(index, 0, true);
          choose(index);
        }}
      >
        <div className="cv-select__body">
          <div className="cv-metricpicker__line">
            <span
              id={id}
              role="option"
              aria-label={option.estimated ? props.estimatedName(option.label) : option.label}
              aria-selected={at && part === 0 ? true : undefined}
              aria-disabled={option.available ? undefined : true}
              aria-describedby={cx(
                option.unit && `${id}-unit`,
                clause !== undefined && `${id}-clause`,
                `${id}-desc`,
              )}
            >
              <span className="cv-metricpicker__label">{marked(option.label, query)}</span>
              {option.unit ? (
                <>
                  <span aria-hidden="true">{" · "}</span>
                  <span id={`${id}-unit`}>{option.unit}</span>
                </>
              ) : null}
              {option.estimated ? (
                <span className="cv-metricpicker__word">{` ${props.estimatedText}`}</span>
              ) : null}
              {clause === undefined ? null : (
                <span className="cv-metricpicker__word">{` ${before}`}</span>
              )}
            </span>
            {stop ? (
              // The stop's own pointer target: a press here is Start recording, never the row's choice.
              <span
                role="presentation"
                onMouseMove={(event) => {
                  event.stopPropagation();
                  move(index, 1, true);
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  move(index, 1, true);
                  record(index);
                }}
              >
                <span
                  id={`${id}-rec`}
                  role="option"
                  className="cv-metricpicker__record"
                  data-active={at && part === 1 ? "" : undefined}
                  data-gated={gate === undefined ? undefined : ""}
                  aria-selected={at && part === 1 ? true : undefined}
                  aria-disabled={gate === undefined ? undefined : true}
                  aria-describedby={gate === undefined ? undefined : `${id}-why`}
                >
                  {gate === undefined ? null : (
                    // Inside an option the glyph is presentational: `aria-disabled` and the reason carry T2.
                    <span className="cv-select__optlock">
                      <Icon name="lock" />
                    </span>
                  )}
                  {props.startRecordingText}
                </span>
              </span>
            ) : null}
            {after === "" ? null : (
              <span className="cv-metricpicker__word" aria-hidden="true">
                {after}
              </span>
            )}
          </div>
          {clause === undefined ? null : (
            // The clause whole, as the option's description: line 1 splits it around the stop.
            <div id={`${id}-clause`} className="cv-visually-hidden" aria-hidden="true">
              {clause}
            </div>
          )}
          <div id={`${id}-desc`} className="cv-metricpicker__desc" aria-hidden="true">
            {option.description}
          </div>
          {stop && gate !== undefined ? (
            <div id={`${id}-why`} className="cv-select__reason" aria-hidden="true">
              {gate}
            </div>
          ) : null}
        </div>
      </div>
    );
  };

  const list = (
    // A pointer surface: a press keeps focus in the input, which drives the list.
    <div
      ref={popup}
      role="presentation"
      className="cv-combobox__popup"
      onMouseDown={(event) => event.preventDefault()}
    >
      <div
        id={listId}
        role="listbox"
        tabIndex={-1}
        className="cv-combobox__list"
        aria-label={ariaLabel}
        aria-labelledby={labelledBy}
      >
        {groups.map((group) => (
          <div
            key={group.category}
            role="group"
            aria-labelledby={`${listId}-${group.category}`}
            className="cv-metricpicker__group"
          >
            <div id={`${listId}-${group.category}`} className="cv-metricpicker__head">
              {props.groupLabel(group.category, group.list.length)}
            </div>
            {group.list.map((option, i) => row(option, group.start + i))}
          </div>
        ))}
      </div>
      {/* No results is a status row, not an option: it follows the list, and its words reach the live region. */}
      {none ? (
        <div className="cv-combobox__status">
          <span>{props.noResultsText}</span>
        </div>
      ) : null}
    </div>
  );

  const activeId = current < 0 ? undefined : `${optionId(current)}${part === 1 ? "-rec" : ""}`;
  return (
    <div className="cv-field-root" data-cmp="CMP-157">
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        ref={well}
        className="cv-field"
        data-gated={reason.gated ? "" : undefined}
        data-disabled={reason.disabled ? "" : undefined}
        data-lead={reason.gated ? "" : undefined}
        onMouseDown={(event) => focusFieldInput(event, inputRef)}
      >
        {reason.gated ? (
          <span className="cv-field__lead cv-field__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        <input
          ref={inputRef}
          id={control.field?.controlId}
          type="text"
          role="combobox"
          className="cv-field__input"
          value={text ?? chosen?.label ?? value ?? ""}
          placeholder={props.placeholder}
          autoComplete="off"
          disabled={reason.disabled}
          readOnly={reason.gated}
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={expanded ? listId : undefined}
          aria-activedescendant={activeId}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          aria-describedby={control.describe()}
          aria-required={control.required}
          aria-disabled={reason.ariaDisabled}
          onChange={(event) => edit(event.target.value)}
          {...refusal.handlers}
        />
      </div>
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
      {refusal.status}
      {unavailable ? null : (
        <span className="cv-visually-hidden" role="status">
          {recall === null ? said : <span key={recall.n}>{recall.text}</span>}
        </span>
      )}
      {expanded && portalRoot !== null ? createPortal(list, portalRoot) : null}
    </div>
  );
}
