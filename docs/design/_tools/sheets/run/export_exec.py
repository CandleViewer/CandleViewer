"""Export drawn boards to PNG through the repo's penpot_exec.py, one call per board.

Usage: python3 -I -B export_exec.py <list.tsv> [--progress FILE] [--server NAME] [--project DIR]
           [--stop FILE]
The TSV has one board per line: page_id <tab> board_id <tab> board_name <tab> out_path (relative
to the current directory, or absolute). Each PNG is written only after its CRC-32, byte length
and pixel size match what the plugin reported; a PNG whose size differs from the board's (a resize
not yet persisted) is retried. Logs parsed fields only, never the raw answer. The token theme is
whatever the file has active: switch it first (theme-*.js) and wait 90 s before a light or
high-contrast export.
Exit 0: all exported; 1: a board failed (the log says which; later boards are still tried);
3: stopped (STOP file).
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path

from _bridge import add_bridge_args, now, progress, run_raw, stopped

JS = r"""
const PAGE_ID = %s, BOARD_ID = %s, NAME = %s;
const page = penpot.currentFile.pages.find((p) => p.id === PAGE_ID);
if (!page) return { error: "page not found" };
if (!penpot.currentPage || penpot.currentPage.id !== PAGE_ID) await penpot.openPage(page);
const b = page.getShapeById(BOARD_ID);
if (!b) return { error: "board not found" };
if (b.name !== NAME) return { error: "name mismatch", name: b.name };
const bytes = await b.export({ type: "png", scale: 1 });
const T = new Uint32Array(256);
for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; T[n] = c >>> 0; }
let crc = 0xffffffff;
for (let i = 0; i < bytes.length; i++) crc = T[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
crc = (crc ^ 0xffffffff) >>> 0;
let bin = ""; const CH = 0x8000;
for (let i = 0; i < bytes.length; i += CH) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
return { name: b.name, w: Math.round(b.width), h: Math.round(b.height), bytes: bytes.length, crc: crc.toString(16).padStart(8, "0"), b64: btoa(bin) };
"""


def export_one(code: str, out: Path, name: str, a: argparse.Namespace) -> str:
    """One attempt: the log line of a written PNG, or "!" + why it failed."""
    try:
        rc, text = run_raw(code, a.server, a.project)
        obj = json.loads(text)
        res = obj.get("result", obj) if isinstance(obj, dict) else obj
    except SystemExit:
        rc, res = 1, {"error": "bridge error"}
    except Exception as e:  # noqa: BLE001 - reported by its class only, never its text
        rc, res = 1, {"error": type(e).__name__}
    if not (rc == 0 and isinstance(res, dict) and res.get("b64")):
        err = res.get("error") if isinstance(res, dict) else type(res).__name__
        return f"!{name}: rc={rc} error={err}"
    data = base64.b64decode(res["b64"])
    crc = "%08x" % (zlib.crc32(data) & 0xFFFFFFFF)
    png = data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24]) if png else (0, 0)
    bw, bh = float(res.get("w") or 0), float(res.get("h") or 0)
    if crc != res.get("crc") or len(data) != res.get("bytes"):
        return f"!{name}: checksum/length mismatch"
    if abs(w - bw) > 1.5 or abs(h - bh) > 1.5:
        return f"!{name}: PNG {w}x{h} but board {bw:.0f}x{bh:.0f} (stale size)"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return f"ok {now()} {name} {len(data)} B {w}x{h} crc {crc}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("tsv")
    ap.add_argument("--progress")
    add_bridge_args(ap)
    a = ap.parse_args()
    with progress(a.progress) as log:
        return export_all(a, log)


def export_all(a: argparse.Namespace, log: TextIO) -> int:
    rc_all = 0
    for line in Path(a.tsv).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        page_id, board_id, name, out = line.split("\t")
        if stopped(a.stop):
            print(f"STOP {now()} before {name}", file=log, flush=True)
            return 3
        code = JS % (json.dumps(page_id), json.dumps(board_id), json.dumps(name))
        for attempt in (1, 2, 3):
            msg = export_one(code, Path(out), name, a)
            if not msg.startswith("!"):
                print(msg, file=log, flush=True)
                break
            print(f"attempt {attempt} {msg}", file=log, flush=True)
            time.sleep(30)
        else:
            rc_all = 1
            print(f"FAILED {now()} {name}", file=log, flush=True)
    return rc_all


if __name__ == "__main__":
    sys.exit(main())
