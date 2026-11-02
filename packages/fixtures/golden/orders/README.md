# Orders goldens (E29-S02, #912; BQ-1, BQ-3, BQ-4, BQ-6, BQ-7, BQ-17)

The web working-orders feature's fixtures: what the shipped code serves for the positions goldens' three
fixture accounts, and two more for the five-account cancel-all. `apps/web/test/features/positions/orders/` and
`apps/web/test/contract/orders.contract.test.ts` read them; nothing else may.

| File                             | What                                                                                                  | Written by                                                    |
| -------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `ws_orders_snapshot.json`        | the `orders` snapshot body (`23` §15.1): E29-D02 §6.2's five open orders, each view stamped with its read | `oms.ws_topics.order_item`                                    |
| `ws_orders_deltas.json`          | one frame per step: an order's first steps, the three amend steps and a fault, a cancel a fill beats, a 110001 park and its reconciliation, an untracked adoption, a hold, a late frame | `change_of`, `order_item`, and `removed` beside a closing step |
| `ws_orders_contract_fields.json` | the snapshot plus `trade_group_id` and `algo_kind`, which `23` §15.1 allows and no producer sends      | the snapshot, extended (below)                                |
| `rest_list_orders_open.json`     | `listOrders?open_only=true` 200: the five, plus the held and the untracked order                       | `api.oms_reads.order_document` (`order_body`)                 |
| `rest_cancel_all_partial.json`   | `cancelAllOrders` 200: five accounts, three succeed                                                    | `api.order_cancel_all._result`                                |
| `rest_amend_order_request.json`  | the specimen amend's body, `{"price": "2495.00"}`                                                      | the client's; read by `api.order_exits._terms`                |
| `rest_cancel_all_request.json`   | a cancel-all body over the five accounts, reduce-only exits kept                                       | the client's; read by `api.order_cancel_all._request`         |
| `manifest.json`                  | the sources, each mapper with the commit of its file, and each file's sha256                          | the generator                                                 |

## Provenance (C-13.5)

An order row is the OMS's own (`24` §8.1), never an exchange payload, so no capture starts these rows: they are
OMS rows holding `docs/design/E29/E29-D02.md` §6.2's fixture values (Main, Sub-1 and Sub-2 as in the positions
goldens) and go through the shipped chain above. Each delta is a committed step (`CommittedOrderStep`), framed as
the topic frames it: the shipped `change_of` names its `change`, and a step out of `OPEN_STATES` carries the order's
id in `removed` beside its item (`OmsTopics._fan_out`), which is also true of a step into `held` or `untracked`. No
payload shape is written by hand. The two request bodies are the client's own and pass the routes' strict readers.

What the deltas show:

- **BQ-1:** the amend's request, its acceptance and its rejection all carry `change: "amend"`; only the state and
  the price tell them apart, and a transport fault lands in `unknown` with no `change`.
- **BQ-3:** a fill that beats a cancel ends the order `filled`, and a cancel the venue answers 110001 parks it in
  `unknown` until reconciliation's `reconcile` step resolves it.
- **BQ-6:** the held and the untracked order are on REST only; an adoption and a hold arrive with `removed`.
- **BQ-17:** the recorded stop (Sub-2's BTCUSDT) has `trigger_direction: null`; the client derives "falls" from its
  closing side.

`ws_orders_contract_fields.json` is the one extension: `23` §6.2.3 says the order row holds neither member, so no
producer sends them, while `23` §15.1 allows them. They carry the Sub-1 entry's bracket and its leg's trade group, so
the client's Parent words are tested against contract-valid frames.

The cancel-all's failures are the OMS's own codes and words (`exchange_unavailable`, `timeout`), never the
exchange's text (SR-E29-09).

## Regeneration

A change of a mapper's output fails the generator's check until the goldens follow it:

    cd services/api && CV_REGEN_GOLDEN=1 uv run pytest tests/unit/oms/test_orders_web_golden.py

Review the JSON diff before committing it. The files are `json.dumps(indent=2)` with LF, so `.prettierignore` keeps
prettier off them.
