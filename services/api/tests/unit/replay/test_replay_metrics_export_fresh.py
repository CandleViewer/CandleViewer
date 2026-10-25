"""#4468: `export_replay_metrics` serves every name it declares, whatever imported first.

Each replay series is defined in the module that updates it, so a name in `EXPORTED_NAMES` was
served only once its module had been imported by someone else. Only a fresh interpreter proves the
exporter is complete on its own (another test in this process may already have imported them).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[3]

# Imports only the exporter, renders it, and reports the declared names with no HELP line plus
# whether the retention wiring was imported along the way (it must not be needed).
_FRESH_PROBE = """
import json, sys
from prometheus_client import generate_latest
from candleviewer.observability.metrics import Metrics
from candleviewer.replay.metrics import EXPORTED_NAMES, export_replay_metrics
m = Metrics("demo")
collector = export_replay_metrics(m.registry, env="demo")
text = generate_latest(m.registry).decode()
collector.close()
missing = sorted(n for n in EXPORTED_NAMES if f"# HELP {n} " not in text)
print(json.dumps({"missing": missing, "wiring": "candleviewer.retention_wiring" in sys.modules}))
"""


def test_a_fresh_process_serves_every_exported_replay_name() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, a literal probe (#2914)
        [sys.executable, "-c", _FRESH_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"missing": [], "wiring": False}
