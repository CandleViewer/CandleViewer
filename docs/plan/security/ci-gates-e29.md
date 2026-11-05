# CI security gates for the OMS (E29-X02)

> Owner: `@CandleViewer/security`. Ticket: E29-X02 (#982), in slices: the Semgrep rules (this page),
> then the route-by-role matrix and the abuse-case suite under `services/api/tests/security/oms/`.
> Threat model: `docs/security/threat-models/E29-oms.md` (section 5.3, section 6; OM-E01, OM-E03,
> OM-I01, OM-I05, OM-S05, OM-T08, OM-T10; SR-051, SR-E29-03, SR-E29-08, SR-E29-13). Contract rules:
> `24-internal-schemas.md` section 8.3 rule 5, section 14.2 rule 3 and section 17.4 L2. Programme
> rules: `docs/plan/04-security-program.md` section 12.2 (Semgrep composition, CI-SEC-006
> suppressions) and section 16.2 (exceptions). This page explains each gate; the rule YAML is the
> source of truth for what is matched.

## Running locally

- Validate: `semgrep --metrics=off --validate --config .semgrep`.
- Prove the fixtures: `python tools/ci/check_semgrep_rule_tests.py`. Each rule's fixture is a tree,
  `.semgrep/tests/<rule-id>/<repo path>/...`, staged at those paths, so a path-scoped rule meets its
  fixtures where its `paths` look. Every tree holds a file with PEP 695 syntax beside one without:
  `oms/` holds both kinds, and Semgrep parses the first another way (#3549).
- Scan as CI does. At merge it reports nothing; with `--disable-nosem` it lists the seven reviewed
  exceptions below, one per statement:

  ```sh
  semgrep scan --metrics=off $(printf -- '--config %s ' .semgrep/cv-oms-*.yml) services/api/candleviewer
  ```

## How these gates run

`_job-security.yml` passes every `.semgrep/cv-*.yml` to `semgrep scan` and runs the fixture checker in
the same `semgrep-bandit` job, so the six rules need no workflow change and add no required-check name
(C-9.1). `ERROR` blocks through `security_gate.py`, so the whole-tree scan keeps `services/api` at zero
unsuppressed findings.

"OMS modules" are M14's package, `services/api/candleviewer/oms/**`, and the order lane's composition
modules beside it, `services/api/candleviewer/oms_*.py` (`oms_wiring.py`, `oms_lane.py`,
`oms_streams.py`, `oms_stream_wiring.py`, `oms_reads_wiring.py`, `oms_reconcile_wiring.py`). The scope
rule reads the OMS stores in `storage/repositories/`; the redaction and allocator rules read every
product module. A pattern exemption a rule makes (a raise-only branch, a type-only import, a duration,
the allocator's own file) has its own `ok` fixture and a `ruleid` fixture beside it that proves the
rule still fires around it.

## Reviewed exceptions

Seven statements are by design. Each carries a comment-only
`nosemgrep: <rule-id> reason=<token> owner=@CandleViewer/security review=2027-02-04` on the line above
it (CI-SEC-006; the date is the R3 security gate of threat model section 5.4):

| Rule                     | Site                                                                         | `reason=`              | Why it is by design                                                                                                                                                                                        |
| ------------------------ | ---------------------------------------------------------------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cv-oms-unscoped-select` | `storage/repositories/oms_reads_sqlalchemy.py`, `position_holder_statement`  | `refusal-audit-holder` | The account holding a position id the scope does not view, read for the refusal's audit record alone and never served (SR-E29-13, ruling Q12); in the module's `UNSCOPED`, which its unit test pins        |
| `cv-oms-unscoped-select` | `storage/repositories/orders_sqlalchemy.py`, `in_scope_statement` (`holder`) | `refusal-audit-holder` | Beside the scoped row, the account of the order holding the id, so only the holding account leaves the database for an out-of-scope id (ruling Q12)                                                        |
| `cv-oms-unscoped-select` | `storage/repositories/orders_sqlalchemy.py`, `link_taken_statement`          | `global-link-check`    | 24 section 8.3 rule 5's yes or no over the global `ux_orders_link`: a bool across every account by design, asked by the allocator and reconciler (below), never on an API route or WS topic; in `UNSCOPED` |
| `cv-oms-env-branch`      | `oms/ports.py`, `InterimRiskGate.check`                                      | `interim-risk-gate-r4` | Ruling R4's interim risk gate: a demo order is admitted unevaluated and every other environment's is refused, announced by `oms_interim_ports{port="risk_gate"}` until E39-S01 replaces it                 |
| `cv-oms-env-branch`      | `oms/ports.py`, `NoArmRecords.check`                                         | `interim-arm-records`  | SR-043's interim stand-in: every live order is `session_not_armed` until E30-S04 brings arm records                                                                                                        |
| `cv-oms-env-branch`      | `oms_wiring.py`, `TradingSwitchesBinding.refusal`                            | `live-enable-gate`     | The live trading switch (C-2.21's synchronous check, rulings Q4 and Q6): a live account's order needs the setting and the flag; demo and testnet never meet it, and any other value is live's              |
| `cv-oms-env-branch`      | `oms_wiring.py`, `OmsRuntime._compose` (the size step's figures)             | `live-no-day-figures`  | 24 section 9.3.6: live has no day figures, so every live entry is refused; `DayRiskFigures` serves demo and testnet only                                                                                   |

`link_taken_statement` answers `link_id_taken`, which has two callers: the allocator, through its
`OrderLinkLookup` (`OrderRepository.exists`), and step 3c of the reconciliation pass
(`oms/reconciler.py`), which asks it about an exchange order whose id no row of its own account
holds, so that an id another account's row holds is recorded as an anomaly and never adopted (24
section 8.5). Neither reads more than the yes or no.

The four environment branches are policy on the environment's risk class, not a venue difference, so
`ExchangeCapabilities` has no field for them; moving each onto a record the composition root builds
would retire its exception.

## cv-oms-no-float-money

- **Protects:** R7 data accuracy, OM-T08 (a projection that drifts from the exchange shows a wrong
  book); AGENTS.md section 5.2 (`Decimal` for money); 24 section 14.4 (`Px`, `Qty`, `Notional`).
- **Matches,** in OMS modules: `float(x)` where `x` names money as a whole word of a name, attribute
  or key, in snake or camel case (`price`, `px`, `qty`, `quantity`, `size`, `notional`, `amount`,
  `amt`, `cost`, `fee`, `commission`, `pnl`, `profit`, `loss`, `balance`, `equity`, `margin`,
  `exposure`, `collateral`, `cash`, `usdt`, `usd`, `leverage`, `mark`, `risk`, `sl`, `tp`,
  `distance`, `trailing`, plurals too), or with `value` closing a longer name, as the exchange names
  its money fields (`cum_exec_value`, `cumExecValue`, `position_value`); a float stored under such a
  name (an assignment, annotated or not, a keyword or a dict key), reported on the float's line;
  `float(Decimal(...))` and `float(x.quantize(...))`; and `float(p)` of a parameter or a local
  annotated `Decimal`, `Px`, `Qty`, `Notional`, `Bps`, `Amount`, `Money`, `Price`, `Quantity` or
  `Figure` (or `| None`). An argument or a name that spans lines is read for a money word on every line, and for its
  duration ending on its first line only, so a money argument that spans lines fires even when it
  ends in a duration name (`float(` `order.price` `- row.delay` `)` on three lines). Fix: keep
  the `Decimal`; quantize to the tick or step.
- **Does not match:** a name that ends as a duration does (`_s`, `_ms`, `_us`, `_ns`, `_sec`,
  `_secs`, `_seconds`, `timeout`, `interval`, `delay`, `wait`, `deadline`, `ttl`), a money word in it
  or not (`price_age_s`); counts and clocks; `float("inf")`; a money word inside another (`slot`,
  `tpsl`); a bare `value` (the `_seconds` helpers' argument: only `value` closing a longer name is
  money). Every `float()` in OMS modules on `main` is one of these: eight durations, a gauge's
  count and a clock. A count named after money (`float(len(prices))`) fires: name the count.
- **Not seen:** a float of a value that neither its name nor its annotation marks as money
  (`level = order.price`, then `float(level)`), `parse_float=float`, an unannotated money value
  under a name the list lacks; other ways to a float (`np.float64(price)`, `price.__float__()`,
  `builtins.float`, `math.fsum` or `math.isclose` over prices); a one-line argument that mixes money
  with a trailing duration (`float(price or timeout_s)`), which the duration ending exempts.
  `cv-no-float-prices` covers `storage/**`, `bars/**` and `ingestion/**`, and `cv-decimal-discipline`
  the `float` annotations.
- **Fixture:** `.semgrep/tests/cv-oms-no-float-money/` (an `oms/` module, one with PEP 695 syntax, an
  `oms_*.py` module).

## cv-oms-unscoped-select

- **Protects:** OM-I01, OM-E01; SR-051, SR-E29-13; C-12.4. The store holds the account in SQL, so a
  foreign id is answered as a missing one.
- **Matches:** a Core `select(...)` (bare, `sa.select` or a table's `.select()`) whose selected
  expressions name `orders`, `positions` or `executions`: the table, bare or module-qualified
  (`m.orders`), the column allow-lists `ORDER_COLUMNS`, `POSITION_COLUMNS` and `EXECUTION_COLUMNS`,
  or an alias bound in the module or the function (`_O = orders.c`, `held = orders.alias("held")`, a
  tuple of up to four), when no `.where(...)` or `.filter(...)` of its chain holds
  `<table>.exchange_account_id ==` (either side), `.exchange_account_id.in_(...)`,
  `.filter_by(exchange_account_id=...)` or `scope_clause(...)`. Scope: the stores E29-T01 and E29-T07
  built, which the order and position routes reach: `storage/repositories/orders*.py`, `oms_*.py`,
  `positions*.py`, `executions*.py` and `recorded_stops*.py`. Fix: add the account, or the
  principal's `scope_clause(scope, environment, account, trade=...)`.
- **Does not match:** an insert's `RETURNING` CTE, another table. The predicate is looked for, not
  proven: one compared with any right-hand side passes (a join's
  `_O.exchange_account_id == _L.exchange_account_id`), and so does a select inside a scoped
  `where`'s arguments. A predicate in a `where` on another statement fires: write it in the chain.
- **Not seen:** a select whose selected expressions name none of the tables, the table only in its
  `where` or `select_from` (`select(literal(1)).where(_O.id == rs.order_id)`): the rule reads what
  a select returns, not whether it is correlated, so the startup sweep's correlated `EXISTS`
  subqueries pass, and so would an uncorrelated one over every account's rows; an alias passed in
  or built by a helper, a tuple of five or more, a table or column list imported under another name
  (`orders as order_table`, `ORDER_COLUMNS as _ORDER_COLUMNS`), a column tuple built at module
  level, an alias made by `sa.alias(orders, ...)` and bound to a name (`orders.alias(...)` is seen),
  a column added by `.add_columns(...)`, an UPDATE or a DELETE (the rule reads selects only), text
  SQL (these stores build Core only; `cv-storage-sql-construction` owns text), and the stores
  outside the scope: `order_path_symbols_sqlalchemy.py` (the instrument refresh's seed, symbol names
  across every account, answered to no request), `reconcile_sqlalchemy.py` (the reconciliation pass,
  one account per call), and the trade-group, notification and admin stores of their own epics. Each
  store's `UNSCOPED` set, which its unit test pins, names its unscoped builders beside the rule.
- **Fixture:** `.semgrep/tests/cv-oms-unscoped-select/`, with the annotated statement that proves the
  marker placement the three exceptions use.

## cv-oms-order-events-unredacted

- **Protects:** OM-I05; SR-E29-08 (threat model section 6, items 2 and 4); C-12.6. `order_events` is
  append-only and kept indefinitely: a key, a signature or an `auth` frame stored once stays.
- **Matches:** in a module that imports the `order_events` table by name, a value written under
  `payload` (a dict key, `dict(payload=...)`, `row["payload"] = ...`, `.values(payload=...)`,
  `.update(payload=...)`, `.setdefault("payload", ...)`, or a key of a payload already built,
  `row["payload"][key] = ...`) that is not a direct `redact_exchange_payload(...)` call, bare or
  module-qualified, or, in a dict, `{}`, reported on the value's line; there too, a payload merged in
  place (`row["payload"].update(...)`) unless by such a call, and an `INSERT ... SELECT`
  (`.from_select(...)`), whose payload the database picks; in any module, an insert or update of
  `<module>.order_events` whose `.values(payload=...)` is not that call; and text SQL that writes the
  table (an `INSERT INTO`, a SQL comment between the two words too, `UPDATE ... SET` or `COPY` of
  `order_events`), which would skip the redaction that runs in Python before the bind. Scope:
  `services/api/candleviewer/**`, not migrations. Fix: write
  `"payload": redact_exchange_payload(event.payload)` through the Core builder, as
  `orders_sqlalchemy._event_values` does.
- **Does not match:** a `payload` in a module that writes no `order_events` row (a WS frame's, a
  handover's), a read (`SELECT payload FROM order_events`). A value redacted earlier and held in a
  variable fires: call the redactor where the value is written.
- **Not seen:** a module that names the table through its module
  (`from candleviewer.db import models as m`): there only `insert(m.order_events).values(payload=...)`
  and the `update` form are read, so a `{"payload": ...}` dict, `m.order_events.insert().values(...)`,
  executemany parameters and the in-place forms pass (no store does so today); values built in
  another module that does not import the table (`.values(**helper(event))`: a helper's own dict is
  read where the helper is, as `_event_values`' is); a dict held in a variable then passed to
  `.values(rows)`; a payload changed through a name (`p = values["payload"]; p["sign"] = ...`) or by
  `|=`; text SQL with an alias between the table and its columns
  (`INSERT INTO order_events AS oe (...)`), or with a SQL comment other than between `INSERT` and
  `INTO` (`INSERT INTO /* tag */ order_events`) or a nested block comment between them
  (`INSERT /* a /* b */ c */ INTO`); a statement split across string literals. The in-memory fake
  (`oms/fakes.py`) redacts the same way, proven by its own tests. The threat model's record-type
  form (section 6 item 4) waits for closed payload schemas (SR-E29-08 item 3, G-1):
  `NewOrderEvent.payload` is a plain `Mapping` today.
- **Fixture:** `.semgrep/tests/cv-oms-order-events-unredacted/`.

## cv-oms-no-network-client

- **Protects:** C-2.2, C-2.11 and C-12.7; OM-E03, OM-D03, OM-I05. The adapter's port signs with M2,
  spends the per-UID budget and its reserve, keeps demo and live apart and builds the allow-listed
  record `order_events` stores; a client made in the OMS bypasses all four.
- **Matches,** in OMS modules: an import of an HTTP, WebSocket or socket client (`httpx`, `httpcore`,
  `aiohttp`, `requests`, `urllib3`, `urllib.request`, `http.client`, `websockets`, `websocket`,
  `socket`, `ssl`, `grpc`, `pycurl`, `treq`), by `importlib.import_module` or `__import__` too; a call
  on one of those modules (`httpx.AsyncClient(...)`); asyncio's own streams (`asyncio.open_connection`,
  `open_unix_connection`) and a `create_connection` or `sock_connect` call on any receiver, an event
  loop however it is named; an `if TYPE_CHECKING:` (or `typing.TYPE_CHECKING`) whose `else` or `elif`
  branch imports one of those clients, reported on the `if` line, as that branch runs. Fix: call the
  `TradingPort` the runtime hands the OMS; an adapter change belongs in `exchange/`.
- **Does not match:** an import in the first branch of `if TYPE_CHECKING:` (the order lane's
  `httpx.AsyncBaseTransport` type in `oms_wiring.py`), an annotation, the adapter's port
  (`exchange/base`) and the adapter import CONSTITUTION.md section 3 allows M14: the ticket's "any
  exchange call outside the adapter package" is narrowed to network clients, as
  `cv-adapter-isolation` already bans the vendor's identifiers outside the adapter.
- **Not seen:** a client handed in by another module (the composition root hands the OMS its port),
  a call on a module name the list lacks, a module name built at runtime
  (`importlib.import_module(name)`), which `cv-adapter-isolation` misses too, and an exchange SDK
  (`import pybit`, `import ccxt`), which that rule sees only where the vendor's name is written as a
  word.
- **Fixture:** `.semgrep/tests/cv-oms-no-network-client/`.

## cv-oms-env-branch

- **Protects:** 24 section 14.2 rule 3 and section 17.4 L2 ("capabilities drive behaviour, not
  conditionals"); C-2.11; OM-E03.
- **Matches,** in OMS modules: an environment compared with one of its values (`==`, `!=`, `is`,
  `is not`, or `operator.eq`, `ne`, `is_` or `is_not` under any import name, against `"live"`,
  `"demo"` or `"testnet"` in any letter case (`env.name == "LIVE"`), or a member `LIVE`, `DEMO` or
  `TESTNET` of an enum whose name holds `Env`, also inside a call such as `Environment("live")`),
  membership of an environment-named value (`env`, `environment`, `self._env`, `order.environment`,
  and an environment's `.value` or `.name`: `settings.environment.value`) in a constant
  (`env not in _NOT_LIVE`) or in a literal collection, and membership of any value in a literal
  collection of environment values; in an `if`, a `while`, a conditional expression, a comprehension
  or an assignment alike. Fix: read a field of `ExchangeCapabilities` or of another record the
  composition root builds.
- **Exemption:** a test whose `if` body is a single `raise` of a class, bare or called with a message
  (a string, an f-string or a name), and that has no `else` or `elif`, a fail-closed self-check; a
  `from` clause, or a method called on the new exception (`.with_traceback(...)`), is reported.
  Seven pass on `main` without an annotation:
  `ports.refuse_live_without_reconciliation`, `stream_consumer.refuse_live_without_position_rows`,
  `oms_stream_wiring.refuse_live_without_freeze`, the reconcile wiring's and the reconcile job's
  always-remediate checks, `DayRiskFigures`' constructor and the runtime's machine-event sink check.
  An `if` that raises and has an `else` or an `elif`, or whose body does more than raise, is reported
  on its `if` line, and so is a raise-only `if` that does work for one environment: a call in the
  raise's arguments (`raise Refused(_open_live_route(port))`); an `await`, or a call to anything but
  a class named in CapWords, anywhere in the raise (`raise _open_live_route(port)`,
  `raise await ready`, `raise Refused if _open_live_route(port) else Unready`); or a walrus in its
  condition, which keeps the test for a later branch (`(live := env == "live")`); the fixture holds
  each.
- **Does not match:** a comparison of two environment values (C-2.11's isolation checks:
  `account.environment != self._environment`, `Validator.check_route`), an execution mode
  (`mode == "paper"`), another enum's `LIVE` (`ViewAsPhase.LIVE`; its name as a string,
  `phase.name == "LIVE"`, fires).
- **Not seen:** `match`/`case`, a table keyed by the environment (`ENV_LETTER[environment]`, data as
  `ExchangeCapabilities` is), a boolean computed elsewhere (`is_live`), an environment under a name
  the pattern lacks, an environment enum imported under a name without `Env` (`PE.LIVE`), a value
  tested for membership in the environment (`"live" in env`), `operator.contains`, or an operator
  passed as a value (`partial(operator.eq, "live")`). In a raise-only `if`: a call or an `await` in
  its condition after the environment test (`env == "live" and await open_live(port)`), where four
  of the seven checks call a predicate; an exception used as control flow (`raise _UseTradeSocket`,
  which an `except` one frame up answers with the live work); and a class, or a function named like
  one, whose call does the work (`raise Refused(port)`), which reads as an exception's construction.
- **Fixture:** `.semgrep/tests/cv-oms-env-branch/`, with the annotated statement that proves the marker
  placement the four exceptions use.

## cv-oms-link-id-constructor

- **Protects:** SR-E29-03 and threat model section 5.3; OM-S05, OM-T10; C-2.10. Every id the OMS
  persists and sends is one `OrderLinkIdAllocator.allocate` returned, checked against every `orders`
  row (24 section 8.3 rule 5), so a reused id never inherits another order's exchange history.
- **Matches,** in every product module but `oms/order_link_allocator.py`: `AllocatedOrderLinkId(...)`,
  bare or module-qualified, its `__new__`, `object.__new__(AllocatedOrderLinkId)`, a subclass, and
  `replace`, `dataclasses.replace`, `copy.replace` or `copy.copy` of a value an `allocate(...)` call
  returned. Fix: `await allocator.allocate(OrderLinkIdParts.generate(...))`.
- **Does not match:** the allocator's own file, whose `allocate` is the one constructor on `main`;
  reading `allocated.order_link_id`; `OrderLinkIdParts.generate` and `parse`, as a candidate is no
  allocation; `replace` of anything else.
- **Not seen:** an id string sent without the allocator (`order_link_id=candidate.value`):
  `OrderLinkId` is a pattern-checked `str` today. SR-E29-03's nominal type, which `place_order` alone
  will accept, is a change still to land; the rule follows that type when it does. Copies the rule
  does not follow: `replace` of a parameter or of an `allocate_replacement(...)` result (the
  allocator's second entry point; only `allocate(...)` is followed), `copy.deepcopy`, `type(x)(...)`,
  `object.__new__(ola.AllocatedOrderLinkId)` and the class held in a variable (`cls(...)`). An
  aliased import (`... as Allocated`) is seen.
- **Fixture:** `.semgrep/tests/cv-oms-link-id-constructor/`, with a fixture at the allocator's own path.

## Requesting an exception

Fix the code if you can. Otherwise add
`# nosemgrep: <rule-id> reason=<token> owner=@CandleViewer/security review=YYYY-MM-DD` (at most 180
days) on the line above the finding's first line, add the site to the table above in the same PR, and
tag `security-review`; a High finding or an exception that outlives a release also follows
`04-security-program.md` section 16.2.
