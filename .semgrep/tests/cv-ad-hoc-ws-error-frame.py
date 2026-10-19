"""Fixtures for cv-ad-hoc-ws-error-frame (E17-T05; E17-X02 adds the keyword, helper, item and text forms).

Scanned only, never imported: each `ruleid` row must fire and each `ok` row must stay clean.
"""
import json

import msgpack

# --- a dict literal (key order does not matter; a `**` spread needs its own row)
a1 = {"t": "err", "p": {"code": "x"}}  # ruleid: cv-ad-hoc-ws-error-frame
a2 = {"type": "err", "p": {"code": "x"}}  # ruleid: cv-ad-hoc-ws-error-frame
a3 = {"p": {"code": "x"}, "t": "err"}  # ruleid: cv-ad-hoc-ws-error-frame
a4 = {**base, "t": "err"}  # ruleid: cv-ad-hoc-ws-error-frame
a5 = {**base, "type": "err"}  # ruleid: cv-ad-hoc-ws-error-frame
# --- keyword-built: dict(...), any other call that takes the type, the gateway's reply helper
b1 = dict(t="err", p={"code": "x"})  # ruleid: cv-ad-hoc-ws-error-frame
b2 = dict(type="err", p={})  # ruleid: cv-ad-hoc-ws-error-frame
b3 = _reply("err", fid, p={})  # ruleid: cv-ad-hoc-ws-error-frame
b4 = _reply(t="err", frame_id=fid)  # ruleid: cv-ad-hoc-ws-error-frame
b5 = conn.push(_reply("err", frame.get("id"), p={"code": "internal_error"}))  # ruleid: cv-ad-hoc-ws-error-frame
b6 = make_frame(type="err", p={})  # ruleid: cv-ad-hoc-ws-error-frame
# --- built up key by key
frame["t"] = "err"  # ruleid: cv-ad-hoc-ws-error-frame
frame["type"] = "err"  # ruleid: cv-ad-hoc-ws-error-frame
frame.update(t="err")  # ruleid: cv-ad-hoc-ws-error-frame
frame.update(type="err")  # ruleid: cv-ad-hoc-ws-error-frame
frame.update({"t": "err"})  # ruleid: cv-ad-hoc-ws-error-frame
frame.setdefault("t", "err")  # ruleid: cv-ad-hoc-ws-error-frame
frame.setdefault("type", "err")  # ruleid: cv-ad-hoc-ws-error-frame
# --- packed straight to msgpack or JSON
c1 = msgpack.packb({"t": "err", "p": {}})  # ruleid: cv-ad-hoc-ws-error-frame
c2 = msgpack.packb(dict(t="err", p={}))  # ruleid: cv-ad-hoc-ws-error-frame
c3 = json.dumps({"p": {}, "t": "err"})  # ruleid: cv-ad-hoc-ws-error-frame
c4 = json.dumps(dict(type="err", p={}))  # ruleid: cv-ad-hoc-ws-error-frame
# --- written as JSON text (str, compact, bytes, escaped quotes, f-string)
d1 = '{"t": "err", "p": {"code": "x"}}'  # ruleid: cv-ad-hoc-ws-error-frame
d2 = '{"type":"err"}'  # ruleid: cv-ad-hoc-ws-error-frame
d3 = b'{"t":"err","p":{}}'  # ruleid: cv-ad-hoc-ws-error-frame
d4 = "{\"t\": \"err\"}"  # ruleid: cv-ad-hoc-ws-error-frame
d5 = f'{{"t": "err", "p": {body}}}'  # ruleid: cv-ad-hoc-ws-error-frame
d6 = '{"p": {}, "t": "err"}'  # ruleid: cv-ad-hoc-ws-error-frame
d7 = b'{"id": "1", "t": "err"}'  # ruleid: cv-ad-hoc-ws-error-frame
d8 = ' {"t" : "err"}'  # ruleid: cv-ad-hoc-ws-error-frame
# --- written as msgpack bytes (fixstr "t" or "type", then the fixstr "err")
e1 = b"\x81\xa1t\xa3err"  # ruleid: cv-ad-hoc-ws-error-frame
e2 = b"\x81\xa4type\xa3err"  # ruleid: cv-ad-hoc-ws-error-frame
e3 = b"\x81\xA1t\xA3err"  # ruleid: cv-ad-hoc-ws-error-frame
e4 = b'\x81\xa1t\xa3err'  # ruleid: cv-ad-hoc-ws-error-frame

# --- fine
f1 = {"t": "ok", "p": {}}  # ok: cv-ad-hoc-ws-error-frame
f2 = build_ws_error("frame_malformed", id="1")  # ok: cv-ad-hoc-ws-error-frame
f3 = dict(t="pong", p={})  # ok: cv-ad-hoc-ws-error-frame
f3b = _reply("pong", fid)  # ok: cv-ad-hoc-ws-error-frame
f3c = _reply(t="welcome", frame_id=fid)  # ok: cv-ad-hoc-ws-error-frame
f3d = harness.next_of_raw("err")  # ok: cv-ad-hoc-ws-error-frame
frame["t"] = "ok"  # ok: cv-ad-hoc-ws-error-frame
frame.update(t="ok")  # ok: cv-ad-hoc-ws-error-frame
frame.setdefault("t", "pong")  # ok: cv-ad-hoc-ws-error-frame
f4 = frame["t"] == "err"  # ok: cv-ad-hoc-ws-error-frame
f5 = msgpack.packb({"t": "pong", "p": frame})  # ok: cv-ad-hoc-ws-error-frame
f6 = json.dumps({"t": "ok", "p": frame})  # ok: cv-ad-hoc-ws-error-frame
f7 = '{"t": "pong"}'  # ok: cv-ad-hoc-ws-error-frame
f8 = '{"type": "error"}'  # ok: cv-ad-hoc-ws-error-frame
f9 = b"\x81\xa1t\xa4pong"  # ok: cv-ad-hoc-ws-error-frame
"""An `err` frame is built by `build_ws_error`, e.g. {"t": "err"} plus a code."""  # ok: cv-ad-hoc-ws-error-frame
