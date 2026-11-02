import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FocusEvent,
  type FormEvent,
  type JSX,
  type KeyboardEvent,
} from "react";
import type { generated } from "@candleviewer/protocol";
import { AUDIT_ROW_COPY } from "./AuditRow.js";
import { Button } from "./Button.js";
import { Combobox, type ComboboxOption } from "./Combobox.js";
import { DatePicker } from "./DatePicker.js";
import { FormField } from "./FormField.js";
import { GateNoticeProvider } from "./internal/disabledReason.js";
import { formatRbacReason } from "./rbacReasons.js";
import { Select, type SelectOption } from "./Select.js";
import { Tag } from "./Tag.js";
import { TextInput } from "./TextInput.js";

type AuditQuery = NonNullable<generated.rest.operations["queryAuditLog"]["parameters"]["query"]>;
type AuditEnvironment = generated.rest.components["schemas"]["Environment"];
type AuditOutcome = generated.rest.components["schemas"]["AuditOutcome"];
type AuditSeverity = generated.rest.components["schemas"]["Severity"];

/**
 * The filter set, URL state (E42-D04 §4 Filters): the generated `queryAuditLog` query parameters, never the cursor or
 * the page size, plus `environment`, which filters the loaded page only (D7; CG-2).
 */
export type AuditFilters = Omit<AuditQuery, "cursor" | "limit"> & {
  readonly environment?: AuditEnvironment;
};

/** A field of the set: the key a `422` names it by. */
export type AuditFilterField = keyof AuditFilters;

/** An actor the host has seen (no user list is served, BQ-3): its `actor_user_id` and the label recorded with it. */
export interface AuditActorOption {
  readonly id: string;
  readonly label: string;
}

/** A registered action code and its SCR-135 label where one exists (CG-3). */
export interface AuditActionOption {
  readonly code: string;
  readonly label?: string;
}

/**
 * The words: E42-D04 §14 `labels.filter.*`, `labels.word.*` (D2, D3), `audit.env_page`, CMP-174's name (`15`) and
 * D04 AL-25's `rbac.owner_only` verbs. PROPOSED (no source gives them): `subjectType`, `subjectId`, `fromTime`,
 * `toTime` and `any`.
 */
export const AUDIT_FILTER_COPY = {
  name: "Filter the audit log",
  from: "From",
  to: "To",
  fromTime: "From time",
  toTime: "To time",
  actor: "Actor",
  action: "Action",
  subjectType: "Subject type",
  subjectId: "Subject id",
  outcome: "Outcome",
  severity: "Severity",
  ip: "IP",
  search: "Search",
  environment: "Environment",
  clear: "Clear filters",
  any: "Any",
  you: "you",
  environments: { live: "LIVE", demo: "DEMO", testnet: "TESTNET" },
  ownVerbs: {
    actor: "see other users' entries",
    ip: "filter by IP address",
    search: "search the audit log",
    environment: "filter by environment",
  },
} as const;

/** The contract's cap on repeated `action` codes (`22` `queryAuditLog`: `maxItems: 50`). */
export const AUDIT_ACTION_MAX = 50;

/** An action code as the contract writes it (`22`: `^[a-z0-9_]+([.][a-z0-9_]+){1,3}$`, at most 64). */
const ACTION_CODE = /^[a-z0-9_]+([.][a-z0-9_]+){1,3}$/;

/** `audit.env_page`: "{ENV} (this page only)" (E42-D04 §14, AL-6). */
export const auditEnvironmentLabel = (env: AuditEnvironment): string =>
  `${AUDIT_FILTER_COPY.environments[env]} (this page only)`;

/** The order the bar lays its fields out in: a `422`'s focus goes to the first in it (E42-D03 I-2). */
const FIELD_ORDER: readonly AuditFilterField[] = [
  "from",
  "to",
  "actor_user_id",
  "action",
  "subject_type",
  "subject_id",
  "outcome",
  "severity",
  "ip",
  "q",
  "environment",
];

/** What the own view gates (AL-25): the server replaces the actor and refuses `q` and `ip` (`22`), so none is sent. */
const OWN_GATED: readonly AuditFilterField[] = ["actor_user_id", "ip", "q", "environment"];

