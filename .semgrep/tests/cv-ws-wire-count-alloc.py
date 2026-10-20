"""Fixtures for cv-ws-wire-count-alloc (E17-X02, SR-128): a count read from the wire must be
bounded before it sizes an allocation or a loop. `todoruleid` marks an accepted miss and `todook`
an accepted false positive (the rule's Known limits). `_fits` and `_rows` are the CVWB decoder's
own helpers (candleviewer.ws.binary). Run with: python tools/ci/check_semgrep_rule_tests.py
"""

import array
import itertools
import struct

HEADER = struct.Struct("<IBBBBBBIQ")
MAX_RECORDS = 4096


def record_count_list_bad(buf):  # the Gherkin: a list sized from a decoded record_count
    (record_count,) = struct.unpack_from("<I", buf, 8)
    return [None] * record_count  # ruleid: cv-ws-wire-count-alloc


def record_count_list_ok(buf):
    (record_count,) = struct.unpack_from("<I", buf, 8)
    if record_count > MAX_RECORDS:
        raise ValueError("record_count over the cap")
    return [None] * record_count  # ok: cv-ws-wire-count-alloc


async def every_source_bad(ws, buf, raw: bytes, msg):
    (a,) = struct.unpack("<I", buf)
    b = HEADER.unpack_from(buf)[6]
    c = next(HEADER.iter_unpack(buf))[6]
    d = int.from_bytes(buf[4:8], "little")
    e = memoryview(buf)[4]
    view = memoryview(buf).cast("B")
    f = memoryview(buf).cast("I")[0]
    held: bytes = buf[4:]
    frame = await ws.receive_bytes()
    data = msg["bytes"]
    got = msg.get("bytes")
    bytearray(a)  # ruleid: cv-ws-wire-count-alloc
    bytearray(b)  # ruleid: cv-ws-wire-count-alloc
    bytearray(c)  # ruleid: cv-ws-wire-count-alloc
    bytearray(d)  # ruleid: cv-ws-wire-count-alloc
    bytearray(e)  # ruleid: cv-ws-wire-count-alloc
    bytearray(f)  # ruleid: cv-ws-wire-count-alloc
    bytearray(raw[4])  # ruleid: cv-ws-wire-count-alloc
    bytearray(view[4])  # ruleid: cv-ws-wire-count-alloc
    bytearray(held[4])  # ruleid: cv-ws-wire-count-alloc
    bytearray(frame[8])  # ruleid: cv-ws-wire-count-alloc
    bytearray(data[8])  # ruleid: cv-ws-wire-count-alloc
    bytearray(got[8])  # ruleid: cv-ws-wire-count-alloc
    bytearray(msg["bytes"][4])  # ruleid: cv-ws-wire-count-alloc
    async for chunk in ws.iter_bytes():
        bytearray(chunk[4])  # ruleid: cv-ws-wire-count-alloc
    bytearray(16)  # ok: cv-ws-wire-count-alloc


def every_sink_bad(buf):
    (n,) = struct.unpack_from("<I", buf, 8)
    bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    bytes(n)  # ruleid: cv-ws-wire-count-alloc
    [0] * n  # ruleid: cv-ws-wire-count-alloc
    n * [0]  # ruleid: cv-ws-wire-count-alloc
    (0,) * n  # ruleid: cv-ws-wire-count-alloc
    n * (0,)  # ruleid: cv-ws-wire-count-alloc
    "-" * n  # ruleid: cv-ws-wire-count-alloc
    n * b"\x00"  # ruleid: cv-ws-wire-count-alloc
    bytes(1) * n  # ruleid: cv-ws-wire-count-alloc
    n * bytes(1)  # ruleid: cv-ws-wire-count-alloc
    bytearray(1) * n  # ruleid: cv-ws-wire-count-alloc
    n * bytearray(b"\x00")  # ruleid: cv-ws-wire-count-alloc
    array.array("I", [0]) * n  # ruleid: cv-ws-wire-count-alloc
    n * array.array("I", [0])  # ruleid: cv-ws-wire-count-alloc
    itertools.repeat(None, n)  # ruleid: cv-ws-wire-count-alloc
    _rows(buf, 0, n, None, "rows")  # ruleid: cv-ws-wire-count-alloc
    range(2, n)  # ruleid: cv-ws-wire-count-alloc
    range(0, n, 2)  # ruleid: cv-ws-wire-count-alloc
    for _ in range(n):  # ruleid: cv-ws-wire-count-alloc
        pass


