// E13-S01 (#423) S4: CMP-242 SchemaForm, feature-local (D02 G-3; `15` CMP-242). It renders the
// closed subset the S1 parser accepts (SR-E13-09; D02 D10) and nothing else: a refused schema is
// one safe error, a property outside the subset is the deck's read-only row (d02.12.r21, frozen
// (1)). The control for a field is chosen by a static `switch` over the parser's closed `kind`,
// never by a name read from the payload; titles and options render as React text, never markup.
// The number field is local, not CMP-008: CMP-008 rounds typed text to its precision and words
// its own range message, where D11 refuses a typed 2.25 with the deck's sentence (G-row on #423).
import { Callout, Icon, Select, Toggle } from "@candleviewer/ui";
import { useId, type JSX, type KeyboardEvent } from "react";
import { rangeHelp, SETTINGS, UNSUPPORTED_PARAM, validationText } from "../copy";
import type { NumberField, ParamField, SchemaResult, ValueRule } from "../model/schema";
import { isFieldEdited, numberText, stepFrom, type Draft, type DraftValue } from "./draft";
import "./settings.css";

export interface SchemaFormProps {
  readonly schema: SchemaResult;
  readonly draft: Draft;
  readonly errors: ReadonlyMap<string, ValueRule>;
  readonly onChange: (name: string, value: DraftValue) => void;
  /** `Enter` in a number field (D02 §11.1: Apply when valid, else the message again). */
  readonly onEnter: (name: string) => void;
  /** Registers each field's focus target, for F-10's "focus the first invalid field". */
  readonly fieldRef?: (name: string, element: HTMLElement | null) => void;
}

interface RowProps {
  readonly spec: ParamField;
  readonly id: string;
  readonly form: SchemaFormProps;
}

/** The dot glyph and the word (D14): never the colour alone; beside the label, not in the name. */
function Edited(): JSX.Element {
  return (
    <span className="cv-ind-settings__edited">
      <span className="cv-ind-settings__dot" aria-hidden="true" />
      {SETTINGS.edited}
    </span>
  );
}

function Message({ id, text }: { readonly id: string; readonly text: string | undefined }) {
  return (
    <div id={id} className="cv-field__message" aria-live="polite" aria-atomic="true">
      {text === undefined ? null : (
        <>
          <span className="cv-field__glyph">
            <Icon name="danger" />
          </span>
          <span>{text}</span>
        </>
      )}
    </div>
  );
}

/** `↑/↓` by step, `PageUp/PageDown` ×10 (D02 D10; K35-02). */
const STEP_KEYS: ReadonlyMap<string, number> = new Map([
  ["ArrowUp", 1],
  ["ArrowDown", -1],
  ["PageUp", 10],
  ["PageDown", -10],
]);

function NumberRow({ spec, id, form }: RowProps & { readonly spec: NumberField }): JSX.Element {
  const raw = form.draft.get(spec.name);
  const text = typeof raw === "string" ? raw : "";
  const rule = form.errors.get(spec.name);
  const message = rule === undefined ? undefined : validationText(spec, rule);
  const valid = rule === undefined ? Number(text) : undefined;
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.nativeEvent.isComposing) return;
    const times = STEP_KEYS.get(event.key);
    if (event.key === "Enter") {
      event.preventDefault();
      form.onEnter(spec.name);
    } else if (times !== undefined) {
      event.preventDefault();
      form.onChange(spec.name, numberText(stepFrom(spec, raw, times)));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      form.onChange(spec.name, numberText(event.key === "Home" ? spec.minimum : spec.maximum));
    }
  };
  return (
    <div className="cv-formfield" data-cmp="CMP-040">
      <span className="cv-ind-settings__label">
        <label id={`${id}-label`} htmlFor={id} className="cv-formfield__label">
          {spec.title}
        </label>
        {isFieldEdited(spec, raw) ? <Edited /> : null}
      </span>
      <div className="cv-formfield__body">
        <div className="cv-field" data-invalid={rule === undefined ? undefined : ""}>
          <input
            ref={(el) => form.fieldRef?.(spec.name, el)}
            id={id}
            type="text"
            role="spinbutton"
            inputMode="decimal"
            autoComplete="off"
            spellCheck={false}
            className="cv-field__input cv-field__input--num"
            value={text}
            aria-valuemin={spec.minimum}
            aria-valuemax={spec.maximum}
            aria-valuenow={valid}
            aria-valuetext={text === "" ? undefined : text}
            aria-invalid={rule === undefined ? undefined : true}
            aria-describedby={`${id}-error ${id}-help`}
            onChange={(event) => form.onChange(spec.name, event.target.value)}
            onKeyDown={onKeyDown}
          />
        </div>
        <Message id={`${id}-error`} text={message} />
        <div id={`${id}-help`} className="cv-formfield__line">
          {rangeHelp(spec)}
        </div>
      </div>
    </div>
  );
}

function Row({ spec, id, form }: RowProps): JSX.Element {
  const raw = form.draft.get(spec.name);
  const rule = form.errors.get(spec.name);
  switch (spec.kind) {
    case "integer":
    case "number":
      return <NumberRow spec={spec} id={id} form={form} />;
    case "enum":
      return (
        <div className="cv-formfield" data-cmp="CMP-040">
          <span className="cv-ind-settings__label">
            <span id={`${id}-label`} className="cv-formfield__label">
              {spec.title}
            </span>
            {isFieldEdited(spec, raw) ? <Edited /> : null}
          </span>
          <div className="cv-formfield__body" ref={(el) => form.fieldRef?.(spec.name, el)}>
            <Select
              aria-labelledby={`${id}-label`}
              options={spec.options.map((option) => ({ value: option, label: option }))}
              value={typeof raw === "string" ? raw : undefined}
              onChange={(value) => form.onChange(spec.name, value)}
              invalid={rule !== undefined}
              {...(rule === undefined ? {} : { errorMessage: validationText(spec, rule) })}
            />
          </div>
        </div>
      );
    case "boolean":
      return (
        <div
          className="cv-formfield"
          data-cmp="CMP-040"
          ref={(el) => form.fieldRef?.(spec.name, el)}
        >
          <Toggle
            label={spec.title}
            checked={raw === true}
            onChange={(checked) => form.onChange(spec.name, checked)}
          />
          {isFieldEdited(spec, raw) ? <Edited /> : null}
        </div>
      );
    case "unsupported":
      return (
        <div className="cv-formfield" data-cmp="CMP-040">
          <span className="cv-formfield__label">{spec.title}</span>
          <p className="cv-formfield__line">{UNSUPPORTED_PARAM}</p>
        </div>
      );
  }
}

/** CMP-242: the Inputs tab's form, in the descriptor's property order (D02 D10). */
export function SchemaForm(props: SchemaFormProps): JSX.Element {
  const base = useId();
  const { schema } = props;
  if (!schema.ok) {
    // One safe error: the payload's words are never shown (SR-E13-09). Rendered in the first
    // commit, with no effect or timer, so it is on screen within D06's 100 ms by construction.
    return <Callout tone="warning" live="polite" title={SETTINGS.schemaRefused} />;
  }
  if (schema.fields.length === 0)
    return <p className="cv-ind-settings__empty">{SETTINGS.noParams}</p>;
  return (
    <div className="cv-ind-settings__fields" data-cmp="CMP-242">
      {schema.fields.map((spec, index) => (
        <Row key={spec.name} spec={spec} id={`${base}-f${index}`} form={props} />
      ))}
    </div>
  );
}