/** `filters` with `field` set to `value`, or without it when `value` is undefined (never a key set to undefined). */
function withField<K extends AuditFilterField>(
  filters: AuditFilters,
  field: K,
  value: AuditFilters[K] | undefined,
): AuditFilters {
  const next: Record<string, unknown> = { ...filters };
  if (value === undefined) delete next[field];
  else next[field] = value;
  return next as AuditFilters;
}

/** An RFC 3339 date-time with an offset (a host may hand over any it parsed from the URL). */
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;

/** A UTC day and time for the date-time picker: `ts` read in UTC, or none when it is not a date-time. */
function splitUtc(ts: string | undefined): { date: string | null; time: string | null } {
  if (ts === undefined || !DATE_TIME.test(ts)) return { date: null, time: null };
  const ms = Date.parse(ts);
  if (Number.isNaN(ms)) return { date: null, time: null };
  const iso = new Date(ms).toISOString();
  return { date: iso.slice(0, 10), time: iso.slice(11, 16) };
}

/** The picker's day and time as the RFC 3339 UTC instant the contract takes; no time is the day's start. */
const joinUtc = (date: string, time: string | null): string => `${date}T${time ?? "00:00"}:00Z`;

const actionLabel = (code: string, options: readonly AuditActionOption[]): string => {
  const label = options.find((option) => option.code === code)?.label?.trim();
  return label === undefined || label === "" ? code : `${label} (${code})`;
};

export interface AuditFilterBarProps {
  /** The applied set, as the URL holds it. */
  readonly filters: AuditFilters;
  /**
   * The next set: a select on change, a text field on Enter or when focus leaves it, never per keystroke (each new set
   * is a recorded read under the audit budget, BQ-3); a date when it commits; Clear filters empties it. The host
   * resets the cursor, and a change to `environment` alone re-filters the loaded page and reads nothing (D7).
   */
  readonly onChange: (filters: AuditFilters) => void;
  /** The actors the loaded pages hold: no user list is served (BQ-3). */
  readonly actorOptions: readonly AuditActorOption[];
  /** The codes seen, and the labelled ones (CG-3). */
  readonly actionOptions: readonly AuditActionOption[];
  /**
   * `own`, a Manager's My activity (AL-25): Actor reads "you", and Actor, IP, Search and Environment stay, T2
   * `rbac.owner_only`, read-only; none of them is ever sent. Default `raw`.
   */
  readonly view?: "raw" | "own";
  /** Where Environment filters: the loaded page only (D7, CG-2). */
  readonly environmentScope?: "page";
  /** Every control T2 with this reason (AL-16's `admin.rate_limited`): nothing applies until it is lifted. */
  readonly blockedReason?: string;
  /** The host's one notice that shows `blockedReason`; without it the bar shows one itself. */
  readonly blockedReasonId?: string;
  /**
   * A `422`'s field errors, by parameter: each under its field, linked by `aria-describedby` and not live; focus goes
   * to the first in the bar's order, which carries it (E42-D03 I-2), unless the user has moved on since the bar sent
   * the set (A-12: focus is now on another control than the one that sent it). The contract is by identity: pass a
   * new object for each answer and the same object between answers; a new object is a new answer, so a literal
   * built on every render would ask for the focus on every render.
   */
  readonly errors?: Readonly<Partial<Record<AuditFilterField, string>>>;
}

interface TextFieldProps {
  readonly id: string;
  readonly label: string;
  readonly applied: string | undefined;
  readonly reason: string | undefined;
  readonly error: string | undefined;
  readonly onApply: (value: string | undefined) => void;
}

/**
 * A CMP-007 field holding a draft that applies on Enter or when focus leaves it, never per keystroke, and each value
 * once: Enter then leaving the field sends one set, even while the host has not fed it back yet.
 */