def guards_that_refuse_ok(self, buf, frames):
    a, b, c, d, e, f, g, h, i, j, k, m, n = struct.unpack_from("<IIIIIIIIIIIII", buf, 8)
    if a * 16 > len(buf) - 12:
        print("short")
        raise ValueError("a")
    if b >= MAX_RECORDS: raise ValueError("b")
    if MAX_RECORDS < c: raise ValueError("c")
    if MAX_RECORDS <= d: return None
    if e > MAX_RECORDS or e < 0: raise ValueError("e")
    if not f <= MAX_RECORDS: raise ValueError("f")
    if not 0 < g <= MAX_RECORDS: raise ValueError("g")
    if not 0 <= h <= MAX_RECORDS: raise ValueError("h")
    exact = 12 + i * 85
    if len(buf) != exact: raise ValueError("length")
    need = 12 + j * 85
    if need != len(buf): raise ValueError("length")
    if len(buf) != 12 + k * 85: raise ValueError("length")
    if 12 + m * 85 != len(buf): raise ValueError("length")
    if n > MAX_RECORDS: raise ValueError("n")
    (self.n,) = struct.unpack_from("<I", buf, 4)
    if self.n > MAX_RECORDS: raise ValueError("self.n")
    if n:  # a later `if` that mentions the value is not the guard
        bytes(n)  # ok: cv-ws-wire-count-alloc
    for frame in frames:
        (p,) = struct.unpack_from("<I", frame, 8)
        if p > MAX_RECORDS: continue
        bytearray(p)  # ok: cv-ws-wire-count-alloc
    [0] * a, [0] * b, [0] * c, [0] * d, [0] * e, [0] * f  # ok: cv-ws-wire-count-alloc
    [0] * g, [0] * h, [0] * i, [0] * j, [0] * k, [0] * m  # ok: cv-ws-wire-count-alloc
    [0] * self.n  # ok: cv-ws-wire-count-alloc


def a_check_holds_until_the_name_is_bound_again(buf, offsets):
    n, m = struct.unpack_from("<II", buf, 8)
    if n > MAX_RECORDS: raise ValueError("n")
    (n,) = struct.unpack_from("<I", buf, 16)
    bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if n > MAX_RECORDS: raise ValueError("n")
    bytearray(n)  # ok: cv-ws-wire-count-alloc
    n = m
    bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if n > MAX_RECORDS: raise ValueError("n")
    n += m
    bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if n > MAX_RECORDS: raise ValueError("n")
    for off in offsets:
        (n,) = struct.unpack_from("<I", buf, off)
        bytearray(n)  # ruleid: cv-ws-wire-count-alloc


def checks_and_clamps_ok(buf, sizes: list[int]):
    a, b, c, d, e, f = struct.unpack_from("<IIIIII", buf, 8)
    _fits(a, 16, len(buf) - 12, "records")
    values = struct.unpack_from("<II", buf, 8)
    counts = [3, 4]
    if a > 8: print(bytearray(a))  # ok: cv-ws-wire-count-alloc
    if a > 0: return [None] * a  # ok: cv-ws-wire-count-alloc
    bytearray(min(b, MAX_RECORDS)), bytearray(min(c, len(buf))), bytearray(d & 0xFF)  # ok: cv-ws-wire-count-alloc
    bytearray(len(values)), bytearray(sizes[0]), bytearray(counts[0])  # ok: cv-ws-wire-count-alloc
    list(itertools.repeat(a, 3)), list(range(d, 10))  # ok: cv-ws-wire-count-alloc
    bytearray(e) if e <= MAX_RECORDS else None, bytearray(f) if f < MAX_RECORDS else None  # ok: cv-ws-wire-count-alloc


