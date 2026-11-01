import "./hotkey-editor.css";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { announce, forget } from "../features/app-shell/announcer";
import { KEYMAP, eventBinding, isDangerous, type KeymapCommand } from "./keymap";
import { reportHotkey, reportRebound } from "./analytics";
import { applyRebind } from "./audit";
import { getBindings, setBindings, subscribeBindings } from "./profile";
import {
  applyImport,
  applySwap,
  exportProfile,
  importProfile,
  parseProfile,
  resetAll,
} from "./profileIo";
import { commandMeta } from "./registry";
import { savesToServer } from "./session";
import {
  normaliseBinding,
  planSwap,
  sharedWith,
  validateBinding,
  validateUnbind,
  type BindingProblem,
  type SwapPlan,
} from "./validate";

const MODS = ["Ctrl", "Alt", "Shift"] as const;
/** The search box's announcement waits for the typing to stop: one count, never one per keystroke. */
const SEARCH_SAY_MS = 600;
/** The context select's "every context" value: no context is named this. */
const ALL = "*";
const CONTEXTS = [...new Set(KEYMAP.map((c) => c.context))];
/** The editor's one key in the shell announcer (#304): each message replaces the last, none is a region of its own. */
const SAID = "keymap:editor";

function say(text: string): void {
  forget(SAID);
  announce("polite", text, SAID);
}

const labelOf = (id: string): string => commandMeta(id)?.label ?? id;
/** Labels two commands share (the arm toggles): their rows' buttons name the context too, so every name is unique. */
const SHARED_LABELS = new Set(
  KEYMAP.map((c) => c.label).filter((l, i, all) => all.indexOf(l) !== i),
);
/** The row a button acts on, after the visible word it starts with (WCAG 2.5.3; A11Y-305BD-02, A11Y-305B-06). */
const rowName = (c: KeymapCommand): string =>
  SHARED_LABELS.has(c.label) ? `${c.label} (${c.context})` : c.label;
/**
 * After an action whose button leaves the row, focus goes back to the row's Save, or to its key field: after Unbind,
 * and whenever Save is disabled because the key field was emptied (A11Y-305B-05).
 */
function focusIn(id: string, control: "save" | "key"): void {
  const save = control === "save" ? document.getElementById(`hk-save-${id}`) : null;
  const usable = save instanceof HTMLButtonElement && !save.disabled;
  (usable ? save : document.getElementById(`hk-key-${id}`))?.focus();
}

/** A refusal's sentence, which names its command once: a reason that names it takes no label in front (DS-305B-04). */
function refusalText(cmd: KeymapCommand, problem: BindingProblem): string {
  const hint = problem.kind === "conflict" ? " - reassign it or choose another key." : "";
  const named = problem.reason.startsWith(`"${cmd.label}"`);
  return `${named ? problem.reason : `${cmd.label}: ${problem.reason}`}${hint}`;
}
/** Where the button a refusal offers sits, said after it (A11Y-305B-01, A11Y-305B-05). */
function pointerTo(problem: BindingProblem, swap: SwapPlan | null): string {
  if (swap !== null) return "Swap is available after Save.";
  return problem.kind === "unsafe-destructive" ? "The acknowledgement is after Save." : "";
}
/** The row a control acts on: a hidden tail after the visible word, so the name starts with it (WCAG 2.5.3). */
function ForRow(props: { readonly cmd: KeymapCommand; readonly joiner?: string }): JSX.Element {
  return (
    <span className="cv-visually-hidden">
      {props.joiner ?? " "}
      {rowName(props.cmd)}
    </span>
  );
}
const sentence = (s: string): string => (/[.!?]$/.test(s) ? s : `${s}.`);
/** An import replaces the profile (D4): what a file leaves out is at its default, as its message says (DS-305B-03). */
const IMPORT_REST = "Every other binding is at its default.";

