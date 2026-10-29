import { describe, expect, it, vi } from "vitest";
import { CRASH_LOG_AUDIT_BURST, CRASH_LOG_AUDIT_WINDOW_MS } from "../src/main/crashLog";
import { parseGpuCrash } from "../src/main/gpuCrash";
import {
  GPU_RELAUNCH_MARKER,
  GPU_RETRY_INTERVAL_MS,
  GpuKeepRefusedError,
  GpuRetryRefusedError,
  createGpuRecovery,
} from "../src/main/gpuRecovery";

const AT = 1_700_000_000_000;
/** What Electron's child-process-gone hands main for a GPU crash, platform fields included. */
const GPU_GONE = { type: "GPU", reason: "crashed", exitCode: 139, name: "GPU" };

/** A recovery started at AT with `argv`, on a settable clock, its relaunch and audit observable. */
function setup(argv: readonly string[] = []) {
  const clock = { now: AT };
  const relaunch = vi.fn();
  const audit = vi.fn();
  const recovery = createGpuRecovery({ argv, relaunch, audit, now: () => clock.now });
  return { clock, relaunch, audit, recovery };
}

describe("createGpuRecovery: the cv:gpu:crashed payload (F15)", () => {
  it("counts each GPU crash: its time, the restarts this session and the reason, nothing more", () => {
    const { clock, recovery, audit } = setup();
    const first = { crashedAtMs: AT, restartCount: 1, reason: "crashed" };
    expect(recovery.childProcessGone(GPU_GONE)).toEqual(first);
    clock.now = AT + 5;
    const odd = { ...GPU_GONE, reason: "C:\\drivers\\gpu.dll fault at 0x0" };
    const second = { crashedAtMs: AT + 5, restartCount: 2, reason: "unknown" };
    expect(recovery.childProcessGone(odd)).toEqual(second);
    expect(audit.mock.calls).toEqual([
      ["gpu-process-gone", { reason: "crashed", restartCount: 1 }],
      ["gpu-process-gone", { reason: "unknown", restartCount: 2 }],
    ]);
  });

  it.each(["Utility", "Zygote", "Sandbox helper", "Pepper Plugin", "Unknown"])(
    "a %s process going emits and counts nothing",
    (type) => {
      const { recovery, audit } = setup();
      expect(recovery.childProcessGone({ ...GPU_GONE, type })).toBeUndefined();
      expect(audit).not.toHaveBeenCalled();
      expect(recovery.childProcessGone(GPU_GONE)?.restartCount).toBe(1);
    },
  );
});