def fixed_size_containers_ok(buf):
    a, b = struct.unpack_from("<BB", buf)
    return bytes([a, b]), [a] * 4, (b,) * 2, bytearray([a]), bytearray(16)  # ok: cv-ws-wire-count-alloc


def guards_that_do_not_bound_bad(buf, other):
    a, b, c, d, e, f, g, h, i, j, k, m, n, o, p, q, r, s, u, v, w = struct.unpack_from("<21I", buf, 8)
    if a == 0: return b""
    bytearray(a)  # ruleid: cv-ws-wire-count-alloc
    if v == 4: return b""
    bytearray(v)  # ruleid: cv-ws-wire-count-alloc
    if not b: return b""
    bytearray(b)  # ruleid: cv-ws-wire-count-alloc
    if c < 1: raise ValueError("c")
    bytearray(c)  # ruleid: cv-ws-wire-count-alloc
    if w < 4: raise ValueError("w")
    bytearray(w)  # ruleid: cv-ws-wire-count-alloc
    if other > MAX_RECORDS: raise ValueError("other")
    bytearray(d)  # ruleid: cv-ws-wire-count-alloc
    assert e <= MAX_RECORDS
    bytearray(e)  # ruleid: cv-ws-wire-count-alloc
    if f > MAX_RECORDS: print("over the cap")
    bytearray(f)  # ruleid: cv-ws-wire-count-alloc
    if not g <= MAX_RECORDS: print("over the cap")
    bytearray(g)  # ruleid: cv-ws-wire-count-alloc
    exact = 12 + h * 85
    if len(buf) != exact: print("length")
    bytearray(h)  # ruleid: cv-ws-wire-count-alloc
    if i > 0: return bytearray(i)  # ruleid: cv-ws-wire-count-alloc
    if p: return bytearray(p)  # ruleid: cv-ws-wire-count-alloc
    if j >= 1: return bytearray(j)  # ruleid: cv-ws-wire-count-alloc
    if 0 < k: return bytearray(k)  # ruleid: cv-ws-wire-count-alloc
    if 1 <= m: return bytearray(m)  # ruleid: cv-ws-wire-count-alloc
    if not n <= 0: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if n > MAX_RECORDS: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if n >= MAX_RECORDS: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if MAX_RECORDS < n: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if MAX_RECORDS <= n: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if not n <= MAX_RECORDS: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if not 0 < n <= MAX_RECORDS: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if not 0 <= n <= MAX_RECORDS: return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if 12 + n * 85 != len(buf): return bytearray(n)  # ruleid: cv-ws-wire-count-alloc
    if len(buf) != 12 + r * 85: return bytearray(r)  # ruleid: cv-ws-wire-count-alloc
    need = 12 + s * 85
    if need != len(buf): return bytearray(s)  # ruleid: cv-ws-wire-count-alloc
    want = 12 + u * 85
    if len(buf) != want: return bytearray(u)  # ruleid: cv-ws-wire-count-alloc
    bytearray(o)  # ruleid: cv-ws-wire-count-alloc
    if o > MAX_RECORDS: raise ValueError("late")
    bytearray(min(p, q))  # ruleid: cv-ws-wire-count-alloc
    hdr = HEADER.unpack_from(buf)
    if hdr[0] != 0x42575643: raise ValueError("magic")
    return bytearray(hdr[6])  # ruleid: cv-ws-wire-count-alloc