/** A saved binding, with the meanings it keeps in exclusive views (`05` §3.3 rule 1; SCR-113's "also bound to"). */
function savedText(cmd: KeymapCommand, binding: string): string {
  const shared = sharedWith(cmd.id, binding, getBindings()).map(
    (s) => `"${s.command.label}" (${s.command.context})`,
  );
  return `${cmd.label}: ${binding}${shared.length > 0 ? `; also bound to ${shared.join(", ")}` : ""}`;
}

interface Refusal {
  readonly raw: string;
  readonly problem: BindingProblem;
  /** The one-click swap a conflict offers (`05` §3.3 rule 2), when one is valid. */
  readonly swap: SwapPlan | null;
}

/** The message of the row a rebind, a swap or an unbind last touched, with the refusal it may carry. */
interface Notice {
  readonly id: string;
  readonly text: string;
  readonly refusal: Refusal | null;
}

/**
 * SCR-113 hotkey editor (R-202): typed/select capture; refusals for a conflict (with a one-click swap), a reserved key,
 * a locked command and a dangerous single letter (#305); E49-S07's audited acknowledgement; unbinding (WCAG 2.1.4);
 * import and export as JSON; reset all. A row's message, and the Swap or acknowledgement it offers, sits in that row
 * after Save (A11Y-305B-01). Every change goes through the audited rebind; every message through the shell announcer.
 * Every role remaps on its device (A55: WCAG 2.1.4); a session without `settings:write` reads one plain note that its
 * changes stay there, which is no T2 reason, so nothing is disabled for it. Analytics (BQ-10) hears each change and
 * each blocked save: `hotkey.rebound`, `hotkey.conflict_blocked`, `hotkey.reset` and `hotkey.profile_imported`.
 */
