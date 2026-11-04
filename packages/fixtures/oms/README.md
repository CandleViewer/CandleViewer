# OMS scenario pack (E29-Q01)

Exchange-side states for the E29 black-box test plan (`docs/qa/e29-oms-test-plan.md`, #844) that the
demo exchange cannot be made to produce on demand: a fill pushed twice, pushes out of order or after
their order ended, a cancel that loses a race, an answer that never returns, a 5xx on a create,
credential-shaped or hostile input. Each scenario is a directory with a `manifest.json` that names the
REST replies and private-WS frames it delivers, the transition rules (`24-internal-schemas.md` §8.2,
S1 to S11) it exercises, the plan's cases it serves, its evidence class and the expected outcome in the
plan's words. The pack models `../accounts/` (E27). It holds no recording: recordings live in the
shared corpus `../bybit/<date>/` (C-13.5), and a scenario points at them. Every value is fabricated or
copied from the corpus, and nothing here comes from a live call.

**State.** One folder for each row of the plan's traceability table (section 9) that is not
`recorded`: 25 scenarios, none a recording. The one `recorded` row, `error_10001_duplicate_id`, is a
reply no documentation shows and waits for E29-K01's findings PR; the S11 row has no folder (a
unit-level contract, BQ-6). `credential_shaped_inputs` holds the AC-15 templates (below).

## What a scenario holds

```text
oms/
  README.md  manifest.schema.json
  <scenario>/manifest.json        the scenario; the directory name is its name
  <scenario>/<file>.json|.jsonl   a derived file the scenario delivers, declared under `files`
```

- A scenario delivers **corpus files**, named from the pack's root as the accounts pack writes them
  (`../bybit/2026-10-05/rest/trading-error-110017.json`), or **derived files** of its own directory
  (a bare file name). It never copies a corpus file.
- Every file of a scenario directory is declared under `files`, delivered by `rest` or `ws`, and derived
  from corpus files that exist; one that is not fails the checks. There is no `_base/`: what scenarios
  share is the corpus.
- REST bodies are `.json`; WS frames are `.jsonl`, one JSON frame per line, LF, no blank line, a final
  newline, read as UTF-8 and kept as written (R-5).

## Evidence classes

| Class              | Meaning                                                                  | Lives in                                          | Today                       |
| ------------------ | ------------------------------------------------------------------------ | ------------------------------------------------- | --------------------------- |
| `recorded`         | Captured, redacted: private data on demo, market data on the public host | the corpus                                        | none (E29-K01 records them) |
| `docs-transcribed` | A documentation example, keys and values unchanged                       | the corpus: `rest/trading-*.json`, `ws/private-*` | the order path's files      |
| `derived`          | Built from the two above: a composed sequence, a repeat, a changed value | a scenario directory, each file with its sources  | the scenarios' own files    |

A `derived` file is a derivation, never evidence of what the venue does: it is outside the corpus
drift check, so a changed field there fails nothing but this pack's checks. A scenario's `evidence`
is the weakest class of what it delivers (`derived` < `docs-transcribed` < `recorded`), and the
loader compares it with the corpus manifest's `source` of every corpus file it delivers: a
`documented-shape` or `derived` corpus file counts as `derived`, and a source in no class fails.

## The K01 deviation

