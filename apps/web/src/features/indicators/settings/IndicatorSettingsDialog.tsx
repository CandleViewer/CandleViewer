// E13-S01 (#423) S4: SCR-035 Indicator settings, for one instance (D02 §5; D06 §5–§7, §12). An
// exported component with a story host and no route (BQ-06): nothing mounts it until a chart
// screen exists. Inputs is CMP-242 SchemaForm; Style holds one note while its token controls are
// absent (C-b: "a deferred capability is drawn as absent, never as a lock"). Visibility, Scale and
// Alerts are absent too: no engine member or contract field backs them yet (G-rows on #423).
//
// The commit model (D06 §6): a `server` instance commits only on Apply or `Enter`, never per
// keystroke (SR-E13-03); a `client_worker` instance previews every valid change display-only,
// with no debounce (BQ-10), "Updating…" only past 100 ms on the injected clock. Invalid values are
// refused, never clamped, and params are re-validated before the store sees them (BQ-11), which
// validates them again. Every close path reverts the preview.
//
// T2 (D06 §12; D05 T2-02, T2-06; G-T2.1a–d, G-T2.5): the view-as leg is checked first, then the
// role leg; one header notice, which Apply points at through CMP-079's notice form. Fields stay
// editable (display-only preview) and `Enter` stages nothing and re-shows the notice. Form validity
// is not T2 (T2-14): Apply keeps its label at `opacity.disabled` with the reason beside it, no lock.
import {
  announcePolite,
  Button,
  Callout,
  Dialog,
  formatRbacReason,
  RbacGate,
  Tabs,
} from "@candleviewer/ui";
import { useEffect, useId, useMemo, useRef, useState, type JSX } from "react";
import { SETTINGS, settingsTitle, validationText } from "../copy";
import type { CatalogueEntry } from "../model/catalogue";
import type { InstanceId } from "../model/instances";
import { defaultParams } from "../model/params";
import { isEditable, type ParamField } from "../model/schema";
import type { Params } from "../model/types";
import type { IndicatorStore } from "../store/indicatorStore";
import { useChartIndicators } from "../store/useIndicators";
import { SLOW_MS, systemClock, type IndicatorPreviewPort, type SettingsClock } from "./clock";
import { checkDraft, draftOf, isFieldEdited, type Draft, type DraftValue } from "./draft";
import { SchemaForm } from "./SchemaForm";

/** The session's legs for this instance's writes, as the host reads them from the session. */
export interface SettingsAccess {
  /** The view-as target's name, or `null`. Checked first (T2-02; E09-D09 §2.1 step 3a). */
  readonly viewAs: string | null;
  /** Whether the role holds the write (`workspaces:write`, D06 §3.1; T2-06). */
  readonly canWrite: boolean;
}

/** D09 §3.2's verb for this write, as T2-05 quotes it ("Your role can't save workspaces."). */
const VERB = "save workspaces";

type Gate =
  | { readonly reason: "rbac.view_as"; readonly user: string; readonly sentence: string }
  | { readonly reason: "rbac.permission"; readonly sentence: string };

/** The first leg that denies, view-as before role; `null` when the writes are allowed. */
export function settingsGate(access: SettingsAccess): Gate | null {
  if (access.viewAs !== null) {
    const user = access.viewAs;
    return { reason: "rbac.view_as", user, sentence: formatRbacReason("rbac.view_as", { user }) };
  }
  if (!access.canWrite) {
    return {
      reason: "rbac.permission",
      sentence: formatRbacReason("rbac.permission", { verb: VERB }),
    };
  }
  return null;
}

export interface IndicatorSettingsDialogProps {
  readonly open: boolean;
  /** Every close path: Apply, Cancel, `Esc`, Close. The dialog returns focus to its opener. */
  readonly onClose: () => void;
  readonly store: IndicatorStore;
  readonly chart: string;
  readonly instanceId: InstanceId;
  readonly entry: CatalogueEntry;
  /** The instance's label as the legend spells it ("EMA 21"); the legend's (S6). */
  readonly label: string;
  /** The chart's interval, as the toolbar spells it ("5m"). */
  readonly timeframe: string;
  readonly access: SettingsAccess;
  /** The display-only preview; absent until #425 serves one (G-a). */
  readonly preview?: IndicatorPreviewPort;
  readonly clock?: SettingsClock;
}

type TabId = "inputs" | "style";

const NO_FIELDS: readonly ParamField[] = Object.freeze([]);
const NO_PARAMS: Params = Object.freeze(Object.create(null) as Params);

/**
 * One polite announcement per press (G-T2.3; D11): cleared, then set in a microtask, as CMP-001's own
 * refusal does, so the same sentence is said again on a repeat press.
 */
