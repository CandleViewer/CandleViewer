import { useId, useState, type JSX } from "react";
import { Icon } from "../icons/Icon.js";
import type {
  AuditDiffFact,
  AuditDiffField,
  AuditDiffModel,
  AuditValue,
} from "./auditDiffModel.js";
import { AUDIT_VALUE_CUT } from "./auditDiffModel.js";
import { Button } from "./Button.js";
import { CopyButton } from "./CopyButton.js";

/** E42-D04 §14 `diff.*` (PROPOSED there), verbatim; `{…}` fills are the functions. */
export const AUDIT_DIFF_COPY = {
  before: "Before",
  after: "After",
  requested: "Requested",
  added: "Added",
  removed: "Removed",
  changed: "Changed",
  no_before: "— (no earlier state recorded)",
  not_sent: "not sent",
  overrides_kept: "not sent — the existing overrides stay",
  head_failed: "Not applied",
  head_intent: "Intent — the outcome is a separate record",
  result: "Recorded result",
  head_started: "Started — the result is a separate record",
  full: "Show full value",
  secret: "Secret — never recorded",
  secret_named: "Hidden — secret-named field",
  credential: "Redacted — it held a credential",
  oversize: "Too large to record — replaced when it was written",
  key_id_note: "finds the key; never pin it",
  none: "none",
  withheld: "Withheld — too large to show here",
  hidden: "Not shown in your view",
} as const;

/** `diff.head_failed` "Not applied — {reason}"; with no reason recorded, its words alone. */
const failedHead = (reason: string | undefined): string =>
  reason === undefined ? AUDIT_DIFF_COPY.head_failed : `${AUDIT_DIFF_COPY.head_failed} — ${reason}`;
/** `diff.unchanged_n` "{n} unchanged fields" / "1 unchanged field". */
const unchangedLabel = (n: number): string =>
  n === 1 ? "1 unchanged field" : `${n} unchanged fields`;
/** `diff.personal` "Personal data, hashed · {hex8}…". */
const personalWords = (hex8: string): string => `Personal data, hashed · ${hex8}…`;
/** `diff.inline` "changed from {a} to {b}" and `diff.inline_requested` "requested {b} (stored {a})". */
const inlineChanged = (a: string, b: string): string => `changed from ${a} to ${b}`;
const inlineRequested = (a: string | undefined, b: string): string =>
  a === undefined ? `requested ${b}` : `requested ${b} (stored ${a})`;

const pathText = (path: readonly string[]): string => path.join(" › ");

/**
 * A control's name in the diff: its visible words first (WCAG 2.5.3), then the field and the side it acts on, so two
 * Show full value or Copy buttons in one row never share a name (2.4.6). PROPOSED (no source composes them):
 * "Show full value of {path} ({term})" and "Copy {path} ({term})", the term Before, After or Requested.
 */
const controlName = (words: string, path: readonly string[], term: string | undefined): string =>
  // A function replacement: a recorded key is data, and `$&` in it must stay as written.
  `${words}${term === undefined ? "" : ` (${term})`}`.replace("{path}", () => pathText(path));

/** The words a value reads as: its text, or its kind's words; never a redacted value, which no kind carries. */
export function auditValueWords(value: AuditValue): string {
  switch (value.kind) {
    case "value":
    case "fingerprint":
    case "identifier":
      return value.text;
    case "personal":
      return personalWords(value.hex8);
    case "none":
      return value.note === undefined ? AUDIT_DIFF_COPY.none : AUDIT_DIFF_COPY[value.note];
    default:
      return AUDIT_DIFF_COPY[value.kind];
  }
}

/** The kinds that lead with the (decorative) lock: the redacted ones (§6). */
const LOCKED: ReadonlySet<AuditValue["kind"]> = new Set(["secret", "secret_named", "credential"]);

