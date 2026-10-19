# src/lib/ws

The web WebSocket client (E17-T04, #413; wire contract `docs/plan/23-ws-protocol.md`). It lands as
thirty-one stacked slices (S1, S1b, S2a to S2d, S3, S3b, S4a to S4h, S5a, S5a-2, S5b, S5b-2, S5c, S5d, S5d-2, S5d-3, S5e, S5e-2, S5e-3, S5f, S5f-2, S5f-3, S5g) and nothing here is
reachable from `main.tsx` until the last one wires it (C-4.13). State is a plain store read through
`useSyncExternalStore`; RxJS, Zustand and Jotai are not dependencies. Layers depend downwards:
`protocol` -> `state` -> `core` -> `policy` -> `client`/`port`/`worker`.

| Path                                    | Role                                                                            | Slice               |
| --------------------------------------- | ------------------------------------------------------------------------------- | ------------------- |
| `errorHandler.ts`, `errorMapping.ts`    | one `err` frame -> UI treatment table (E17-T05)                                 | landed              |
| `protocol/`, `api.ts`, `state/types.ts` | frames, codec, heatmap bucket; public surface; state types                      | S1                  |
| `state/reducer.ts`                      | pure connection-state reducer and initial state; EngineEvent in types.ts        | S1b                 |
| `core/` stream core                     | sequencer, snapshot assembler, subscriptions (registry), resync guard           | S2, S4a             |
| `policy/`                               | pacer, close policy, timers; throttle policy and ctl debounce                   | S3, S3b             |
| `core/connection.ts`                    | one socket: handshake, token, heartbeat, close policy, reconnect, re-auth       | S4b, S4c            |
| `core/engine.ts`                        | streams to `sub`/`unsub`/`resync`, replies, revocation, system, baselines       | S4d to S4h          |
| `core/flowControl.ts`                   | panes: throttles, collapsed topics, heatmap bucket                              | S4g, S4h            |
| `core/engine.ts`, `flowControl.ts`      | `rs` on `ctl`/`unsub`, SR-193 back-off, `rebaseline`, `changed`                 | S5a, S5a-2          |
| `core/`                                 | flow control, the `unsub` guard and revocations keyed by `(ch, rs)`             | #3439               |
| `port/`                                 | port messages (checked both ways); frame queue and buffer copies; `endpoint.ts` | S5b, S5b-2, S5e-2   |
| `worker/portHost.ts`                    | the shared worker's host: tabs, token over ports, state; then streams           | S5c to S5d-3, S5e-3 |
| `worker/wsWorker.ts`, `faultChannel.ts` | shared-worker entry; dev-only fault channel, absent from production             | S5e, S5e-2          |
| `client/`                               | rAF scheduler, `createWsClient`, `workerPort`, `useWsState`; shell wiring       | S5f to S5g          |

`WsErrorHost.tsx` (E17-T05) is the host of the `err` treatment: it shows what `errorHandler.ts` decides.
