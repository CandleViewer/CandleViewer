/**
 * SCR-090 alerts centre (E40-S01 Part A): tabs All / Fired / Snoozed, filters, a table of alert rows,
 * row and bulk actions with per-item results, firing history and the states of E40-D02 §2.5.
 * Server truth only: no alert is created here, and every write is a REST call the server authorises.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from "react";
import {
  Button,
  Callout,
  ConfirmDialog,
  EmptyState,
  ForbiddenState,
  Icon,
  SearchBox,
  Select,
  Tabs,
  Table,
  Toggle,
  type MenuItem,
  type TableColumn,
} from "@candleviewer/ui";
import { getMeClaims } from "../../lib/auth/meCache";
import { getActiveClient } from "../../lib/ws/client/activeClient";
import { useWsState } from "../../lib/ws/client/useWsState";
import { AlertHistoryDialog } from "./AlertHistoryDialog";
import { alertsApi, type AlertsApi, type AlertsFailure } from "./alertsApi";
import { startAlertsBridge, type AlertsFrameSource } from "./alertsBridge";
import { COPY } from "./alertsCopy";
import { alertsStore, useAlerts, type AlertsStore } from "./alertsStore";
import {
  describeCondition,
  failedDesktopAlerts,
  groupOf,
  inTab,
  matchesStatus,
  metricsOf,
  sortRows,
  statusOf,
  STATUS_WORD,
  TRIGGER_WORDS,
  type StatusFilter,
  type StatusKey,
} from "./alertRowModel";
import { ALERT_TABS, hasFired, isSnoozed, type AlertTab } from "./alertStatus";
import { runBulkAction, type BulkAction, type BulkRunner } from "./bulkActions";
import { SNOOZE_PRESETS, SNOOZE_PRESET_MS, snoozeFromPreset, snoozeUntil } from "./snooze";
import { nextLocalMidnightMs } from "./snoozeTomorrow";
import { createWsAlertsSource } from "./alertsWsSource";
import type { Alert, VocabularySignal } from "./types";

const STATUS_ICON = {
  armed: "notifications",
  fired: "success",
  snoozed: "pending",
  disarmed: "disconnected",
  disabled: "hide",
  expired: "calendar",
} as const;
const CHANNEL_WORD: Readonly<Record<string, string>> = {
  in_app: "In app",
  desktop: "Desktop",
  email: "Email",
  webhook: "Webhook",
  push: "Push",
};
const MAX_ROWS = 200;
const MINUTE_MS = 60_000;
const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "attention", label: "Needs attention" },
  { value: "armed", label: "Armed" },
  { value: "not_armed", label: "Not armed" },
  { value: "snoozed", label: "Snoozed" },
];

export interface AlertsScreenProps {
  readonly api?: AlertsApi;
  readonly store?: AlertsStore;
  /** The `alerts` topic; the shell's WS client by default. */
  readonly source?: AlertsFrameSource;
  readonly permissions?: readonly string[];
  readonly now?: () => number;
  readonly timeZone?: string;
  readonly onShowOnChart?: (alert: Alert) => void;
  readonly notificationsHref?: string;
  readonly download?: (filename: string, text: string) => void;
  /** Monotonic clock for the confirm dialog's early-press guard (C-4.14); tests inject one. */
  readonly confirmNow?: () => number;
}

type Confirm =
  | { readonly kind: "bulk"; readonly action: Exclude<BulkAction, "snooze" | "unsnooze"> }
  | { readonly kind: "delete"; readonly alert: Alert }
  | { readonly kind: "enable"; readonly alert: Alert };

const utcClock = (ms: number): string => `${new Date(ms).toISOString().slice(11, 16)} UTC`;
const dayClock = (ms: number): string =>
  `${new Date(ms).toISOString().slice(0, 19).replace("T", " ")} UTC`;