/** A long value: its first 120 characters, then Show full value (a disclosure, M4: a cut). */
function LongValue({ text, name }: { readonly text: string; readonly name: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <span id={id} className="cv-audit-diff__text">
        {open ? text : text.slice(0, AUDIT_VALUE_CUT)}
      </span>{" "}
      <Button
        variant="ghost"
        size="sm"
        iconLeft={open ? "chevron-down" : "chevron-right"}
        aria-label={name}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((was) => !was)}
        onKeyDown={(event) => {
          if (event.repeat && (event.key === "Enter" || event.key === " ")) event.preventDefault();
        }}
      >
        {AUDIT_DIFF_COPY.full}
      </Button>
    </>
  );
}

/** One value, by kind (E42-D04 §6's table); `term` is the side it stands under (Before, After, Requested), if any. */
function ValueView({
  value,
  path,
  term,
}: {
  readonly value: AuditValue;
  readonly path: readonly string[];
  readonly term?: string | undefined;
}): JSX.Element {
  const words = auditValueWords(value);
  const mono =
    (value.kind === "value" && value.numeric) ||
    value.kind === "fingerprint" ||
    value.kind === "identifier";
  return (
    <span className="cv-audit-diff__value" data-kind={value.kind} data-mono={mono ? "" : undefined}>
      {LOCKED.has(value.kind) ? (
        <span className="cv-audit-diff__lock">
          <Icon name="lock" />
        </span>
      ) : null}
      {value.kind === "value" && value.cut ? (
        <LongValue
          text={value.text}
          name={controlName(`${AUDIT_DIFF_COPY.full} of {path}`, path, term)}
        />
      ) : (
        words
      )}
      {value.kind === "fingerprint" || value.kind === "identifier" ? (
        <>
          {" "}
          <CopyButton value={value.text} label={controlName("Copy {path}", path, term)} />
        </>
      ) : null}
      {value.kind === "identifier" ? (
        <span className="cv-audit-diff__note"> {AUDIT_DIFF_COPY.key_id_note}</span>
      ) : null}
    </span>
  );
}

/** A field's term: its status word in its own column (state shape), then its path in mono. */
function Term({ field }: { readonly field: Pick<AuditDiffField, "path" | "status"> }): JSX.Element {
  return (
    <dt className="cv-audit-diff__term">
      {field.status === undefined ? null : (
        <span className="cv-audit-diff__status">{AUDIT_DIFF_COPY[field.status]} </span>
      )}
      <span className="cv-audit-diff__path">{pathText(field.path)}</span>
    </dt>
  );
}

/** A field with its Before and After (or Requested) pair, as a nested `dl` with visible terms. */
function FieldView({
  field,
  request,
}: {
  readonly field: AuditDiffField;
  readonly request: boolean;
}): JSX.Element {
  return (
    <div className="cv-audit-diff__field" data-status={field.status}>
      <Term field={field} />
      <dd className="cv-audit-diff__desc">
        <dl className="cv-audit-diff__values">
          {field.before === undefined ? null : (
            <div className="cv-audit-diff__pair">
              <dt>{AUDIT_DIFF_COPY.before}</dt>
              <dd>
                <ValueView value={field.before} path={field.path} term={AUDIT_DIFF_COPY.before} />
              </dd>
            </div>
          )}
          {field.after === undefined ? null : (
            <div className="cv-audit-diff__pair">
              <dt>{afterTerm(request)}</dt>
              <dd>
                <ValueView value={field.after} path={field.path} term={afterTerm(request)} />
              </dd>
            </div>
          )}
        </dl>
      </dd>
    </div>
  );
}

/** A field shown as one value: a fact, a result's field, an unchanged field; `term` its side, under a withheld pair. */
function FactView({
  fact,
  term,
}: {
  readonly fact: AuditDiffFact;
  readonly term?: string | undefined;
}): JSX.Element {
  return (
    <div className="cv-audit-diff__field">
      <Term field={fact} />
      <dd className="cv-audit-diff__desc">
        <ValueView value={fact.value} path={fact.path} term={term} />
      </dd>
    </div>
  );
}

