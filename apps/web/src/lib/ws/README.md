# src/lib/ws

The web WebSocket client (E17-T04, #413; wire contract `docs/plan/23-ws-protocol.md`). It lands as
ten stacked slices (S1, S1b, S2a, S2b, S2c, S2d, S3, S3b, S4, S5) and nothing here is reachable from
`main.tsx` until the last one wires it (C-4.13). State is a plain store read through
`useSyncExternalStore`; RxJS, Zustand and Jotai are not dependencies. Layers depend downwards:
`protocol` -> `state` -> `core` -> `policy` -> `client`/`port`/`worker`.

| Path                                    | Role                                                                     | Slice  |
| --------------------------------------- | ------------------------------------------------------------------------ | ------ |
| `errorHandler.ts`, `errorMapping.ts`    | one `err` frame -> UI treatment table (E17-T05)                          | landed |
| `protocol/`, `api.ts`, `state/types.ts` | frames, codec, heatmap bucket; public surface; state types               | S1     |
| `state/reducer.ts`                      | pure connection-state reducer and initial state; EngineEvent in types.ts | S1b    |
| `core/`                                 | sequencer, snapshot assembler, subscriptions, resync guard, engine       | S2, S4 |
| `policy/`                               | pacer, close policy, timers; S3b adds throttle policy, ctl debounce      | S3     |
| `port/`, `worker/`, `client/`           | shared worker, fault channel, rAF scheduler, `useWsState`, shell wiring  | S5     |

`WsErrorHost.tsx` (E17-T05) is the host of the `err` treatment: it shows what `errorHandler.ts` decides.