function TextFilter({ id, label, applied, reason, error, onApply }: TextFieldProps): JSX.Element {
  const [draft, setDraft] = useState(applied ?? "");
  const [seen, setSeen] = useState(applied);
  // The value last sent, until the host's set moves: Enter then blur against a lagging host sends it once (C-5520-11).
  const [sent, setSent] = useState(applied);
  // A set changed elsewhere (a deep link, Clear filters) replaces the draft.
  if (applied !== seen) {
    setSeen(applied);
    setDraft(applied ?? "");
    setSent(applied);
  }
  const apply = (): void => {
    if (reason !== undefined) return;
    const value = draft.trim() === "" ? undefined : draft.trim();
    if (value === applied || value === sent) return;
    setSent(value);
    onApply(value);
  };
  return (
    <FormField
      label={label}
      htmlFor={id}
      error={error}
      errorLive={false}
      {...(reason === undefined ? {} : { disabledReason: reason })}
    >
      <TextInput
        value={reason === undefined ? draft : (applied ?? "")}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.nativeEvent.isComposing) {
            event.preventDefault();
            apply();
          }
        }}
        onBlur={apply}
      />
    </FormField>
  );
}

/**
 * CMP-174 AuditFilterBar (E42-D04 §4 Filters; `15` CMP-174): a `form` with `role="search"` named "Filter the audit
 * log" over the contract's filters, each control under its visible label: From and To (CMP-047 with times, UTC),
 * Actor and Action (CMP-048, the actions as CMP-011 chips, at most 50), Subject type and id, IP and Search (CMP-007),
 * Outcome, Severity and Environment (CMP-009; Environment's options say "(this page only)"), then Clear filters.
 * Selects apply on change and text on Enter or blur. The own view gates Actor ("you"), IP, Search and Environment
 * with `rbac.owner_only` and sends none of them; `blockedReason` gates every control behind one notice (AL-16). A
 * `422`'s errors sit under their fields, not live, and focus moves to the first (AL-17). The set is the host's: the
 * bar owns no live region and reads nothing.
 */
