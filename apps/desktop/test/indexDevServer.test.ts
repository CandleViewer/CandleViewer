import { afterAll, expect, it, vi, type Mock } from "vitest";
import { BrowserWindow, ipcMain, type IpcMainInvokeEvent } from "electron";

// index.ts decides on CV_DEV_SERVER_URL once, in its whenReady wiring, and hands that one decision
// to both the IPC sender check and the main window. index.test.ts imports it with no dev server
// set; this file imports it with one set, so that wiring itself is what runs (#3608).
vi.mock("electron", () => ({
  app: {
    on: vi.fn(),
    whenReady: vi.fn().mockResolvedValue(undefined),
    emit: vi.fn(),
    requestSingleInstanceLock: vi.fn().mockReturnValue(true),
    commandLine: { appendSwitch: vi.fn() },
    isPackaged: false,
  },
  BrowserWindow: vi.fn().mockImplementation(() => ({
    webContents: { setWindowOpenHandler: vi.fn(), on: vi.fn() },
    once: vi.fn(),
    loadURL: vi.fn(),
  })),
  session: {
    defaultSession: {
      webRequest: { onHeadersReceived: vi.fn() },
      setPermissionRequestHandler: vi.fn(),
    },
  },
  ipcMain: { handle: vi.fn() },
  protocol: { registerSchemesAsPrivileged: vi.fn(), handle: vi.fn() },
  shell: { openExternal: vi.fn() },
}));
vi.mock("../src/main/logger", () => ({ logStartup: vi.fn(), logAuditEvent: vi.fn() }));

vi.stubEnv("CV_DEV_SERVER_URL", "http://localhost:5173");
const { IpcSenderRefusedError } = await import("../src/main/index");
afterAll(() => vi.unstubAllEnvs());

/** Calls the KEK-handle channel from the main frame of a page on `url`. */
function kekHandleFrom(url: string): unknown {
  const channel = "cv:keychain:getKekHandle";
  const listener = vi.mocked(ipcMain.handle).mock.calls.find(([name]) => name === channel)?.[1];
  const mainFrame = { url, parent: null };
  const event = { senderFrame: mainFrame, sender: { mainFrame } } as unknown as IpcMainInvokeEvent;
  return (listener as (event: IpcMainInvokeEvent) => unknown)(event);
}

it("one dev-server decision feeds both the main window and the IPC sender check (#3608)", async () => {
  await vi.waitFor(() => expect(BrowserWindow).toHaveBeenCalledTimes(1));
  const win = vi.mocked(BrowserWindow).mock.results[0]?.value as { loadURL: Mock };
  expect(win.loadURL).toHaveBeenCalledWith("http://localhost:5173/");
  expect(kekHandleFrom("http://localhost:5173/terminal")).toMatch(/^kek-handle-/);
  expect(() => kekHandleFrom("app://candleviewer/")).toThrow(IpcSenderRefusedError);
});
