"""Run one JS body in your Penpot plugin through the repo's penpot_exec.py and print rc + the parsed
result as JSON (truncated at 20 KB). The answer is redacted by penpot_exec.py.

Usage: python3 -I -B run_js.py <file.js> [--server NAME] [--project DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path

from _bridge import add_bridge_args, run_raw


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("file")
    add_bridge_args(ap)
    a = ap.parse_args()
    code = Path(a.file).read_text(encoding="utf-8")
    try:
        rc, text = run_raw(code, a.server, a.project)
    except SystemExit as e:
        print("rc", 1, json.dumps({"error": str(e.code)[:200]}))
        return 1
    try:
        obj = json.loads(text)
        res = obj.get("result", obj) if isinstance(obj, dict) else obj
        out = json.dumps(res, ensure_ascii=False)
    except ValueError:
        out = json.dumps({"error": "non-JSON answer", "len": len(text)})
    print("rc", rc, out[:20000])
    return rc


if __name__ == "__main__":
    sys.exit(main())