/** The unchanged fields, folded (`diff.unchanged_n`): a disclosure, a cut both ways (M4). */
function Unchanged({ facts }: { readonly facts: readonly AuditDiffFact[] }): JSX.Element {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="cv-audit-diff__unchanged">
      <Button
        variant="ghost"
        size="sm"
        iconLeft={open ? "chevron-down" : "chevron-right"}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((was) => !was)}
        onKeyDown={(event) => {
          if (event.repeat && (event.key === "Enter" || event.key === " ")) event.preventDefault();
        }}
      >
        {unchangedLabel(facts.length)}
      </Button>
      {/* Collapsed, the list it controls is hidden, never an empty list in the tree. */}
      <dl id={id} className="cv-audit-diff__fields" hidden={!open}>
        {open ? facts.map((fact) => <FactView key={pathText(fact.path)} fact={fact} />) : null}
      </dl>
    </div>
  );
}

/** The second term: Requested for a request (§6: never After), else After. */
const afterTerm = (request: boolean): string =>
  request ? AUDIT_DIFF_COPY.requested : AUDIT_DIFF_COPY.after;

const headWords = (model: AuditDiffModel): string | undefined => {
  const head = model.head;
  if (head === undefined) return undefined;
  switch (head.kind) {
    case "failed":
      return failedHead(head.reason);
    case "intent":
      return AUDIT_DIFF_COPY.head_intent;
    case "started":
      return AUDIT_DIFF_COPY.head_started;
    default:
      return AUDIT_DIFF_COPY.result;
  }
};

