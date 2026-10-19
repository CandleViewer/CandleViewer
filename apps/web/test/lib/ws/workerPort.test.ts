// E17-T04 S5f-3 (ADR-0005; Q8): the tab's port to the worker. One engine and one socket for every tab where there is a shared
// worker, one worker of the tab's own where there is none; the module is a real worker file in both, built as an ES module.
import { afterEach, describe, expect, it, vi } from "vitest";
import { openWorkerPort } from "../../../src/lib/ws/client/workerPort";

afterEach(() => vi.unstubAllGlobals());

/** What a worker constructor is given, and the port or scope it hands back. */
function fakeWorker() {
  const made: {
    url: string;
    options: unknown;
    port: { postMessage: unknown; onmessage: unknown };
  }[] = [];
  class Fake {
    readonly port = { postMessage: vi.fn(), onmessage: null as unknown };
    postMessage = vi.fn();
    onmessage: unknown = null;
    constructor(url: URL, options: unknown) {
      made.push({ url: url.pathname, options, port: this.port });
    }
  }
  return { Fake, made };
}

describe("the worker's port", () => {
  it("is the port of a shared worker when there is one: one engine and one socket for every tab", () => {
    const shared = fakeWorker();
    const dedicated = fakeWorker();
    vi.stubGlobal("SharedWorker", shared.Fake);
    vi.stubGlobal("Worker", dedicated.Fake);
    const port = openWorkerPort();
    expect(shared.made).toHaveLength(1);
    expect(dedicated.made).toEqual([]);
    expect(shared.made[0]?.url).toMatch(/\/lib\/ws\/worker\/wsWorker\.ts$/);
    expect(shared.made[0]?.options).toEqual({ type: "module", name: "cv-ws" });
    const heard: unknown[] = [];
    port.listen((data) => heard.push(data)); // assigning onmessage is what starts a MessagePort
    port.postMessage({ t: "stop" }, []);
    expect(shared.made[0]?.port.postMessage).toHaveBeenCalledWith({ t: "stop" }, []);
    (shared.made[0]?.port.onmessage as (event: { data: unknown }) => void)({ data: "x" });
    expect(heard).toEqual(["x"]);
  });

  it("is a worker of the tab's own when there is no shared one", () => {
    const dedicated = fakeWorker();
    vi.stubGlobal("SharedWorker", undefined);
    vi.stubGlobal("Worker", dedicated.Fake);
    const port = openWorkerPort();
    expect(dedicated.made).toHaveLength(1);
    expect(dedicated.made[0]?.url).toMatch(/\/lib\/ws\/worker\/wsWorker\.ts$/);
    expect(dedicated.made[0]?.options).toEqual({ type: "module", name: "cv-ws" });
    expect(() => port.postMessage({ t: "stop" }, [])).not.toThrow();
  });
});
