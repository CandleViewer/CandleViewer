// E17-T04 S5f-3 (ADR-0005, D13; 23 4.1; Q8): the tab's port to the worker, as the browser gives it. A SharedWorker serves every tab
// of the origin with one engine and one socket. A browser without one (Android Chrome; Electron's `app://` until it is a
// standard, secure scheme) runs the same file as a dedicated worker of the tab, which costs one socket a tab against the
// gateway's eight a user. Vite bundles the worker from the `new URL(..., import.meta.url)` of each call, so both stay literal.
import { portOf, type PortLike } from "../port/endpoint";

const NAME = "cv-ws";

export function openWorkerPort(): PortLike {
  if (typeof SharedWorker !== "undefined") {
    const shared = new SharedWorker(new URL("../worker/wsWorker.ts", import.meta.url), {
      type: "module",
      name: NAME,
    });
    return portOf(shared.port);
  }
  return portOf(
    new Worker(new URL("../worker/wsWorker.ts", import.meta.url), { type: "module", name: NAME }),
  );
}