function announce(text: string): void {
  announcePolite("");
  queueMicrotask(() => announcePolite(text));
}

/** The element a field's focus lands on: the input, or the first control inside its wrapper. */
const focusTarget = (element: HTMLElement): HTMLElement | null =>
  element.matches("input, button") ? element : element.querySelector("input, button");

export function IndicatorSettingsDialog(props: IndicatorSettingsDialogProps): JSX.Element | null {
  const { open, onClose, store, chart, instanceId, entry, access, preview } = props;
  const clock = props.clock ?? systemClock;
  const instance = useChartIndicators(store, chart).find((i) => i.id === instanceId);
  const fields = entry.schema.ok ? entry.schema.fields : NO_FIELDS;
  const committed = instance?.params ?? NO_PARAMS;
  const [draft, setDraft] = useState<Draft>(() => draftOf(fields, committed));
  const [tab, setTab] = useState<TabId>("inputs");
  const [slow, setSlow] = useState(false);
  const [refusal, setRefusal] = useState("");
  // Each opening starts from the committed values (the draft of a closed session is gone).
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setDraft(draftOf(fields, committed));
      setTab("inputs");
      setSlow(false);
      setRefusal("");
    }
  }
  const checked = useMemo(() => checkDraft(fields, draft), [fields, draft]);
  const gate = settingsGate(access);
  const ids = useId();
  const noticeId = `${ids}-notice`;
  const fixId = `${ids}-fix`;
  const captionId = `${ids}-caption`;
  const tabsRef = useRef<HTMLDivElement>(null);
  const fieldEls = useRef(new Map<string, HTMLElement>());
  const focusInvalid = useRef(false);
  const run = useRef<{ seq: number; cancel: (() => void) | null; shown: boolean }>({
    seq: 0,
    cancel: null,
    shown: false,
  });
  const latest = useRef({ preview, onClose });
  latest.current = { preview, onClose };

  const server = instance?.compute === "server";

  /** A `client_worker` preview of valid params (D06 §6 row 1); a later one supersedes it. */
  const startPreview = (params: Params): void => {
    if (preview === undefined || instance?.compute !== "client_worker") return;
    const state = run.current;
    state.seq += 1;
    const seq = state.seq;
    state.cancel?.();
    state.shown = true;
    state.cancel = clock.after(SLOW_MS, () => {
      if (run.current.seq === seq) setSlow(true);
    });
    const settle = (): void => {
      if (run.current.seq !== seq) return;
      run.current.cancel?.();
      run.current.cancel = null;
      setSlow(false);
    };
    preview.preview(params).then(settle, settle);
  };

  /** Ends the session's preview, so the chart shows the committed instance again. */
  const endPreview = (): void => {
    const state = run.current;
    state.seq += 1;
    state.cancel?.();
    state.cancel = null;
    if (state.shown) latest.current.preview?.clear();
    state.shown = false;
  };

  // Unmounting mid-session reverts the preview too (refs only: nothing here re-renders).
  useEffect(
    () => () => {
      const state = run.current;
      state.cancel?.();
      if (state.shown) latest.current.preview?.clear();
      state.shown = false;
    },
    [],
  );

  const close = (): void => {
    endPreview();
    setSlow(false);
    latest.current.onClose();
  };

  // The instance went away while open (removed elsewhere): nothing is left to configure.
  useEffect(() => {
    if (open && instance === undefined) close();
  });

  // F-10: after a switch to Inputs, focus lands on the first invalid field.
  useEffect(() => {
    if (!focusInvalid.current || tab !== "inputs") return;
    focusInvalid.current = false;
    const first = fields.find((f) => checked.errors.has(f.name));
    const element = first === undefined ? undefined : fieldEls.current.get(first.name);
    if (element !== undefined) focusTarget(element)?.focus();
  });

  const commitDraft = (next: Draft): void => {
    setDraft(next);
    setRefusal("");
    const result = checkDraft(fields, next);
    if (result.params !== null) startPreview(result.params);
  };

  const change = (name: string, value: DraftValue): void => {
    const next = new Map(draft);
    next.set(name, value);
    commitDraft(next);
  };

  const reset = (): void => commitDraft(draftOf(fields, defaultParams(fields)));

  /** Apply on an invalid form (T2-14, F-10): nothing commits; the reason once; the field focused. */
  const refuseInvalid = (): void => {
    announce(SETTINGS.fixFirst);
    focusInvalid.current = true;
    setTab("inputs");
  };

  const apply = (): void => {
    if (gate !== null || instance === undefined) return;
    if (checked.params === null) {
      refuseInvalid();
      return;
    }
    const result = store.configure(chart, instance.id, entry, checked.params);
    if (result.ok || result.reason === "unchanged") {
      close();
      return;
    }
    setRefusal(
      result.reason === "subscription_limit" ? SETTINGS.atCapacity : SETTINGS.applyRefused,
    );
  };

  const onEnter = (name: string): void => {
    const spec = fields.find((f) => f.name === name);
    const rule = checked.errors.get(name);
    if (spec !== undefined && isEditable(spec) && rule !== undefined) {
      announce(validationText(spec, rule));
    } else if (gate !== null) {
      announce(gate.sentence);
    } else {
      apply();
    }
  };

  const fieldRef = (name: string, element: HTMLElement | null): void => {
    if (element === null) fieldEls.current.delete(name);
    else fieldEls.current.set(name, element);
  };

  if (instance === undefined) return null;
  const title = settingsTitle(props.label, instance.placement.kind, props.timeframe);
  const edited = fields.some((f) => isEditable(f) && isFieldEdited(f, draft.get(f.name)));
  const invalid = checked.params === null;

  const inputs = (
    <div className="cv-ind-settings__grid">
      <SchemaForm
        schema={entry.schema}
        draft={draft}
        errors={checked.errors}
        onChange={change}
        onEnter={onEnter}
        fieldRef={fieldRef}
      />
      <figure className="cv-ind-settings__preview">
        <div className="cv-ind-settings__tile" role="img" aria-labelledby={captionId} />
        <figcaption id={captionId} className="cv-ind-settings__caption">
          {server ? SETTINGS.previewServer : SETTINGS.previewWindow}
        </figcaption>
        <p className="cv-ind-settings__caption" role="status" aria-live="polite">
          {slow ? SETTINGS.updating : ""}
        </p>
      </figure>
    </div>
  );

  const applyButton =
    gate !== null ? (
      // 2a against the panel's one notice (G-T2.5): the lock "Not available" leads the full label
      // and the notice node is the description (CMP-001 `disabledReasonId`).
      gate.reason === "rbac.view_as" ? (
        <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: gate.user }}>
          <Button variant="primary" disabledReasonId={noticeId}>
            {SETTINGS.apply}
          </Button>
        </RbacGate>
      ) : (
        <RbacGate allowed={false} reason="rbac.permission" fills={{ verb: VERB }}>
          <Button variant="primary" disabledReasonId={noticeId}>
            {SETTINGS.apply}
          </Button>
        </RbacGate>
      )
    ) : invalid ? (
      <span className="cv-ind-settings__apply">
        <span id={fixId} className="cv-ind-settings__reason">
          {SETTINGS.fixFirst}
        </span>
        {/* T2-14's validity look: CMP-001's fill at `opacity.disabled`, focusable, no lock. */}
        <button
          type="button"
          className="cv-control cv-button cv-ind-settings__invalid"
          data-cmp="CMP-001"
          data-variant="primary"
          data-size="md"
          aria-disabled="true"
          aria-describedby={fixId}
          onClick={refuseInvalid}
        >
          <span className="cv-button__label">{SETTINGS.apply}</span>
        </button>
      </span>
    ) : (
      <Button variant="primary" onClick={apply}>
        {SETTINGS.apply}
      </Button>
    );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
      title={title}
      description={
        edited ? (
          <span className="cv-ind-settings__edited">
            <span className="cv-ind-settings__dot" aria-hidden="true" />
            {SETTINGS.edited}
          </span>
        ) : undefined
      }
      size="lg"
      initialFocusRef={tabsRef}
      footer={
        <div className="cv-ind-settings__footer">
          <span className="cv-ind-settings__status" role="status" aria-live="polite">
            {refusal}
          </span>
          {entry.schema.ok ? (
            <Button variant="secondary" onClick={reset}>
              {SETTINGS.reset}
            </Button>
          ) : null}
          <Button variant="secondary" onClick={close}>
            {SETTINGS.cancel}
          </Button>
          {entry.schema.ok ? applyButton : null}
        </div>
      }
    >
      <div className="cv-ind-settings">
        {gate === null ? null : (
          <Callout id={noticeId} tone="info" live="off" title={gate.sentence} />
        )}
        <div ref={tabsRef}>
          <Tabs
            aria-label={title}
            tabs={[
              {
                id: "inputs",
                label: SETTINGS.tabs.inputs,
                ...(invalid && tab !== "inputs" ? { icon: "danger" as const } : {}),
              },
              { id: "style", label: SETTINGS.tabs.style },
            ]}
            value={tab}
            onChange={(id) => setTab(id === "style" ? "style" : "inputs")}
            renderPanel={(id) =>
              id === "style" ? (
                <p className="cv-ind-settings__note">{SETTINGS.stylePending}</p>
              ) : (
                inputs
              )
            }
          />
        </div>
      </div>
    </Dialog>
  );
}