/** The full form (row expansion, SCR-136): definition lists with visible Before / After (or Requested) terms. */
function FullDiff({ model }: { readonly model: AuditDiffModel }): JSX.Element {
  const head = headWords(model);
  const request = model.shape === "request";
  if (model.shape === "hidden") {
    return (
      <div className="cv-audit-diff" data-form="full" data-shape="hidden">
        <p className="cv-audit-diff__line">{AUDIT_DIFF_COPY.hidden}</p>
      </div>
    );
  }
  // A withheld state beside a served one reads Withheld once under its term, the other term listing the served fields
  // (§6 rules): Requested for a request, and a result's fields as its values; a request's or a record's facts follow.
  const withheld = model.before === "withheld" || model.after === "withheld";
  const result = model.shape === "result";
  const served = (side: "before" | "after"): AuditDiffFact[] =>
    result
      ? side === "after"
        ? [...model.facts]
        : []
      : model.fields.flatMap((field) => {
          const value = side === "before" ? field.before : field.after;
          return value === undefined ? [] : [{ path: field.path, value }];
        });
  return (
    <div className="cv-audit-diff" data-form="full" data-shape={model.shape}>
      {head === undefined ? null : <p className="cv-audit-diff__head">{head}</p>}
      {result && model.before === "none" ? (
        <p className="cv-audit-diff__line">{AUDIT_DIFF_COPY.no_before}</p>
      ) : null}
      {withheld ? (
        <>
          <dl className="cv-audit-diff__fields">
            {(["before", "after"] as const).map((side) => {
              const term = side === "before" ? AUDIT_DIFF_COPY.before : afterTerm(request);
              return model[side] === "none" ? null : (
                <div key={side} className="cv-audit-diff__field">
                  <dt className="cv-audit-diff__term">{term}</dt>
                  <dd className="cv-audit-diff__desc">
                    {model[side] === "withheld" ? (
                      <span className="cv-audit-diff__value" data-kind="withheld">
                        {AUDIT_DIFF_COPY.withheld}
                      </span>
                    ) : (
                      <dl className="cv-audit-diff__fields">
                        {served(side).map((fact) => (
                          <FactView key={pathText(fact.path)} fact={fact} term={term} />
                        ))}
                      </dl>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
          {result || model.facts.length === 0 ? null : (
            <dl className="cv-audit-diff__fields">
              {model.facts.map((fact) => (
                <FactView key={pathText(fact.path)} fact={fact} />
              ))}
            </dl>
          )}
        </>
      ) : model.fields.length === 0 && model.facts.length === 0 && model.unchanged.length === 0 ? (
        <p className="cv-audit-diff__line">
          <span className="cv-audit-diff__value" data-kind="none">
            {AUDIT_DIFF_COPY.none}
          </span>
        </p>
      ) : (
        <dl className="cv-audit-diff__fields">
          {model.fields.map((field) => (
            <FieldView key={pathText(field.path)} field={field} request={request} />
          ))}
          {model.facts.map((fact) => (
            <FactView key={pathText(fact.path)} fact={fact} />
          ))}
        </dl>
      )}
      {model.unchanged.length === 0 ? null : <Unchanged facts={model.unchanged} />}
    </div>
  );
}

/** One inline line: "value: OFF → ON", the arrow hidden and the line read "changed from OFF to ON". */
function InlineField({
  field,
  request,
}: {
  readonly field: AuditDiffField;
  readonly request: boolean;
}): JSX.Element {
  const path = pathText(field.path);
  const before = field.before === undefined ? undefined : auditValueWords(field.before);
  const after = field.after === undefined ? undefined : auditValueWords(field.after);
  if (request && after !== undefined) {
    const kept = field.after?.kind === "none" && field.after.note !== undefined;
    return (
      <li>
        {path}: {kept ? after : inlineRequested(before, after)}
      </li>
    );
  }
  if (field.status === "changed" && before !== undefined && after !== undefined) {
    return (
      <li>
        {path}: <span aria-hidden="true">{`${before} → ${after}`}</span>
        <span className="cv-visually-hidden">{inlineChanged(before, after)}</span>
      </li>
    );
  }
  const status =
    field.status === undefined || field.status === "changed"
      ? ""
      : `${AUDIT_DIFF_COPY[field.status]} `;
  return (
    <li>
      {status}
      {path}: {after ?? before ?? AUDIT_DIFF_COPY.none}
    </li>
  );
}

/** The inline form (compact contexts: SCR-122's summary, flag history): one line per field. */
function InlineDiff({ model }: { readonly model: AuditDiffModel }): JSX.Element {
  const head = headWords(model);
  const request = model.shape === "request";
  const words = (side: "before" | "after"): string | undefined =>
    model[side] === "withheld" ? AUDIT_DIFF_COPY.withheld : undefined;
  return (
    <ul className="cv-audit-diff" data-form="inline" data-shape={model.shape}>
      {model.shape === "hidden" ? <li>{AUDIT_DIFF_COPY.hidden}</li> : null}
      {head === undefined ? null : <li>{head}</li>}
      {model.shape === "result" && model.before === "none" ? (
        <li>{AUDIT_DIFF_COPY.no_before}</li>
      ) : null}
      {words("before") === undefined && words("after") === undefined ? null : (
        <li>{AUDIT_DIFF_COPY.withheld}</li>
      )}
      {model.fields.map((field) => (
        <InlineField key={pathText(field.path)} field={field} request={request} />
      ))}
      {model.facts.map((fact) => (
        <li key={pathText(fact.path)}>
          {pathText(fact.path)}: {auditValueWords(fact.value)}
        </li>
      ))}
    </ul>
  );
}

export interface AuditDiffProps {
  /** `auditDiffModel(entry)`: the renderer's only input (E42-D04 §6). */
  readonly model: AuditDiffModel;
  /** `full` (row expansion, SCR-136) or `inline` (compact contexts). */
  readonly form: "full" | "inline";
}

/**
 * CMP-173's diff part (E42-D04 D15, §6): the one diff language, rendered from `auditDiffModel` alone. The full form
 * is a `dl` per field, its path the term (after its Added, Removed or Changed word in the state shape) and a nested
 * `dl` with visible Before and After terms (Requested for a refused or intent record); the request's and the record's
 * facts as values; unchanged fields folded into a disclosure; a value past 120 characters behind Show full value. The
 * inline form is one line per field, its arrow hidden. A redacted kind shows its words after a decorative lock, and
 * no kind carries a value the server redacted. Fingerprints and identifiers take a CMP-033 Copy.
 */
export function AuditDiff({ model, form }: AuditDiffProps): JSX.Element {
  return form === "inline" ? <InlineDiff model={model} /> : <FullDiff model={model} />;
}