export function AuditFilterBar({
  filters,
  onChange,
  actorOptions,
  actionOptions,
  view = "raw",
  blockedReason,
  blockedReasonId,
  errors,
}: AuditFilterBarProps): JSX.Element {
  const copy = AUDIT_FILTER_COPY;
  const own = view === "own";
  const blocked = blockedReason?.trim() || undefined;
  const hostNotice = blockedReasonId?.trim() || undefined;
  const noticeId = useId();
  const actionLabelId = useId();
  const ids = {
    from: useId(),
    to: useId(),
    actor_user_id: useId(),
    action: useId(),
    subject_type: useId(),
    subject_id: useId(),
    outcome: useId(),
    severity: useId(),
    ip: useId(),
    q: useId(),
    environment: useId(),
  } satisfies Record<AuditFilterField, string>;

  const ownReason = (verb: string): string | undefined =>
    own ? formatRbacReason("rbac.owner_only", { verb }) : undefined;
  // One reason per control (E09-D09 §2.1): the view's RBAC leg comes before a registered state.
  const reasons: Readonly<Record<AuditFilterField, string | undefined>> = {
    from: blocked,
    to: blocked,
    actor_user_id: ownReason(copy.ownVerbs.actor) ?? blocked,
    action: blocked,
    subject_type: blocked,
    subject_id: blocked,
    outcome: blocked,
    severity: blocked,
    ip: ownReason(copy.ownVerbs.ip) ?? blocked,
    q: ownReason(copy.ownVerbs.search) ?? blocked,
    environment: ownReason(copy.ownVerbs.environment) ?? blocked,
  };
  const gate = (field: AuditFilterField): { disabledReason?: string } => {
    const reason = reasons[field];
    return reason === undefined ? {} : { disabledReason: reason };
  };
  const errorOf = (field: AuditFilterField): string | undefined => errors?.[field] || undefined;

  // Where focus was when the bar last sent a set (`undefined` before the first): an answer's focus move needs it.
  const sentFrom = useRef<Element | null | undefined>(undefined);
  /** The next set to the host; the own view never sends what it gates. */
  const emit = (next: AuditFilters): void => {
    if (blocked !== undefined) return;
    let sent = next;
    if (own) for (const field of OWN_GATED) sent = withField(sent, field, undefined);
    sentFrom.current = document.activeElement;
    onChange(sent);
  };
  const set = <K extends AuditFilterField>(field: K, value: AuditFilters[K] | undefined): void => {
    if (reasons[field] !== undefined) return;
    emit(withField(filters, field, value));
  };

  // A `422`: focus to the first field in error (E42-D03 I-2); the field carries it, so nothing is announced. A new
  // `errors` object is a new answer; the ids are stable, read through a ref. Only if the user has not moved on (A-12):
  // focus is where it was when the bar sent the set (still on the field Enter applied, or on the page after a field
  // applied on leaving), never pulled back from another control the user went to meanwhile. A sender that has left
  // the document (a calendar day, gone with its popover) is not a move-on.
  const idsRef = useRef(ids);
  idsRef.current = ids;
  useLayoutEffect(() => {
    const first = FIELD_ORDER.find((field) => (errors?.[field] ?? "") !== "");
    if (first === undefined) return;
    const from = sentFrom.current;
    const here = document.activeElement;
    const movedOn =
      from !== undefined &&
      from?.isConnected !== false &&
      here !== null &&
      here !== document.body &&
      here !== from;
    if (!movedOn) document.getElementById(idsRef.current[first])?.focus();
  }, [errors]);

  // From and To: a draft day and time each, applied once a day is set.
  const fromApplied = splitUtc(filters.from);
  const toApplied = splitUtc(filters.to);
  const [fromDraft, setFromDraft] = useState(fromApplied);
  const [toDraft, setToDraft] = useState(toApplied);
  const [seenRange, setSeenRange] = useState(`${filters.from ?? ""}|${filters.to ?? ""}`);
  const range = `${filters.from ?? ""}|${filters.to ?? ""}`;
  if (range !== seenRange) {
    setSeenRange(range);
    setFromDraft(fromApplied);
    setToDraft(toApplied);
  }
  const commitWindow = (
    field: "from" | "to",
    draft: { date: string | null; time: string | null },
  ): void => {
    if (field === "from") setFromDraft(draft);
    else setToDraft(draft);
    set(field, draft.date === null ? undefined : joinUtc(draft.date, draft.time));
  };

  // Actor: a choice from the list applies its id; an emptied field drops it when focus leaves.
  const actorApplied =
    filters.actor_user_id === undefined
      ? ""
      : (actorOptions.find((option) => option.id === filters.actor_user_id)?.label ??
        filters.actor_user_id);
  const [actorText, setActorText] = useState(actorApplied);
  const [seenActor, setSeenActor] = useState(actorApplied);
  if (actorApplied !== seenActor) {
    setSeenActor(actorApplied);
    setActorText(actorApplied);
  }
  // The actor last sent, until the host's set moves: a choice, then leaving the field, sends it once.
  const [actorSent, setActorSent] = useState(filters.actor_user_id);
  const [seenActorId, setSeenActorId] = useState(filters.actor_user_id);
  if (filters.actor_user_id !== seenActorId) {
    setSeenActorId(filters.actor_user_id);
    setActorSent(filters.actor_user_id);
  }
  const sendActor = (id: string | undefined): void => {
    if (id === filters.actor_user_id || id === actorSent) return;
    setActorSent(id);
    set("actor_user_id", id);
  };
  const actorChoices: readonly ComboboxOption[] = actorOptions.map((option) => ({
    value: option.id,
    label: option.label,
  }));
  const settleActor = (): void => {
    if (reasons.actor_user_id !== undefined) return;
    const text = actorText.trim();
    if (text === "") {
      sendActor(undefined);
      return;
    }
    const match = actorOptions.find((option) => option.label.toLowerCase() === text.toLowerCase());
    if (match !== undefined && match.id !== filters.actor_user_id) sendActor(match.id);
    else setActorText(actorApplied);
  };

  // Action: codes added from the list or typed exactly, shown as removable chips.
  const actions = filters.action ?? [];
  const [actionText, setActionText] = useState("");
  const actionChoices: readonly ComboboxOption[] = actionOptions.map((option) => ({
    value: option.code,
    label: actionLabel(option.code, actionOptions),
  }));
  const pendingFocus = useRef<string | null>(null);
  const addAction = (code: string): void => {
    setActionText("");
    if (reasons.action !== undefined || actions.includes(code)) return;
    if (actions.length >= AUDIT_ACTION_MAX) return;
    set("action", [...actions, code]);
  };
  const resolveTyped = (text: string): string | undefined => {
    const typed = text.trim();
    const lower = typed.toLowerCase();
    const known = actionOptions.find(
      (option) =>
        option.code === lower ||
        (option.label !== undefined && option.label.toLowerCase() === lower) ||
        actionLabel(option.code, actionOptions).toLowerCase() === lower,
    );
    if (known !== undefined) return known.code;
    return typed.length <= 64 && ACTION_CODE.test(typed) ? typed : undefined;
  };
  const removeAction = (code: string): void => {
    if (reasons.action !== undefined) return;
    const at = actions.indexOf(code);
    // CMP-011: the group hands focus on, the next chip, else the previous, else the input; never <body>.
    pendingFocus.current = actions[at + 1] ?? actions[at - 1] ?? null;
    if (pendingFocus.current === null) pendingFocus.current = "";
    set("action", actions.length > 1 ? actions.filter((one) => one !== code) : undefined);
  };
  const chipsRef = useRef<HTMLUListElement>(null);
  const actionsKey = actions.join("\n");
  useLayoutEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    const chip = [...(chipsRef.current?.children ?? [])].find(
      (item) => item instanceof HTMLElement && item.dataset["code"] === target,
    );
    (chip?.querySelector("button") ?? document.getElementById(idsRef.current.action))?.focus();
  }, [actionsKey]);

  const outcomeOptions: readonly SelectOption[] = [
    { value: "", label: copy.any },
    ...(Object.keys(AUDIT_ROW_COPY.outcome) as AuditOutcome[]).map((value) => ({
      value,
      label: AUDIT_ROW_COPY.outcome[value],
    })),
  ];
  const severityOptions: readonly SelectOption[] = [
    { value: "", label: copy.any },
    ...(Object.keys(AUDIT_ROW_COPY.severity) as AuditSeverity[]).map((value) => ({
      value,
      label: AUDIT_ROW_COPY.severity[value],
    })),
  ];
  const environmentOptions: readonly SelectOption[] = [
    { value: "", label: copy.any },
    ...(Object.keys(copy.environments) as AuditEnvironment[]).map((value) => ({
      value,
      label: auditEnvironmentLabel(value),
    })),
  ];
  const pick = <K extends "outcome" | "severity" | "environment">(field: K, value: string): void =>
    set(field, value === "" ? undefined : (value as AuditFilters[K]));

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    // Each field applies itself: Enter in a field never submits the form.
    event.preventDefault();
  };
  const onActorBlur = (event: FocusEvent<HTMLDivElement>): void => {
    if (!event.currentTarget.contains(event.relatedTarget)) settleActor();
  };
  const onActionKey = (event: KeyboardEvent<HTMLInputElement>, active?: ComboboxOption): void => {
    if (event.key !== "Enter" || active !== undefined || event.nativeEvent.isComposing) return;
    event.preventDefault();
    const code = resolveTyped(actionText);
    if (code !== undefined) addAction(code);
  };
  const onActorKey = (event: KeyboardEvent<HTMLInputElement>, active?: ComboboxOption): void => {
    if (event.key !== "Enter" || active !== undefined || event.nativeEvent.isComposing) return;
    event.preventDefault();
    settleActor();
  };

  const bar = (
    <form
      role="search"
      aria-label={copy.name}
      className="cv-audit-filters"
      data-cmp="CMP-174"
      data-view={view}
      noValidate
      onSubmit={onSubmit}
    >
      {blocked !== undefined && hostNotice === undefined ? (
        <p id={noticeId} className="cv-audit-filters__notice">
          {blocked}
        </p>
      ) : null}
      <div className="cv-audit-filters__fields">
        <FormField
          label={copy.from}
          htmlFor={ids.from}
          error={errorOf("from")}
          errorLive={false}
          {...gate("from")}
        >
          <DatePicker
            withTime
            timeLabel={copy.fromTime}
            value={fromDraft.date}
            time={fromDraft.time}
            onChange={(date) => commitWindow("from", { ...fromDraft, date })}
            onTimeChange={(time) => commitWindow("from", { ...fromDraft, time })}
          />
        </FormField>
        <FormField
          label={copy.to}
          htmlFor={ids.to}
          error={errorOf("to")}
          errorLive={false}
          {...gate("to")}
        >
          <DatePicker
            withTime
            timeLabel={copy.toTime}
            value={toDraft.date}
            time={toDraft.time}
            onChange={(date) => commitWindow("to", { ...toDraft, date })}
            onTimeChange={(time) => commitWindow("to", { ...toDraft, time })}
          />
        </FormField>
        <div className="cv-audit-filters__combo" onBlur={onActorBlur}>
          <FormField
            label={copy.actor}
            htmlFor={ids.actor_user_id}
            error={errorOf("actor_user_id")}
            errorLive={false}
            {...gate("actor_user_id")}
          >
            <Combobox
              options={own ? [] : actorChoices}
              value={own ? copy.you : actorText}
              onKeyDown={onActorKey}
              onChange={(text, option) => {
                if (reasons.actor_user_id !== undefined) return;
                setActorText(option?.label ?? text);
                if (option !== undefined) sendActor(option.value);
              }}
            />
          </FormField>
        </div>
        <FormField
          label={copy.action}
          htmlFor={ids.action}
          labelId={actionLabelId}
          error={errorOf("action")}
          errorLive={false}
          {...gate("action")}
        >
          <Combobox
            options={actionChoices}
            value={actionText}
            onKeyDown={onActionKey}
            onChange={(text, option) => {
              if (option !== undefined) addAction(option.value);
              else setActionText(text);
            }}
          />
        </FormField>
        <TextFilter
          id={ids.subject_type}
          label={copy.subjectType}
          applied={filters.subject_type}
          reason={reasons.subject_type}
          error={errorOf("subject_type")}
          onApply={(value) => set("subject_type", value)}
        />
        <TextFilter
          id={ids.subject_id}
          label={copy.subjectId}
          applied={filters.subject_id}
          reason={reasons.subject_id}
          error={errorOf("subject_id")}
          onApply={(value) => set("subject_id", value)}
        />
        <FormField
          label={copy.outcome}
          htmlFor={ids.outcome}
          error={errorOf("outcome")}
          errorLive={false}
          {...gate("outcome")}
        >
          <Select
            options={outcomeOptions}
            value={filters.outcome ?? ""}
            onChange={(value) => pick("outcome", value)}
          />
        </FormField>
        <FormField
          label={copy.severity}
          htmlFor={ids.severity}
          error={errorOf("severity")}
          errorLive={false}
          {...gate("severity")}
        >
          <Select
            options={severityOptions}
            value={filters.severity ?? ""}
            onChange={(value) => pick("severity", value)}
          />
        </FormField>
        <TextFilter
          id={ids.ip}
          label={copy.ip}
          applied={own ? undefined : filters.ip}
          reason={reasons.ip}
          error={errorOf("ip")}
          onApply={(value) => set("ip", value)}
        />
        <TextFilter
          id={ids.q}
          label={copy.search}
          applied={own ? undefined : filters.q}
          reason={reasons.q}
          error={errorOf("q")}
          onApply={(value) => set("q", value)}
        />
        <FormField
          label={copy.environment}
          htmlFor={ids.environment}
          error={errorOf("environment")}
          errorLive={false}
          {...gate("environment")}
        >
          <Select
            options={environmentOptions}
            value={own ? "" : (filters.environment ?? "")}
            onChange={(value) => pick("environment", value)}
          />
        </FormField>
      </div>
      {actions.length === 0 ? null : (
        <ul ref={chipsRef} className="cv-audit-filters__chips" aria-labelledby={actionLabelId}>
          {actions.map((code) => (
            <li key={code} data-code={code}>
              <Tag
                label={actionLabel(code, actionOptions)}
                removable
                onRemove={() => removeAction(code)}
                {...(reasons.action === undefined ? {} : { disabledReason: reasons.action })}
              />
            </li>
          ))}
        </ul>
      )}
      <div className="cv-audit-filters__actions">
        <Button
          variant="secondary"
          onClick={() => emit({})}
          {...(blocked === undefined
            ? {}
            : { disabledReason: blocked, disabledReasonId: hostNotice ?? noticeId })}
        >
          {copy.clear}
        </Button>
      </div>
    </form>
  );
  // Mounted gated or not, so a rate limit that starts or ends never remounts a control or drops focus.
  return (
    <GateNoticeProvider
      notice={blocked === undefined ? null : { noticeId: hostNotice ?? noticeId, reason: blocked }}
    >
      {bar}
    </GateNoticeProvider>
  );
}