describe("createGpuRecovery: cv:gpu:retry relaunches the app", () => {
  it("refuses before any GPU crash this session, audits the reason only, never relaunches", () => {
    const { recovery, relaunch, audit } = setup();
    recovery.childProcessGone({ ...GPU_GONE, type: "Utility" });
    expect(() => recovery.retry()).toThrow(GpuRetryRefusedError);
    expect(relaunch).not.toHaveBeenCalled();
    expect(audit.mock.calls).toEqual([["gpu-retry-refused", { reason: "no-crash" }]]);
    expect(String(new GpuRetryRefusedError())).toBe("GpuRetryRefusedError: GPU retry refused");
  });

  it("relaunches after a crash, then refuses as rate-limited until the interval has passed", () => {
    const { clock, recovery, relaunch, audit } = setup();
    recovery.childProcessGone(GPU_GONE);
    recovery.retry();
    clock.now = AT + GPU_RETRY_INTERVAL_MS - 1;
    expect(() => recovery.retry()).toThrow(GpuRetryRefusedError);
    expect(relaunch).toHaveBeenCalledTimes(1);
    clock.now = AT + GPU_RETRY_INTERVAL_MS;
    recovery.retry();
    expect(relaunch).toHaveBeenCalledTimes(2);
    expect(audit.mock.calls.slice(1)).toEqual([
      ["gpu-retry-accepted", { restartCount: 1 }],
      ["gpu-retry-refused", { reason: "rate-limited" }],
      ["gpu-retry-accepted", { restartCount: 1 }],
    ]);
  });

  it("relaunches with this launch's arguments plus the marker; a near-miss token is no marker", () => {
    const nearMiss = `${GPU_RELAUNCH_MARKER}=1`;
    const { recovery, relaunch } = setup(["--x", nearMiss]);
    recovery.childProcessGone(GPU_GONE);
    recovery.retry();
    expect(relaunch.mock.calls).toEqual([[["--x", nearMiss, "--cv-gpu-relaunched"]]]);
  });

  it("a relaunched session waits the interval from its start, then keeps the marker once", () => {
    const { clock, recovery, relaunch, audit } = setup(["--x", GPU_RELAUNCH_MARKER]);
    expect(() => recovery.retry()).toThrow(GpuRetryRefusedError);
    expect(audit).toHaveBeenLastCalledWith("gpu-retry-refused", { reason: "no-crash" });
    recovery.childProcessGone(GPU_GONE);
    clock.now = AT + GPU_RETRY_INTERVAL_MS - 1;
    expect(() => recovery.retry()).toThrow(GpuRetryRefusedError);
    expect(audit).toHaveBeenLastCalledWith("gpu-retry-refused", { reason: "rate-limited" });
    clock.now = AT + GPU_RETRY_INTERVAL_MS;
    recovery.retry();
    expect(relaunch.mock.calls).toEqual([[["--x", GPU_RELAUNCH_MARKER]]]);
  });

  it("bounds refusal audits per reason per window, then writes one summary with the count", () => {
    const { clock, recovery, audit } = setup();
    const flood = 50;
    for (let i = 0; i < flood; i += 1) {
      expect(() => recovery.retry()).toThrow(GpuRetryRefusedError);
    }
    const refused = ["gpu-retry-refused", { reason: "no-crash" }];
    expect(audit.mock.calls).toEqual(Array.from({ length: CRASH_LOG_AUDIT_BURST }, () => refused));
    clock.now = AT + CRASH_LOG_AUDIT_WINDOW_MS;
    expect(() => recovery.retry()).toThrow(GpuRetryRefusedError);
    const suppressed = flood - CRASH_LOG_AUDIT_BURST;
    const summary = { event: "gpu-retry-refused", reason: "no-crash", suppressed };
    expect(audit.mock.calls.slice(CRASH_LOG_AUDIT_BURST)).toEqual([
      ["gpu-retry-audit-suppressed", summary],
      refused,
    ]);
  });
});

describe("createGpuRecovery: cv:gpu:info's lastCrash (#4951)", () => {
  it("is null before a GPU crash, then the last one as sent, not retried; another process is none", () => {
    const { clock, recovery } = setup();
    expect(recovery.lastCrash()).toBeNull();
    recovery.childProcessGone({ ...GPU_GONE, type: "Utility" });
    expect(recovery.lastCrash()).toBeNull();
    const first = recovery.childProcessGone(GPU_GONE);
    expect(recovery.lastCrash()).toEqual({ ...first, retried: false, kept: false });
    clock.now = AT + 5;
    const second = recovery.childProcessGone({ ...GPU_GONE, reason: "oom" });
    expect(recovery.lastCrash()).toEqual({ ...second, retried: false, kept: false });
  });

  it("is retried once a retry is accepted after it; a refused retry or a newer crash is not", () => {
    const { clock, recovery } = setup();
    const first = recovery.childProcessGone(GPU_GONE);
    recovery.retry();
    expect(recovery.lastCrash()).toEqual({ ...first, retried: true, kept: false });
    const second = recovery.childProcessGone(GPU_GONE);
    expect(() => recovery.retry()).toThrow(GpuRetryRefusedError); // rate-limited
    expect(recovery.lastCrash()).toEqual({ ...second, retried: false, kept: false });
    clock.now = AT + GPU_RETRY_INTERVAL_MS;
    recovery.retry();
    expect(recovery.lastCrash()).toEqual({ ...second, retried: true, kept: false });
  });

  it("a relaunched launch has none until its own crash, which no retry has answered", () => {
    const { recovery } = setup([GPU_RELAUNCH_MARKER]);
    expect(recovery.lastCrash()).toBeNull();
    const crash = recovery.childProcessGone(GPU_GONE);
    expect(recovery.lastCrash()).toEqual({ ...crash, retried: false, kept: false });
  });
});