E29-K01 (#843) has not recorded a demo session, and its harness is the only recorder that can capture
private data (`tools/fixtures/capture_fixture.py` is public-only, see `../bybit/README.md`). So no
authenticated capture exists: every file under `oms/` is derived, or points at a transcription. #844's
rulings let the slices that need no recording land first, each stating this deviation. When K01's
findings PR lands recordings in `../bybit/<date>/`, each derived file is re-derived from the recorded
frames (its `derived_from` re-pointed and its `derivation` re-stated), `evidence` is raised where
nothing derived remains, and `scrub_fixture()` has re-mapped K01's per-run tokens first (R-3). Until
then a derived file says what it was built from and what was done to it, and nothing more.

## Manifest format

`manifest.schema.json` (JSON Schema 2020-12, within the keyword subset of the accounts pack's
validator) is the contract; `services/api/tests/_oms_fixtures.py` checks the rules a schema without
conditionals cannot. In short:

- `scenario` is the directory name. `origin` is `ticket` (the ticket's fixture list), `plan` (the
  black-box plan) or `threat model AC-nn`. `environment` is `demo`: the hosts the scenario stands in
  for (C-2.11), not a claim that anything was captured. `description` and `expected` are prose; the
  outcome is in the plan's words, never an internal function or field.
- `rules` lists S1 to S11 (empty for an abuse case that no rule covers). `cases` lists the plan's
  `E29-TC-nnn` ids. `consumers` lists the tickets whose suites are to replay it. With `evidence`,
  these four are the scenario's row of the plan's section 9 table, and the checker compares them.
- `rest` maps `"<METHOD> <path>"` to a stub: `payload` (a corpus file or a derived file) and an
  optional `http_status` (200 when absent; a documentation example states none, so this is the
  scenario's choice, not evidence). A stub answers every call of its route the same way.
- `ws.private` lists the files whose frames the private stream delivers, in this order. A fixture's
  frames are its delivery order: a gap, a reversal or a repeat is its own scenario, never random.
- `files` declares each derived file: `derived_from` (corpus files that exist) and `derivation`
  (what was done to them, and nothing was invented beyond it). A derived frame keeps the field paths
  and types of its source's frame: only values change (the smoke test compares the shapes).
- `slots` (a template only) names each `{{name}}` placeholder of the scenario's own files with the
  `shape` and `length` of the value a seed generates for it at test time.
- A scenario delivers something: at least one stub or one frame.

**Injection.** `inject` lays faults over the shapes, applied in the order listed:

| Kind        | Fields        | What it does                                                                                   |
| ----------- | ------------- | ---------------------------------------------------------------------------------------------- |
| `timeout`   | `call`        | The request reaches the venue and its answer never returns (S1, a post-send timeout)           |
| `http_5xx`  | `call`        | The call answers HTTP 503 and the corpus's gateway body (`error_503.json`) instead of its stub |
| `drop`      | `frame`       | The frame is never delivered: a lost push                                                      |
| `duplicate` | `frame`       | The frame is delivered twice in a row                                                          |
| `reorder`   | `frame`, `to` | The frame moves to index `to`                                                                  |

`call` names a stubbed call; `frame` and `to` are indexes from 0 into the delivered sequence as the
faults before left it. The loader applies the three WS kinds (`delivered_frames()`); the two REST
kinds are data for the harness that replays the scenario (`injections`). A fault that needs a state
the scenario does not hold, such as a socket killed for 60 s, is the harness's (E29-Q04), not an
injection.

## Using a scenario

`services/api/tests/_oms_fixtures.py` loads one and checks it; the corpus files are read through
`tests/_corpus.py`:

```python
from tests._oms_fixtures import load, scenario_names

scenario = load("ws_duplicate_exec")  # PackError names the rule a scenario breaks
scenario.delivered_frames()  # the private frames to deliver: raw text, in order, faults applied
scenario.reply("POST", "/v5/order/create")  # .status, .body, .payload; UnstubbedCall if none
scenario.injections  # every fault, as data; the harness applies the REST kinds
scenario.canonical()  # the bytes two loads agree on
scenario.render("seed")  # a template with its slots filled: .frames, .replies, .values, .leaks(*texts)
```

Offline and deterministic: the loader opens files and nothing else, so no test of it can reach a
network, and a replay is the same bytes every time. Tests serve replies and frames to the adapter's
own parsers, through `httpx.MockTransport` and `FakeTradingPort` (the mock exchange is those two,
not a server). A call no stub answers is a test failure, never a silent success.

## Redaction (R-1 to R-6)

Nothing is committed before it passes these; each rule names its owner.

1. **R-1 Private data from demo only.** Nothing private comes from live (C-13.5, the ticket's security
   notes). Public market data, with no key and no account, may come from the public host: demo has no
   public feed of its own (C-2.11).
2. **R-2 The recorder scrubs first.** E29-K01's harness replaces identifier values with per-run tokens,
   drops headers, signatures, `args` and `auth` frames, and refuses a final text that still holds a
   registered secret.
3. **R-3 `scrub_fixture()` runs second** (`tools/fixtures/`, offline and deterministic; it lands with
   the recordings). It re-maps K01's tokens to well-formed synthetic values: UIDs `9000xxxx`
   (`../accounts/README.md`, "Fabricated values"), `orderId` and `execId` UUID-shaped
   (`00000000-0000-4000-8000-…`), our orders' links in the `OUR_ID` form (`24-internal-schemas.md`
   §8.3), and the UID segment of each push `id`, `conn_id` and `req_id`. Relative times stay: S5
   depends on them.
4. **R-4 Gates before any commit.** `node packages/fixtures/scripts/verify.mjs` (it scans `oms/`),
   `python scripts/check_secrets_hygiene.py fixtures`, `gitleaks protect --staged --redact`, and a
   field-by-field review: the public redactor (`tools/fixtures/redact.py`) is not enough for private
   data, as its docstring says.
5. **R-5 File form.** Plain `.jsonl` and `.json`, as above; LFS only above 1.5 MB, inside the corpus's
   2.5 MB cap (`../bybit/README.md`).
6. **R-6 AC-15 seeds are never committed as secret-shaped text** (next section).

## Templates for AC-15 (OM-I05)

The threat model's AC-15 (`docs/security/threat-models/E29-oms.md`) feeds the OMS what a venue or a
user could make it echo: auth headers, an `auth` frame, a signed URL, an error text that repeats a key,
keys under field names no redactor knows. Text of that shape is never committed, and the gates above
refuse only part of it. `verify.mjs` refuses a field named `sign`, `signature`, `api_key`, `apiKey` or
`api_secret` with a value of 8 characters or more, a field named `secret`, `token` or `password` with
a value of 16 or more letters, digits or `+/=_-`, a `Bearer` token of 20 or more letters, digits or
`._-`, a PEM private-key header and an `X-BAPI-API-KEY` or `X-BAPI-SIGN` header with 16 or more
letters and digits. The hygiene check refuses the `api_key`, `apiKey` and `api_secret` fields from 16
characters, a signature from 32 hex digits, a PEM header and those two headers. Neither refuses a
signature of another shape or a key it cannot see as a token. The bare-key rule that `accounts/` has
covers `oms/` as well, in both gates (`KEY_SHAPE_DIRS` in `verify.mjs`, `_KEY_SHAPE_DIRS` in the
hygiene check): a bare token of 18 to 20 or of 36 letters and digits is refused wherever it sits, in
prose, in an `auth` frame's `args`, in a signed URL, in an error text or under a field of any name. It
is a tripwire for a paste, not a complete control: a key split by a JSON escape or joined to a hyphen
is not a bare token, so the field-by-field review under R-4 stays the control for those shapes
(gitleaks runs its own rules over them as well). The form:

- A **template** is a derived file in which every secret-shaped value is a placeholder, a whole JSON
  string value or a token inside a longer text. The committed file parses without its seed and passes
  every gate as committed, so the placeholder's spelling is chosen to satisfy them: `verify.mjs` flags
  eight characters or more as the value of a field named `sign`, `signature`, `api_key`, `apiKey` or
  `api_secret`, so those fields take a shorter one. `secret`, `token` and `password` are flagged from
  16 letters, digits or `+/=_-`, so they take a placeholder shorter than that or holding a character
  outside the set (`{{SLOT_1}}`, `<slot-1>` and `***` pass there; `PLACEHOLDER_SECRET_01` is flagged),
  and a field flagged from 8 characters takes `<sig>` or `***`.
- The manifest names each slot under `slots`: a `shape` (`alnum`, `letters`, `symbol`, `hex` or
  `digits`) and a `length`. `render(seed)` fills the slots at test time: each value is generated in
  memory from the seed and the slot's name alone, in the exact shape the case needs (a key, a
  signature, a timestamp), and is never written to disk or logged. A `Rendered` keeps its text and
  values out of `repr`, and `leaks(*texts)` names the slots whose value is in any text, never the
  value, so a failure message holds none. The loader refuses a placeholder with no slot and a slot no
  file uses.