export function AlertsScreen(props: AlertsScreenProps): JSX.Element {
  const api = props.api ?? alertsApi;
  const store = props.store ?? alertsStore;
  const permissions = props.permissions ?? getMeClaims().permissions;
  const canRead = permissions.includes("alerts:read");
  const canWrite = permissions.includes("alerts:write");
  const clock = useMemo(() => ({ now: props.now ?? Date.now }), [props.now]);
  const timeZone = props.timeZone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const alerts = useAlerts(store);
  const link = useWsState().link.kind;

  const [load, setLoad] = useState<"loading" | "ready" | AlertsFailure>("loading");
  const [resyncing, setResyncing] = useState(false);
  const [signals, setSignals] = useState<ReadonlyMap<string, VocabularySignal> | null>(null);
  const [vocabularyDown, setVocabularyDown] = useState(false);
  const [failed, setFailed] = useState<ReadonlySet<string>>(new Set());
  const [tab, setTab] = useState<AlertTab>("all");
  const [symbol, setSymbol] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [history, setHistory] = useState<Alert | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(clock.now());

  // Remaining snooze time refreshes at most once a minute (T-6).
  useEffect(() => {
    const id = setInterval(() => setNowMs(clock.now()), MINUTE_MS);
    return () => clearInterval(id);
  }, [clock]);

  const refresh = useCallback(
    async (signal?: AbortSignal): Promise<void> => {
      const out = await api.list(signal);
      const stale = (): boolean => signal?.aborted === true;
      if (stale()) return;
      if (out.kind !== "ok") return setLoad(out.kind);
      store.replaceAll(out.value);
      setLoad("ready");
      setResyncing(false);
      setNowMs(clock.now());
      const bad = await api.deliveries({ status: "failed" }, signal);
      if (!stale() && bad.kind === "ok") setFailed(failedDesktopAlerts(bad.value, out.value));
    },
    [api, store, clock],
  );

  useEffect(() => {
    if (!canRead) return;
    const controller = new AbortController();
    void refresh(controller.signal);
    void api.vocabulary(controller.signal).then((out) => {
      if (controller.signal.aborted) return;
      setVocabularyDown(out.kind !== "ok");
      if (out.kind === "ok") setSignals(new Map(out.value.map((s) => [s.id, s])));
    });
    return () => controller.abort();
  }, [api, canRead, refresh]);

  const source = props.source;
  useEffect(() => {
    if (!canRead) return;
    const feed =
      source ??
      createWsAlertsSource(getActiveClient, () => {
        setResyncing(true);
        void refresh();
      });
    return startAlertsBridge(feed, store);
  }, [canRead, source, store, refresh]);

  const groupFor = useCallback(
    (a: Alert) => groupOf(statusOf(a, nowMs), failed.has(a.id as string)),
    [nowMs, failed],
  );
  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const kept = alerts.filter(
      (a) =>
        inTab(a, tab, nowMs) &&
        (symbol === "all" || a.symbol === symbol) &&
        matchesStatus(groupFor(a), statusFilter) &&
        (needle === "" || a.name.toLowerCase().includes(needle)),
    );
    return sortRows(kept, tab, groupFor);
  }, [alerts, tab, nowMs, symbol, statusFilter, search, groupFor]);
  const counts = useMemo(
    () => ({
      all: alerts.length,
      fired: alerts.filter(hasFired).length,
      snoozed: alerts.filter((a) => isSnoozed(a, nowMs)).length,
    }),
    [alerts, nowMs],
  );
  const symbols = useMemo(
    () => [...new Set(alerts.flatMap((a) => (a.symbol == null ? [] : [a.symbol])))].sort(),
    [alerts],
  );

  // "Showing N of M" is announced when the filters change, never on a live update (LR-8).
  const latest = useRef({ shown: rows.length, total: alerts.length });
  latest.current = { shown: rows.length, total: alerts.length };
  const [announce, setAnnounce] = useState("");
  useEffect(() => {
    if (load === "ready") setAnnounce(COPY.showing(latest.current.shown, latest.current.total));
  }, [load, tab, symbol, statusFilter, search]);

  const failure = (kind: AlertsFailure): string =>
    kind === "forbidden" ? COPY.readOnly : COPY.failReason[kind];

  const act = async (
    run: () => Promise<{ kind: string; value?: unknown }>,
    done: (v: never) => void,
  ): Promise<void> => {
    setProblem(null);
    const out = await run();
    if (out.kind === "ok") return done(out.value as never);
    setProblem(failure(out.kind as AlertsFailure));
  };
  const setEnabled = (a: Alert, enabled: boolean): Promise<void> =>
    act(
      () => api.setEnabled(a.id as string, enabled),
      (next: Alert) => store.upsert(next),
    );
  const snooze = (a: Alert, until: string | null): Promise<void> =>
    act(
      () => api.setSnooze(a.id as string, until),
      (next: Alert) => store.upsert(next),
    );
  const removeOne = (a: Alert): Promise<void> =>
    act(
      () => api.remove(a.id as string),
      () => {
        store.remove(a.id as string);
        setSelected((s) => new Set([...s].filter((id) => id !== a.id)));
      },
    );

  const runBulk = async (action: "enable" | "disable" | "delete"): Promise<void> => {
    const names = new Map(alerts.map((a) => [a.id as string, a.name]));
    const runner: BulkRunner = async (kind, id) => {
      const out =
        kind === "delete" ? await api.remove(id) : await api.setEnabled(id, kind === "enable");
      if (out.kind !== "ok") throw new Error(failure(out.kind));
    };
    const result = await runBulkAction(action, [...selected], runner);
    const lines = result.outcomes.flatMap((o) =>
      o.ok ? [] : [`'${names.get(o.id) ?? o.id}' — ${o.error}`],
    );
    setReport(
      `${result.summary.ok} of ${result.summary.total} ${COPY.bulkDone[action]}.` +
        (lines.length > 0 ? ` ${lines.length} failed: ${lines.join("; ")}.` : ""),
    );
    setSelected(new Set(result.failedIds));
    await refresh();
  };

  const snoozeItems = (a: Alert): MenuItem[] => [
    ...SNOOZE_PRESETS.filter((p) => p !== "4h" && p !== "24h").map((p) => ({
      id: `snooze-${p}`,
      label: p.replace("m", " min").replace("1h", "1 h"),
      description: `Until ${utcClock(clock.now() + SNOOZE_PRESET_MS[p])}`,
      onSelect: () => {
        const r = snoozeFromPreset(p, clock);
        if (r.ok) void snooze(a, r.until);
      },
    })),
    (() => {
      const end = nextLocalMidnightMs(clock.now(), timeZone);
      return {
        id: "snooze-tomorrow",
        label: "Until tomorrow",
        description: `00:00 ${timeZone} (${utcClock(end)})`,
        onSelect: () => {
          const r = snoozeUntil(end, clock);
          if (r.ok) void snooze(a, r.until);
        },
      };
    })(),
  ];

  const rowActions = (a: Alert): MenuItem[] => {
    const key = statusOf(a, nowMs);
    const write: MenuItem[] = !canWrite
      ? []
      : [
          isSnoozed(a, nowMs)
            ? { id: "wake", label: COPY.actions.wake, onSelect: () => void snooze(a, null) }
            : { id: "snooze", label: `${COPY.actions.snooze} ▸`, items: snoozeItems(a) },
          a.enabled === false
            ? {
                id: "enable",
                label: COPY.actions.enable,
                onSelect: () =>
                  key === "disarmed"
                    ? setConfirm({ kind: "enable", alert: a })
                    : void setEnabled(a, true),
              }
            : {
                id: "disable",
                label: COPY.actions.disable,
                onSelect: () => void setEnabled(a, false),
              },
          {
            id: "duplicate",
            label: COPY.actions.duplicate,
            disabledReason: COPY.actions.duplicateDisabled,
            onSelect: () => undefined,
          },
        ];
    return [
      ...write,
      { id: "chart", label: COPY.actions.chart, onSelect: () => props.onShowOnChart?.(a) },
      { id: "history", label: COPY.actions.history, onSelect: () => setHistory(a) },
      ...(canWrite
        ? [
            {
              id: "delete",
              label: COPY.actions.delete,
              danger: true,
              opensConfirm: true,
              onSelect: () => setConfirm({ kind: "delete", alert: a }),
            } as MenuItem,
          ]
        : []),
    ];
  };

  const statusCell = (a: Alert): JSX.Element => {
    const key: StatusKey = statusOf(a, nowMs);
    const until = Date.parse(a.snoozed_until ?? "");
    const metric =
      metricsOf((a.condition_ir as { conditions?: unknown }).conditions)[0] ?? "metric";
    return (
      <span>
        <Icon name={STATUS_ICON[key]} /> {STATUS_WORD[key]}
        {key === "snoozed"
          ? ` until ${utcClock(until)} (${Math.max(1, Math.ceil((until - nowMs) / MINUTE_MS))} min)`
          : null}
        {key === "disarmed" ? (
          <span>
            {" "}
            {COPY.disarmTitle(signals?.get(metric)?.display_name ?? metric)}. {COPY.disarmWhy}
            {canWrite ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setConfirm({ kind: "enable", alert: a })}
              >
                {`${COPY.actions.enable}…`}
              </Button>
            ) : null}
          </span>
        ) : null}
      </span>
    );
  };

  const columns: TableColumn<Alert>[] = [
    { id: "name", header: "Name", cell: (a) => a.name },
    { id: "symbol", header: "Symbol", cell: (a) => a.symbol ?? "Any symbol" },
    {
      id: "condition",
      header: "Condition",
      cell: (a) => {
        const c = describeCondition(a, signals);
        return `${c.text}${c.estimated ? ` ${COPY.estimated}` : ""} · ${TRIGGER_WORDS[a.trigger_mode ?? "once"] ?? a.trigger_mode}`;
      },
    },
    { id: "status", header: "Status", cell: statusCell },
    {
      id: "last",
      header: "Last fired",
      cell: (a) =>
        a.last_fired_at == null
          ? "never"
          : `${dayClock(Date.parse(a.last_fired_at))}${(a.fire_count ?? 0) > 1 ? ` · ${a.fire_count} times` : ""}`,
    },
    {
      id: "delivery",
      header: "Delivery",
      cell: (a) => {
        const bad = failed.has(a.id as string);
        const words = (a.channels ?? []).map((c) =>
          bad && c === "desktop" ? COPY.deliveryChip : (CHANNEL_WORD[c] ?? c),
        );
        return (
          <span>
            {bad ? <Icon name="danger" /> : null} {words.join(" · ")}
            {bad ? <span> {COPY.deliveryProblem}</span> : null}
          </span>
        );
      },
    },
    ...(canWrite
      ? [
          {
            id: "active",
            header: "Active",
            interactive: true,
            cell: (a: Alert) => (
              <Toggle
                label={`Active: ${a.name}`}
                labelPosition="hidden"
                checked={a.enabled !== false}
                onChange={(on) => void setEnabled(a, on)}
              />
            ),
          } satisfies TableColumn<Alert>,
        ]
      : []),
  ];

  if (!canRead)
    return <ForbiddenState capability={COPY.forbiddenCapability} homeHref="/terminal" />;

  const filtersActive = symbol !== "all" || statusFilter !== "all" || search !== "";
  const clearFilters = (): void => {
    setSymbol("all");
    setStatusFilter("all");
    setSearch("");
  };
  const emptyState =
    alerts.length === 0 ? (
      <EmptyState title={COPY.empty} description={COPY.emptyBody} />
    ) : filtersActive ? (
      <EmptyState
        variant="filtered-empty"
        title={COPY.filteredEmpty}
        cta={{ label: COPY.clearFilters, onClick: clearFilters }}
      />
    ) : (
      <EmptyState variant="filtered-empty" title={COPY.tabEmpty[tab]} />
    );
  const tableError =
    typeof load === "string" && load !== "loading" && load !== "ready"
      ? {
          message: `${COPY.errorTitle} ${load === "unavailable" ? COPY.errorCause.unavailable : COPY.failReason[load]}`,
          onRetry: () => {
            setLoad("loading");
            void refresh();
          },
        }
      : undefined;
  const dialog = confirm === null ? null : confirmProps(confirm, selected.size);
  const panel = (
    <>
      {selected.size > 0 && canWrite ? (
        <div role="toolbar" aria-label="Bulk actions">
          <span>{COPY.selected(selected.size)}</span>
          <Button
            variant="secondary"
            onClick={() => setConfirm({ kind: "bulk", action: "enable" })}
          >
            Enable
          </Button>
          <Button
            variant="secondary"
            onClick={() => setConfirm({ kind: "bulk", action: "disable" })}
          >
            Disable
          </Button>
          <Button variant="danger" onClick={() => setConfirm({ kind: "bulk", action: "delete" })}>
            Delete…
          </Button>
          <Button variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      ) : (
        <div role="search" aria-label="Filter alerts">
          <Select
            aria-label="Symbol"
            value={symbol}
            onChange={setSymbol}
            options={[
              { value: "all", label: "All symbols" },
              ...symbols.map((s) => ({ value: s, label: s })),
            ]}
          />
          <Select
            aria-label="Status"
            value={statusFilter}
            onChange={(v) => setStatusFilter(v as StatusFilter)}
            options={STATUS_OPTIONS}
          />
          <SearchBox
            label="Search names"
            value={search}
            onChange={setSearch}
            onClear={() => setSearch("")}
          />
        </div>
      )}
      <Table
        caption={COPY.heading}
        captionHidden
        columns={columns}
        rows={rows.slice(0, MAX_ROWS)}
        rowKey={(a) => a.id as string}
        rowLabel={(a) => a.name}
        density="compact"
        loading={load === "loading"}
        loadingText={COPY.loading}
        {...(tableError === undefined ? {} : { error: tableError })}
        emptyState={emptyState}
        rowActions={rowActions}
        {...(canWrite ? { selected, onRowSelect: setSelected } : {})}
      />
    </>
  );

  return (
    <div>
      <header>
        <h1>{COPY.heading}</h1>
        {canWrite ? (
          <Button variant="primary" disabled disabledReason={COPY.newAlertDisabled}>
            {COPY.newAlert}
          </Button>
        ) : null}
      </header>
      {link === "offline" || link === "reconnecting" ? (
        <Callout tone="warning" title={COPY.disconnected} />
      ) : null}
      {resyncing ? <p role="status">{COPY.resyncing}</p> : null}
      {vocabularyDown ? <Callout tone="warning" title={COPY.vocabularyDown} live="polite" /> : null}
      {problem === null ? null : <Callout tone="danger" title={problem} />}
      <p role="status" aria-live="polite">
        {report ?? announce}
      </p>
      <Tabs
        aria-label={COPY.heading}
        tabs={ALERT_TABS.map((id) => ({ id, label: `${COPY.tabs[id]} ${counts[id]}` }))}
        value={tab}
        onChange={(id) => setTab(id as AlertTab)}
        renderPanel={() => panel}
      />
      {dialog === null || confirm === null ? null : (
        <ConfirmDialog
          open
          {...(props.confirmNow === undefined ? {} : { now: props.confirmNow })}
          title={dialog.title}
          message={dialog.body}
          confirmLabel={dialog.confirm}
          confirmVariant={
            confirm.kind === "enable"
              ? "primary"
              : confirm.kind === "bulk" && confirm.action !== "delete"
                ? "primary"
                : "danger"
          }
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            setConfirm(null);
            if (confirm.kind === "bulk") void runBulk(confirm.action);
            else if (confirm.kind === "delete") void removeOne(confirm.alert);
            else void setEnabled(confirm.alert, true);
          }}
        />
      )}
      {history === null ? null : (
        <AlertHistoryDialog
          alert={history}
          api={api}
          onClose={() => setHistory(null)}
          notificationsHref={props.notificationsHref}
          {...(props.download === undefined ? {} : { download: props.download })}
        />
      )}
    </div>
  );
}

function confirmProps(c: Confirm, count: number): { title: string; body: string; confirm: string } {
  if (c.kind === "bulk") {
    const b = COPY.bulk[c.action];
    return { title: b.title(count), body: b.body, confirm: b.confirm(count) };
  }
  if (c.kind === "delete")
    return {
      title: COPY.deleteOne.title(c.alert.name),
      body: COPY.bulk.delete.body,
      confirm: COPY.deleteOne.confirm,
    };
  return { title: `Enable ${c.alert.name}?`, body: COPY.enableConfirm, confirm: "Enable" };
}