def known_limits(buf, raw: bytes, frames, kind, pad):
    a, b, c, d, e, f, g, h, i, j, k, m, n, o, q, r, s = struct.unpack_from("<17I", buf, 8)
    if kind == 1 and a > MAX_RECORDS: raise ValueError("a")
    bytearray(a)  # todoruleid: cv-ws-wire-count-alloc
    if not 4 < n: raise ValueError("n")
    bytearray(n)  # todoruleid: cv-ws-wire-count-alloc
    if b > c: raise ValueError("b")
    bytearray(b)  # todoruleid: cv-ws-wire-count-alloc
    if d > MAX_RECORDS:
        if kind: raise ValueError("d")
    bytearray(d)  # todoruleid: cv-ws-wire-count-alloc
    hdr = HEADER.unpack_from(buf)
    if hdr[0] > 3: raise ValueError("version")
    bytearray(hdr[6])  # todoruleid: cv-ws-wire-count-alloc
    bytearray(16) if e <= MAX_RECORDS else bytearray(e)  # todoruleid: cv-ws-wire-count-alloc
    try:
        if f > MAX_RECORDS: raise ValueError("f")
    except ValueError:
        pass
    bytearray(f)  # todoruleid: cv-ws-wire-count-alloc
    for frame in frames:
        (p,) = struct.unpack_from("<I", frame, 8)
        if p > MAX_RECORDS: continue
    bytearray(p)  # todoruleid: cv-ws-wire-count-alloc
    while g:  # todoruleid: cv-ws-wire-count-alloc
        g -= 1
    make_buffer(h)  # todoruleid: cv-ws-wire-count-alloc
    bytearray(read_count(buf))  # todoruleid: cv-ws-wire-count-alloc
    if o * q > len(buf): raise ValueError("oq")
    bytearray(q)  # todoruleid: cv-ws-wire-count-alloc
    if not r > MAX_RECORDS: raise ValueError("r")
    bytearray(r)  # todoruleid: cv-ws-wire-count-alloc
    body = raw[12:]
    bytearray(body[0])  # todoruleid: cv-ws-wire-count-alloc
    need = s * 16
    if need > len(buf): raise ValueError("need")
    bytearray(s)  # todook: cv-ws-wire-count-alloc
    if i <= MAX_RECORDS: bytearray(i)  # todook: cv-ws-wire-count-alloc
    if j > MAX_RECORDS: j = MAX_RECORDS
    bytearray(j)  # todook: cv-ws-wire-count-alloc
    if k > MAX_RECORDS: raise ValueError("k")
    else: bytearray(k)  # todook: cv-ws-wire-count-alloc
    if k > 8: return bytearray(k)  # todook: cv-ws-wire-count-alloc
    if raw[4] > MAX_RECORDS: raise ValueError("raw")
    bytearray(raw[4])  # todook: cv-ws-wire-count-alloc
    gap = len(buf) - 12
    if gap > 8: return b"\x00" * gap  # todook: cv-ws-wire-count-alloc
    return pad * m, "x".ljust(m)  # todoruleid: cv-ws-wire-count-alloc


def guard_spellings_flagged(buf):
    a, b, c, d, e, f, g, h, i = struct.unpack_from("<9I", buf, 8)
    for _ in range(i, 0, -1): pass  # todoruleid: cv-ws-wire-count-alloc
    if len(buf) != 12 + 85 * a: raise ValueError("a")
    bytearray(a)  # todook: cv-ws-wire-count-alloc
    if not 0 <= b < MAX_RECORDS: raise ValueError("b")
    bytearray(b)  # todook: cv-ws-wire-count-alloc
    if not 0 < c < MAX_RECORDS: raise ValueError("c")
    bytearray(c)  # todook: cv-ws-wire-count-alloc
    if not d < MAX_RECORDS: raise ValueError("d")
    bytearray(d)  # todook: cv-ws-wire-count-alloc
    bytearray(MAX_RECORDS if e > MAX_RECORDS else e)  # todook: cv-ws-wire-count-alloc
    exact = 12 + f * 85
    if len(buf) != exact: raise ValueError("f")
    bytearray(exact)  # todook: cv-ws-wire-count-alloc
    if g > 1: raise ValueError("g")
    bytearray(g)  # todook: cv-ws-wire-count-alloc
    _fits(1, h * 16, len(buf) - 12, "h")
    bytearray(h)  # todook: cv-ws-wire-count-alloc
