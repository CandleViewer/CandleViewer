"""E17-Q03 WS load harness (#568): the k6 profiles A, B and C, the W5 answer, the verdict.

`fixture_app.py` is the backend under load: the real `/ws` gateway on loopback, fed by `feeder.py`
from the recorded corpus. `tests/load/ws/` is the k6 client, and `tests/load/ws/profiles.json` the
one profile table both sides read. `budgets.py` judges what k6 and the `/metrics` scrapes
measured, `w5.py` holds the pre-registered W5 rule, `runner.py` drives a run.

Offline: recorded corpus and seeded clones only, loopback only (C-13.5, C-12.9).
"""

#: Bumped when a metric's definition changes: a baseline from another version is not compared
#: (`bench.ingestion.gate.compare(..., harness_version=...)`).
HARNESS_VERSION = "e17-q03/1"

#: The fixture backend's ready line on stdout: `CV_BENCH_WS_READY port=<p> pid=<n> tokens=<path>`.
READY = "CV_BENCH_WS_READY"

#: The event loop the fixture runs on: the stdlib's, so that its Python socket guard sees every
#: lookup. Production's uvicorn picks uvloop where it is installed, so loop-sensitive numbers
#: (fan-out, loop lag, CPU) of this harness are comparable with its own runs, not with production's.
LOOP = "asyncio"