export function HotkeyEditor(): JSX.Element {
  const bindings = useSyncExternalStore(subscribeBindings, getBindings);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [report, setReport] = useState<readonly string[]>([]);
  const [importText, setImportText] = useState("");
  const [exported, setExported] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [ctx, setCtx] = useState(ALL);
  const needle = query.trim().toLowerCase();
  /**
   * The row last focused: a ref, so focusing a row renders nothing. Only when the row it releases was listed solely
   * because it was being edited does the list change, and then one render drops it.
   */
  const editingRef = useRef<string | null>(null);
  const matchesRef = useRef<ReadonlySet<KeymapCommand>>(new Set());
  const [, setListed] = useState(0);
  const onEdit = useCallback((id: string) => {
    const prev = editingRef.current;
    if (prev === id) return;
    editingRef.current = id;
    const held = KEYMAP.find((c) => c.id === prev);
    if (held !== undefined && !matchesRef.current.has(held)) setListed((n) => n + 1);
  }, []);
  const matches = useMemo(
    () =>
      new Set(
        KEYMAP.filter(
          (c) =>
            (ctx === ALL || c.context === ctx) &&
            (needle === "" ||
              `${c.label} ${c.context} ${bindings.get(c.id) ?? c.defaultBinding}`
                .toLowerCase()
                .includes(needle)),
        ),
      ),
    [ctx, needle, bindings],
  );
  matchesRef.current = matches;
  const matched = matches.size;
  /** The row being edited, or holding the last message, stays listed whatever the search says. */
  const keep = notice?.id ?? editingRef.current;
  const shown = useMemo(
    () => KEYMAP.filter((c) => matches.has(c) || c.id === keep),
    [matches, keep],
  );
  const count = shown.length; // the announcement counts the rows on screen
  const filtering = needle !== "" || ctx !== ALL;
  useEffect(() => {
    if (!filtering) return undefined;
    const timer = setTimeout(
      () => say(`${count} ${count === 1 ? "command matches" : "commands match"}.`),
      SEARCH_SAY_MS,
    );
    return () => clearTimeout(timer);
  }, [count, filtering]);
  const exportRef = useRef<HTMLTextAreaElement>(null);
  const importRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    exportRef.current?.focus(); // the exported JSON, ready to copy
  }, [exported]);

  function tell(id: string, text: string, refusal: Refusal | null = null, spoken = text): void {
    setStatus(null);
    setNotice({ id, text, refusal });
    say(spoken);
  }

  function tellAll(text: string): void {
    setNotice(null);
    setStatus(text);
    say(text);
  }

  /** A refusal, for a Save or a Reset alike: counted, said, and offering the swap a conflict allows. */
  function refuse(
    cmd: KeymapCommand,
    raw: string,
    problem: BindingProblem,
    current: ReadonlyMap<string, string>,
  ): void {
    if (problem.kind === "conflict") {
      reportHotkey({ name: "hotkey.conflict_blocked", action: cmd.id, collidesWith: problem.with });
    }
    const swap = problem.kind === "conflict" ? planSwap(cmd.id, raw, current) : null;
    const text = refusalText(cmd, problem);
    // The button it offers sits after Save: say it is there (A11Y-305B-01, A11Y-305B-05).
    const pointer = pointerTo(problem, swap);
    tell(
      cmd.id,
      text,
      { raw, problem, swap },
      pointer === "" ? text : `${sentence(text)} ${pointer}`,
    );
  }

  function tryBind(cmd: KeymapCommand, raw: string, ack = false): void {
    const current = getBindings();
    const problem = validateBinding(cmd.id, raw, current, undefined, { acknowledgedUnsafe: ack });
    if (problem) return refuse(cmd, raw, problem, current);
    const binding = normaliseBinding(raw) ?? raw;
    const next = applyRebind(current, cmd.id, binding, ack);
    setBindings(next);
    reportRebound(current, next, [cmd.id]);
    tell(cmd.id, savedText(cmd, binding));
  }

  function swap(cmd: KeymapCommand, r: Refusal): void {
    const plan = planSwap(cmd.id, r.raw, getBindings()); // re-planned: the profile may have moved
    if (plan === null) tryBind(cmd, r.raw);
    else {
      const before = getBindings();
      const next = applySwap(before, plan);
      setBindings(next);
      reportRebound(before, next, [plan.a, plan.b]);
      tell(cmd.id, `${labelOf(plan.a)}: ${plan.aTo}; ${labelOf(plan.b)}: ${plan.bTo}`);
    }
    focusIn(cmd.id, "save"); // either way the Swap button leaves the row
  }

  function resetOne(cmd: KeymapCommand): void {
    const before = getBindings();
    // The default may have been taken since: the same checks as a Save, and nothing is applied on a refusal.
    const problem =
      cmd.defaultBinding === "" ? null : validateBinding(cmd.id, cmd.defaultBinding, before);
    if (problem) return refuse(cmd, cmd.defaultBinding, problem, before);
    const next = applyRebind(before, cmd.id, cmd.defaultBinding);
    setBindings(next);
    reportRebound(before, next, [cmd.id]);
    reportHotkey({ name: "hotkey.reset" });
    tell(cmd.id, `${cmd.label}: back to its default, ${cmd.defaultBinding || "unbound"}`);
    focusIn(cmd.id, "key"); // the row's Reset is now disabled
  }

  function unbind(cmd: KeymapCommand): void {
    if (validateUnbind(cmd.id) !== null) return; // a locked row has no Unbind
    const before = getBindings();
    const next = applyRebind(before, cmd.id, "");
    setBindings(next);
    reportRebound(before, next, [cmd.id]);
    tell(cmd.id, `${cmd.label}: unbound`);
    focusIn(cmd.id, "key"); // the row's Unbind is now disabled
  }

  function onImport(): void {
    const parsed = parseProfile(importText);
    if (!parsed.ok) {
      setReport([]); // a failure has no entries: its sentence is the status, shown once (DS-305B-04)
      return tellAll(parsed.reason); // the text stays, to be corrected
    }
    const r = importProfile(parsed.profile);
    setBindings(applyImport(getBindings(), r));
    reportHotkey({ name: "hotkey.profile_imported" });
    setReport(r.rejected.map((x) => `${x.commandId} -> ${x.binding}: ${x.problem.reason}`));
    setImportText("");
    importRef.current?.focus(); // the emptied box, not the Import button it disables (A11Y-305BD-01)
    const entries = Object.keys(parsed.profile).length;
    tellAll(
      `Imported ${entries - r.rejected.length}, ${r.rejected.length} refused. ${IMPORT_REST}`,
    );
  }

  function onExport(): void {
    setExported(exportProfile(getBindings()));
    exportRef.current?.focus(); // already shown: refreshed in place
  }

  // Rows are memoised: the handlers they get never change identity, and call the latest closures.
  const latest = useRef({ tryBind, swap, resetOne, unbind });
  latest.current = { tryBind, swap, resetOne, unbind };
  const onBind = useCallback(
    (c: KeymapCommand, raw: string, ack?: boolean) => latest.current.tryBind(c, raw, ack),
    [],
  );
  const onSwap = useCallback((c: KeymapCommand, r: Refusal) => latest.current.swap(c, r), []);
  const onUnbind = useCallback((c: KeymapCommand) => latest.current.unbind(c), []);
  const onReset = useCallback((c: KeymapCommand) => latest.current.resetOne(c), []);

  return (
    <section aria-labelledby="hk-h" data-keymap-context="Settings">
      <h1 id="hk-h">Hotkeys</h1>
      {savesToServer() ? null : <p>Saved on this device only.</p>}
      <p>
        Trading commands (marked in the Context column) change the risk surface of your muscle
        memory: rebinding one is audited.
      </p>
      <div className="hk-noprint">
        <label>
          Search commands
          <input
            type="search"
            value={query}
            onChange={(e) => {
              setNotice(null); // a stale message must not pin its row under every later filter
              setQuery(e.target.value);
            }}
          />
        </label>
        <label>
          Context
          <select
            value={ctx}
            onChange={(e) => {
              setNotice(null);
              setCtx(e.target.value);
            }}
          >
            <option value={ALL}>All contexts</option>
            {CONTEXTS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => window.print()}>
          Print list
        </button>
      </div>
      <table>
        <caption>Current key bindings by context</caption>
        <thead>
          <tr>
            <th scope="col">Context</th>
            <th scope="col">Command</th>
            <th scope="col">Binding</th>
            <th scope="col" className="hk-noprint">
              Change
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((c) => (
            <Row
              key={c.id}
              cmd={c}
              binding={bindings.get(c.id) ?? c.defaultBinding}
              notice={notice?.id === c.id ? notice : null}
              onBind={onBind}
              onSwap={onSwap}
              onUnbind={onUnbind}
              onReset={onReset}
              onEdit={onEdit}
            />
          ))}
        </tbody>
      </table>
      {matched === 0 ? <p>No command matches.</p> : null}
      <button
        type="button"
        onClick={() => {
          setBindings(resetAll(getBindings()));
          reportHotkey({ name: "hotkey.reset" });
          tellAll("Every binding is back to its default.");
        }}
      >
        Reset all
      </button>
      <label>
        Import keymap (JSON)
        <textarea
          ref={importRef}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
      </label>
      <button type="button" disabled={importText.trim() === ""} onClick={onImport}>
        Import
      </button>
      <button type="button" onClick={onExport}>
        Export
      </button>
      {exported !== null ? (
        <label>
          Export keymap (JSON)
          <textarea ref={exportRef} readOnly value={exported} />
        </label>
      ) : null}
      {status !== null ? <p id="hk-status">{status}</p> : null}
      {report.length ? (
        <ul aria-label="Import report">
          {report.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

const Row = memo(function Row(props: {
  cmd: KeymapCommand;
  binding: string;
  notice: Notice | null;
  onBind: (c: KeymapCommand, raw: string, ack?: boolean) => void;
  onSwap: (c: KeymapCommand, r: Refusal) => void;
  onUnbind: (c: KeymapCommand) => void;
  onReset: (c: KeymapCommand) => void;
  onEdit: (id: string) => void;
}): JSX.Element {
  const { cmd, binding, notice, onBind, onSwap, onUnbind, onReset, onEdit } = props;
  const [recording, setRecording] = useState(false);
  const [mods, setMods] = useState<readonly string[]>([]);
  const [key, setKey] = useState("");
  const raw = [...MODS.filter((m) => mods.includes(m)), key].join("+");
  // `05` §3.3 rule 3: Esc and Ctrl+K are excluded from the remap UI (AC4; E10-D04 §15's words).
  const locked = commandMeta(cmd.id)?.remappable === false;
  const refusal = notice?.refusal ?? null;
  return (
    <tr onFocus={() => onEdit(cmd.id)}>
      <td>
        {cmd.context}
        {isDangerous(cmd) ? <span> (trading)</span> : null}
      </td>
      <th scope="row">{cmd.label}</th>
      <td>
        {binding === "" ? "unbound" : <kbd>{binding}</kbd>}
        {locked ? null : (
          <button
            type="button"
            className="hk-noprint"
            disabled={binding === ""}
            onClick={() => onUnbind(cmd)}
          >
            Unbind
            <ForRow cmd={cmd} />
          </button>
        )}
        {locked ? null : (
          <button
            type="button"
            className="hk-noprint"
            disabled={binding === cmd.defaultBinding}
            onClick={() => onReset(cmd)}
          >
            Reset
            <ForRow cmd={cmd} />
          </button>
        )}
      </td>
      <td className="hk-noprint">
        {locked ? (
          "not remappable"
        ) : (
          <>
            {MODS.map((m) => (
              <label key={m}>
                <input
                  type="checkbox"
                  checked={mods.includes(m)}
                  onChange={(e) =>
                    setMods(e.target.checked ? [...mods, m] : mods.filter((x) => x !== m))
                  }
                />
                {m}
                <ForRow cmd={cmd} joiner=" for " />
              </label>
            ))}
            {/* The field sits inside its label: an implicit association, which jsdom (and a reader's tree) resolves
                without a document-wide id search per label. */}
            <label>
              Key
              <ForRow cmd={cmd} joiner=" for " />
              <input
                id={`hk-key-${cmd.id}`}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                size={6}
              />
            </label>
            <button
              type="button"
              aria-pressed={recording}
              onClick={() => {
                setRecording(!recording);
                say(recording ? "Recording cancelled." : "Press the keys now. Esc cancels.");
              }}
              onBlur={() => {
                if (!recording) return;
                setRecording(false);
                say("Recording cancelled.");
              }}
              onKeyDown={(e) => {
                if (!recording) return;
                if (e.key === "Tab") {
                  // Tab keeps moving focus (WCAG 2.1.2); leaving the button cancels the recording.
                  setRecording(false);
                  return say("Recording cancelled.");
                }
                e.preventDefault();
                e.stopPropagation();
                if (e.key === "Escape") {
                  setRecording(false);
                  return say("Recording cancelled.");
                }
                if (["Control", "Alt", "Shift", "Meta"].includes(e.key)) return; // wait for the key
                const hit = normaliseBinding(eventBinding(e.nativeEvent));
                setRecording(false);
                if (hit === null) return say("That key cannot be bound. Choose another.");
                const prefix = MODS.filter((m) => hit.split("+").includes(m));
                setMods(prefix);
                setKey(hit.slice(prefix.map((m) => `${m}+`).join("").length));
                say(`Captured ${hit}. Choose Save to apply it.`);
              }}
            >
              Record
              <ForRow cmd={cmd} />
            </button>
            {recording ? <span> Press keys now (Esc cancels)</span> : null}
            <button
              id={`hk-save-${cmd.id}`}
              type="button"
              disabled={!key}
              onClick={() => onBind(cmd, raw)}
            >
              Save
              <ForRow cmd={cmd} />
            </button>
          </>
        )}
        {notice !== null ? (
          <div id="hk-msg">
            <p>{notice.text}</p>
            {refusal?.swap ? (
              <button type="button" onClick={() => onSwap(cmd, refusal)}>
                Swap
              </button>
            ) : null}
            {refusal?.problem.kind === "unsafe-destructive" ? (
              <button
                type="button"
                onClick={() => {
                  onBind(cmd, refusal.raw, true);
                  focusIn(cmd.id, "save");
                }}
              >
                I understand, bind anyway
              </button>
            ) : null}
          </div>
        ) : null}
      </td>
    </tr>
  );
});
