# src/lib/ws

The web WebSocket client (E17-T04, #413; wire contract `docs/plan/23-ws-protocol.md`). It lands as
five stacked slices and nothing here is reachable from `main.tsx` until the last one wires it
(C-4.13). State is a plain store read through `useSyncExternalStore`; RxJS, Zustand and Jotai are
not dependencies. Layers depend downwards: `protocol` -> `state` -> `core` -> `policy` -> `client`/`port`/`worker`.

| Path                                    | Role                                                                     | Slice  |
| --------------------------------------- | ------------------------------------------------------------------------ | ------ |
| `errorHandler.ts`, `errorMapping.ts`    | one `err` frame -> UI treatment table (E17-T05)                          | landed |
| `protocol/`, `api.ts`, `state/types.ts` | frames, codec, heatmap bucket; public surface; state types               | S1     |
| `state/reducer.ts`, `core/`             | pure state reducer; sequencer, snapshot assembler, subscriptions, engine | S2, S4 |
| `policy/`                               | pacer, close policy, throttle, ctl debounce, frame scheduler             | S3     |
| `port/`, `worker/`, `client/`           | shared worker, fault channel, `useWsState`, shell wiring                 | S5     |
