// Throwaway runner: drives headless Chromium over CDP. Usage: node run-bench.mjs <chrome> <html> <ms> <reps>
// Env: ONLY=<name substring> limits the configs; SET=main|recycle picks the matrix (see mirror-bench.html).
// The browser's WebSocket endpoint is read from Chrome's stderr ("DevTools listening on …"); no HTTP call is made.
// <chrome> is a headless Chromium (e.g. chrome-headless-shell); WebSocket needs Node 22+, or Node 20 with --experimental-websocket.
/* global process, WebSocket, setTimeout, console */
import { spawn } from "node:child_process";
const [chrome, html, ms = "20000", reps = "3"] = process.argv.slice(2);
const p = spawn(
  chrome,
  ["--no-sandbox", "--disable-gpu", "--remote-debugging-port=0", "about:blank"],
  {
    stdio: ["ignore", "ignore", "pipe"],
  },
);
const endpoint = await new Promise((resolve, reject) => {
  let err = "";
  p.stderr.on("data", (d) => {
    err += d;
    const m = err.match(/DevTools listening on (\S+)/);
    if (m) resolve(m[1]);
  });
  p.on("exit", (code) => reject(new Error(`chrome exited (${code})`)));
});
const ws = new WebSocket(endpoint);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pend = new Map();
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) {
    pend.get(m.id)(m);
    pend.delete(m.id);
  }
};
const send = (method, params = {}, sessionId) =>
  new Promise((r) => {
    const i = ++id;
    pend.set(i, r);
    ws.send(JSON.stringify({ id: i, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
const { targetInfos } = (await send("Target.getTargets")).result;
const target = targetInfos.find((t) => t.type === "page");
const { sessionId } = (
  await send("Target.attachToTarget", { targetId: target.targetId, flatten: true })
).result;
await send(
  "Page.navigate",
  {
    url: `file://${html}?ms=${ms}&reps=${reps}&only=${process.env.ONLY || ""}&set=${process.env.SET || ""}`,
  },
  sessionId,
);
for (;;) {
  await new Promise((r) => setTimeout(r, 2000));
  const r = await send(
    "Runtime.evaluate",
    {
      expression: 'document.getElementById("out").textContent',
    },
    sessionId,
  );
  const v = r.result.result.value;
  if (v && v.startsWith("RESULT")) {
    console.log(v.slice(6));
    break;
  }
}
p.kill();
process.exit(0);