- The case asserts that the OMS's stored events, diagnostics, audit rows and logs hold none of the
  generated values.

## Checks

| Where                                                                | Runs                                                                                                                         |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `pnpm --filter @candleviewer/fixtures lint` (`scripts/verify.mjs`)   | The redaction gate over `raw/`, `golden/`, `bybit/`, `accounts/`, `oms/`; the bare-key rule over the last two (js lane)      |
| `pnpm --filter @candleviewer/fixtures lint` (`oms-pack.mjs`)         | Each scenario folder against its row of the plan's section 9 table: Rules, Cases, Evidence, Consumers (js lane)              |
| `python scripts/check_secrets_hygiene.py fixtures` (repo root)       | The field-name rules over every fixture directory; the bare-key rule over `accounts/` and `oms/` (security lane)             |
| `tests/unit/fixtures_corpus/test_oms_pack_smoke.py` (`services/api`) | Per scenario: the schema, every file parses, `derived_from` exists, the evidence class, two byte-identical loads, no network |
| `tests/unit/fixtures_corpus/test_oms_pack_adapter.py`                | `services/api`: each scenario read twice through the adapter's own parsers, the same reads both times (BQ-6)                 |

The two Python tests read the scenario directories by name: adding one adds its checks. The checker
reads the plan's section 9 table (`docs/qa/e29-oms-test-plan.md`): a folder with no row fails, a row
that disagrees with its folder fails, a row with no folder yet is pending (the `recorded` row waits
for E29-K01's findings PR), and the S11 row has no folder (BQ-6): its folder test is skipped and its
Rules and Cases cells are still read.

## Adding a scenario

1. Pick the name the plan or the ticket gives it (a path with `key`, `secret`, `token` or `crypt` in it
   makes the PR a `security-review` one, C-10.2).
2. Deliver corpus files where one holds the shape; derive a file only for what no corpus file shows,
   and state in `derivation` exactly what was done. Never invent a payload shape.
3. Add the scenario's row to the plan's section 9 table, then set `rules`, `cases`, `evidence` and
   `consumers` from it (`evidence` is the weakest class delivered) and `expected` in the plan's words.
4. Run the gates under R-4 and the two Python tests, `test_oms_pack_smoke.py` and
   `test_oms_pack_adapter.py`, in `tests/unit/fixtures_corpus/`.
