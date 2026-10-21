---
description: Python backend conventions for services/api (FastAPI, asyncio, pydantic v2, ruff/black/mypy strict, pytest-asyncio, hypothesis, module boundaries).
---
# Python backend (`services/api/`)

Source: `AGENTS.md` §5.2, `CONSTITUTION.md` §2–§3, `docs/plan/20-architecture.md`, ADR-0004 (modular monolith).

## Stack
- Python 3.12, FastAPI, asyncio, pydantic v2 (`BaseModel`, `model_validate`, `ConfigDict(frozen=True, extra="forbid")`
  for inbound DTOs), SQLAlchemy 2.x async + Alembic, uv for deps.
- Tooling: Ruff, Black, mypy strict mode, pytest, import-linter. Commands: `AGENTS.md` §4 only — do not restate them here.

## Module boundaries (C-3.x)
- The module list and dependency table are owned by CONSTITUTION §3 — do not restate them; read them.
- Dependencies flow one way; cycles forbidden (C-3.1). New module or new edge ⇒ ADR (C-3.4).
- `secrets` importable only by the modules C-3.2 allows. `audit` is write-only except its read paths (C-3.3).
- Bybit-specific code lives only in `exchange/bybit/`; everything else uses `exchange/base/` interfaces.
- Statechart runtime is imported only in `candleviewer/statechart/` (see `21-statecharts.md`).
- HTTP/WS routers are contract-first: change `docs/plan/22-api-openapi.yaml` / `23-ws-protocol.md` first,
  regenerate `packages/protocol`, then implement (CONSTITUTION §6).

## Async rules
- **Never block the event loop**: no `time.sleep`, `requests`, sync DB drivers, sync file I/O on hot paths,
  CPU-heavy loops > ~1 ms. Use `asyncio.sleep`, `httpx.AsyncClient`, asyncpg, `asyncio.to_thread` or a
  process pool for CPU work (footprint aggregation batches, Parquet writes).
- Every task is owned: create via a `TaskGroup` or a supervisor; no fire-and-forget `create_task` without
  a stored reference and error handler.
- Every external await has a timeout (`asyncio.timeout`). Cancellation must be honoured — never swallow
  `CancelledError`.
- Bounded queues everywhere (`asyncio.Queue(maxsize=...)`); document the overflow policy.
- Time: inject a clock; use exchange timestamps (ms, UTC) for market data; never `datetime.now()` without tz.

## Types and style
- `mypy --strict` clean; no `Any` in public signatures; `# type: ignore[code]` needs a justification comment.
- Money/price/qty: `Decimal` (or integer ticks) — never `float` for order values. Round to instrument
  tick/lot via the instrument-info cache.
- Errors: domain exceptions per module; map to RFC 7807 problem responses at the HTTP edge only.
- Logging: structlog, JSON, with `correlation_id`; never log secrets, API keys, signatures, or full order payloads
  with credentials (see `50-security.md`).

## Tests
- pytest + pytest-asyncio (`asyncio_mode = "auto"`), hypothesis for invariants (bar aggregation, book deltas,
  rounding, risk limits). Coverage ≥85% line / ≥75% branch for `services/api/**` (CONSTITUTION §9 #3).
- Market/exchange data comes from recorded fixtures under `packages/fixtures/bybit/`; no network (see `40-testing.md`).
- Mark integration tests `@pytest.mark.integration` (need docker compose stack).