describe("createGpuRecovery: cv:gpu:keepSoftware marks the last crash kept (#306)", () => {
  it("refuses before any GPU crash this launch, audits the reason only, and keeps nothing", () => {
    const { recovery, audit } = setup();
    recovery.childProcessGone({ ...GPU_GONE, type: "Utility" });
    expect(() => recovery.keepSoftware()).toThrow(GpuKeepRefusedError);
    expect(recovery.lastCrash()).toBeNull();
    expect(audit.mock.calls).toEqual([["gpu-keep-refused", { reason: "no-crash" }]]);
    expect(String(new GpuKeepRefusedError())).toBe("GpuKeepRefusedError: GPU keep refused");
  });

  it("keeps the last crash once: a second keep changes nothing and audits nothing", () => {
    const { recovery, audit } = setup();
    const crash = recovery.childProcessGone(GPU_GONE);
    recovery.keepSoftware();
    recovery.keepSoftware();
    expect(recovery.lastCrash()).toEqual({ ...crash, retried: false, kept: true });
    expect(audit.mock.calls.slice(1)).toEqual([["gpu-software-kept", { restartCount: 1 }]]);
  });

  it("a newer crash is not kept, and a relaunched launch has none to keep", () => {
    const { clock, recovery } = setup();
    recovery.childProcessGone(GPU_GONE);
    recovery.keepSoftware();
    clock.now = AT + 5;
    const newer = recovery.childProcessGone({ ...GPU_GONE, reason: "oom" });
    expect(recovery.lastCrash()).toEqual({ ...newer, retried: false, kept: false });
    const relaunched = setup([GPU_RELAUNCH_MARKER]).recovery;
    expect(() => relaunched.keepSoftware()).toThrow(GpuKeepRefusedError);
    expect(relaunched.lastCrash()).toBeNull();
  });

  it("bounds its refusal audits per reason per window, then writes one summary, as retry's are", () => {
    const { clock, recovery, audit } = setup();
    const flood = 50;
    for (let i = 0; i < flood; i += 1) {
      expect(() => recovery.keepSoftware()).toThrow(GpuKeepRefusedError);
    }
    const refused = ["gpu-keep-refused", { reason: "no-crash" }];
    expect(audit.mock.calls).toEqual(Array.from({ length: CRASH_LOG_AUDIT_BURST }, () => refused));
    clock.now = AT + CRASH_LOG_AUDIT_WINDOW_MS;
    expect(() => recovery.keepSoftware()).toThrow(GpuKeepRefusedError);
    const suppressed = flood - CRASH_LOG_AUDIT_BURST;
    const summary = { event: "gpu-keep-refused", reason: "no-crash", suppressed };
    expect(audit.mock.calls.slice(CRASH_LOG_AUDIT_BURST)).toEqual([
      ["gpu-keep-audit-suppressed", summary],
      refused,
    ]);
  });
});

describe("parseGpuCrash (the preload's check of cv:gpu:crashed)", () => {
  it("returns a fresh copy holding the three fields only", () => {
    const payload = { crashedAtMs: AT, restartCount: 2, reason: "killed", exitCode: 9 };
    const parsed = parseGpuCrash(payload);
    expect(parsed).toEqual({ crashedAtMs: AT, restartCount: 2, reason: "killed" });
    expect(parsed).not.toBe(payload);
    expect(Object.isFrozen(parsed)).toBe(true);
  });

  it.each([
    ["null", null],
    ["an array", [AT, 1, "crashed"]],
    ["a fractional time", { crashedAtMs: 1.5, restartCount: 1, reason: "crashed" }],
    ["a string count", { crashedAtMs: AT, restartCount: "1", reason: "crashed" }],
    ["a negative count", { crashedAtMs: AT, restartCount: -1, reason: "crashed" }],
    ["a reason off the list", { crashedAtMs: AT, restartCount: 1, reason: "segfault" }],
  ])("refuses %s", (_label, payload) => {
    expect(parseGpuCrash(payload)).toBeUndefined();
  });
});
