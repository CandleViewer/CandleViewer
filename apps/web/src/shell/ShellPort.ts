/**
 * ShellPort: the typed boundary between the renderer (this package) and
 * whatever desktop/browser shell hosts it. ADR-0011 (Electron vs Tauri) is
 * `proposed`; every shell-specific capability the app touches goes through
 * this interface so the decision stays reversible in practice, not just on
 * paper (`docs/plan/27-adrs/ADR-0011-electron-vs-tauri.md`).
 *
 * Source of truth for the responsibility list: ADR-0011 decision criterion 5
 * and `docs/plan/20-architecture.md` §2.2 C3. Each responsibility below maps
 * to exactly one named method or capability flag:
 *
 *   | Responsibility (ADR-0011 #5 / §2.2 C3)        | Port surface              |
 *   |------------------------------------------------|----------------------------|
 *   | Window management & multi-window persistence   | `windows.*`, `caps.floatingWindows` |
 *   | OS-keychain bridge for the KEK (opaque handle)  | `keychain.getKekHandle`, `caps.keychain` |
 *   | Auto-update                                     | `updates.*`, `caps.autoUpdate` |
 *   | Deep links                                      | `deepLinks.*`, `caps.deepLinks` |
 *   | Tray                                             | `tray.*`, `caps.tray` |
 *   | OS notifications                                | `notifications.*`, `caps.osNotifications` |
 *   | GPU info / flags, GPU-process crash (F15)       | `gpu.info`, `gpu.onCrashed`, `gpu.retry`, `gpu.keepSoftware`, `caps.gpuInfo` |
 *   | Crash log                                        | `crashLog.append`, `caps.crashLog` |
 *   | Playwright-drivability                          | not a runtime capability — verified by `apps/desktop/e2e` |
 *
 * No method here accepts a caller-supplied channel name (SR-111): the
 * Electron implementation's preload bridge exposes one named, typed function
 * per method, each backed by a compile-time-constant IPC channel validated on
 * both sides (see `apps/desktop/src/preload/allowList.ts`). This file itself
 * has zero Electron dependency — `apps/web` must never import `electron`
 * (C-3.5, enforced by `.dependency-cruiser.js` `web-not-to-desktop`).
 */

/** A monitor-relative window rectangle, persisted across restarts (US-SET-009). */
export interface WindowBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly monitorId: string;
}

/** One floated/re-docked pane's persisted layout state. */
export interface WindowState {
  readonly windowId: string;
  readonly paneId: string;
  readonly route: string;
  readonly bounds: WindowBounds;
}

export type UpdateStatus =
  | { readonly state: "idle" | "checking" | "up-to-date" }
  | { readonly state: "available"; readonly version: string }
  | { readonly state: "downloading"; readonly progressPct: number }
  | { readonly state: "ready-to-apply"; readonly version: string }
  | { readonly state: "error"; readonly reason: string };

export type TrayStatus = "ok" | "warn" | "error";

export interface CrashEntry {
  readonly timestampMs: number;
  /** Never includes secrets, tokens or full request/order payloads (C-12.6). */
  readonly message: string;
  readonly stack?: string;
  readonly context?: Readonly<Record<string, string>>;
}

export interface GpuInfo {
  readonly vendor: string;
  readonly renderer: string;
  readonly hardwareAccelerated: boolean;
  /** True if the WebGL2 context reports the extensions the chart engine needs. */
  readonly webgl2CapabilityParity: boolean;
  /** The desktop shell's last GPU-process crash this session, or null (#4951); a tab has none. */
  readonly lastCrash?: GpuLastCrash | null;
}

/** Why the desktop shell's GPU process went: Electron's reason, or "unknown" (F15). */
export type GpuCrashReason =
  | "clean-exit"
  | "abnormal-exit"
  | "killed"
  | "crashed"
  | "oom"
  | "launch-failed"
  | "integrity-failure"
  | "memory-eviction"
  | "unknown";

/** A GPU-process crash in the desktop shell (F15): no exit code or other platform text. */
export interface GpuCrash {
  readonly crashedAtMs: number;
  /** GPU-process restarts this session, this one included. */
  readonly restartCount: number;
  readonly reason: GpuCrashReason;
}

/** `GpuInfo.lastCrash`: the crash as it was pushed, and whether a retry or a keep came after it. */
export interface GpuLastCrash extends GpuCrash {
  readonly retried: boolean;
  readonly kept: boolean;
}

export interface DeepLinkPayload {
  readonly url: string;
  readonly receivedAtMs: number;
}

/**
 * Every optional capability the UI can query before deciding whether to
 * render a control at all. US-SET-009: an unavailable capability is *hidden
 * with a human-readable reason*, never shown disabled.
 */
export interface ShellCapabilities {
  readonly floatingWindows: boolean;
  readonly tray: boolean;
  readonly autoUpdate: boolean;
  readonly keychain: boolean;
  readonly osNotifications: boolean;
  readonly gpuInfo: boolean;
  readonly deepLinks: boolean;
  readonly crashLog: boolean;
  /** Reason string per unavailable capability key, e.g. `{ tray: "not available in a browser tab" }". */
  readonly reason: Readonly<Partial<Record<keyof Omit<ShellCapabilities, "reason">, string>>>;
}

export interface ShellPort {
  readonly capabilities: ShellCapabilities;

  readonly windows: {
    float(paneId: string, route: string): Promise<void>;
    redock(windowId: string): Promise<void>;
    saveState(state: readonly WindowState[]): Promise<void>;
    restoreState(): Promise<readonly WindowState[]>;
  };

  readonly tray: {
    setStatus(status: TrayStatus): Promise<void>;
  };

  readonly updates: {
    check(): Promise<UpdateStatus>;
    apply(): Promise<void>;
  };

  readonly keychain: {
    /** Opaque handle only — never key material in the renderer (SR-119). */
    getKekHandle(): Promise<string>;
  };

  readonly deepLinks: {
    onDeepLink(handler: (payload: DeepLinkPayload) => void): () => void;
  };

  readonly notifications: {
    show(title: string, body: string): Promise<void>;
  };

  readonly crashLog: {
    append(entry: CrashEntry): Promise<void>;
  };

  readonly gpu: {
    info(): Promise<GpuInfo>;
    /**
     * Each GPU-process crash in the desktop shell, the last one before the subscription included
     * (`GpuInfo.lastCrash`, read once, with its `kept`) unless a retry answered it; a no-op
     * subscription in a tab.
     */
    onCrashed(handler: (crash: GpuCrash) => void): () => void;
    /** Relaunches the desktop app with the GPU allowed again; refused in a browser tab. */
    retry(): Promise<void>;
    /** Marks the desktop shell's last GPU crash kept for this launch (#306); a no-op in a tab. */
    keepSoftware(): Promise<void>;
  };
}
