"""The E29 OMS scenario pack's loader, for the test tree (E29-Q01, #844).

A scenario is a directory of `packages/fixtures/oms/` with a `manifest.json` (its README says what
every field means). `load()` reads one, checks it against every rule the pack states and returns it
whole: the REST stubs, the private-WS frames, the faults laid over them. The corpus files a scenario
delivers are read through `tests._corpus`, the one door every test uses to the shared corpus.

Offline and deterministic by construction: the loader opens files and nothing else (no socket, no
clock, no randomness, no cache), so two loads of one scenario are byte-identical (`canonical()`).
Everything is the pack's own data; no value here is a venue fact: what a scenario's evidence class
means is in the pack's README.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from jsonschema import Draft202012Validator

from tests._corpus import CORPUS_ROOT, corpus_path
from tests._corpus import manifest as corpus_manifest

__all__ = [
    "EVIDENCE_RANK",
    "MANIFEST",
    "PACK_ROOT",
    "SCHEMA",
    "Injection",
    "PackError",
    "RestReply",
    "Scenario",
    "UnstubbedCall",
    "load",
    "manifest",
    "path_of",
    "scenario_names",
    "schema",
]

PACK_ROOT: Final = Path(__file__).resolve().parents[3] / "packages" / "fixtures" / "oms"
MANIFEST: Final = "manifest.json"
SCHEMA: Final = "manifest.schema.json"
#: Weakest first: a scenario is as strong as the weakest thing it delivers.
EVIDENCE_RANK: Final = {"derived": 0, "docs-transcribed": 1, "recorded": 2}
WS_FAULTS: Final = frozenset({"drop", "duplicate", "reorder"})
REST_FAULTS: Final = frozenset({"timeout", "http_5xx"})


class PackError(ValueError):
    """A scenario that breaks a rule of the pack; the message names the scenario and the rule."""


class UnstubbedCall(LookupError):
    """A REST call no stub of the scenario answers: a test failure, never a silent success."""


@dataclass(frozen=True)
class RestReply:
    """What a stub answers: the status and the decoded JSON body, and the file it came from."""

    call: str
    status: int
    body: Any
    payload: str


@dataclass(frozen=True)
class Injection:
    """One fault of the manifest's `inject` list (the pack's README says what each kind does)."""

    kind: str
    call: str | None = None
    frame: int | None = None
    to: int | None = None


@dataclass(frozen=True)
class Scenario:
    """A loaded scenario. `frames` are the private-WS lines as written (raw text, in order)."""

    name: str
    manifest: Mapping[str, Any]
    frames: tuple[str, ...]
    replies: Mapping[str, RestReply]
    injections: tuple[Injection, ...]
    #: Every file read, as the manifest writes it, with the sha256 of its bytes.
    files: Mapping[str, str]

    def reply(self, method: str, path: str) -> RestReply:
        """The stub for `<METHOD> <path>`; `UnstubbedCall` when the scenario has none."""
        try:
            return self.replies[f"{method} {path}"]
        except KeyError:
            raise UnstubbedCall(f"{self.name}: no stub answers {method} {path}") from None

    def delivered_frames(self) -> tuple[str, ...]:
        """The frames the stream delivers: `frames` with the WS faults applied, in the order
        listed, each to the sequence as the one before left it."""
        out = list(self.frames)
        for fault in self.injections:
            if fault.kind not in WS_FAULTS:
                continue
            assert fault.frame is not None  # checked at load
            if fault.kind == "drop":
                del out[fault.frame]
            elif fault.kind == "duplicate":
                out.insert(fault.frame + 1, out[fault.frame])
            else:
                assert fault.to is not None
                out.insert(fault.to, out.pop(fault.frame))
        return tuple(out)

    def canonical(self) -> bytes:
        """The bytes two loads of this scenario must agree on: everything it holds, key-sorted."""
        body = {
            "scenario": self.name,
            "manifest": self.manifest,
            "files": dict(self.files),
            "replies": {k: dataclasses.asdict(v) for k, v in self.replies.items()},
            "frames": list(self.frames),
            "delivered": list(self.delivered_frames()),
            "injections": [dataclasses.asdict(i) for i in self.injections],
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def schema(root: Path = PACK_ROOT) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / SCHEMA).read_text(encoding="utf-8"))
    return data


def scenario_names(root: Path = PACK_ROOT) -> list[str]:
    """The scenario directories, sorted."""
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
    )


def manifest(name: str, root: Path = PACK_ROOT) -> dict[str, Any]:
    """A scenario's manifest as written, unchecked."""
    path = root / name / MANIFEST
    if not path.is_file():
        raise PackError(f"{name}: no {MANIFEST}")
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise PackError(f"{name}: {MANIFEST} is not JSON ({error})") from error
    return data


def path_of(name: str, ref: str, root: Path = PACK_ROOT) -> Path:
    """A reference as scenario `name`'s manifest writes it, resolved to a file path: a bare file
    name is the scenario's own; a corpus file is `../<corpus>/<date>/<rest|ws>/<file>`, found by
    `tests._corpus`. A reference of any other form is a `PackError`."""
    parts = PurePosixPath(ref).parts
    if len(parts) == 1:
        return root / name / ref
    if len(parts) != 5 or parts[:2] != ("..", CORPUS_ROOT.name):
        raise PackError(f"{name}: {ref} is neither a file of this scenario nor of the corpus")
    return corpus_path("/".join(parts[3:]), capture_date=parts[2])


def load(name: str, root: Path = PACK_ROOT) -> Scenario:
    """Read scenario `name` and check it: the schema, the files it declares and delivers, the
    evidence class against the corpus manifest, the faults. `PackError` names the first rule it
    breaks."""
    return _Reader(name, root).scenario()


class _Reader:
    """One load: the checks in order, the files read once each."""

    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.root = root
        self.manifest = manifest(name, root)
        self.files: dict[str, str] = {}

    def scenario(self) -> Scenario:
        self._schema()
        m = self.manifest
        declared = m.get("files", {})
        self._declared(declared)
        replies = {call: self._stub(call, stub) for call, stub in m.get("rest", {}).items()}
        frames = tuple(
            line for ref in m.get("ws", {}).get("private", []) for line in self._frames(ref)
        )
        if not replies and not frames:
            raise PackError(f"{self.name}: delivers nothing (no rest stub, no ws frame)")
        self._evidence(replies, m.get("ws", {}).get("private", []))
        injections = self._injections(replies, len(frames))
        return Scenario(self.name, m, frames, replies, injections, dict(self.files))

    def _fail(self, what: str) -> PackError:
        return PackError(f"{self.name}: {what}")

    def _schema(self) -> None:
        errors = sorted(
            f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
            for e in Draft202012Validator(schema(self.root)).iter_errors(self.manifest)
        )
        if errors:
            raise self._fail("the manifest breaks the schema: " + "; ".join(errors))
        if self.manifest["scenario"] != self.name:
            raise self._fail(f"scenario {self.manifest['scenario']!r} is not its directory name")

    def _text(self, ref: str) -> str:
        path = path_of(self.name, ref, self.root)
        if not path.is_file():
            raise self._fail(f"{ref} does not exist")
        raw = path.read_bytes()
        self.files[ref] = hashlib.sha256(raw).hexdigest()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise self._fail(f"{ref} is not UTF-8") from error

    def _declared(self, declared: Mapping[str, Any]) -> None:
        """Every file of the directory is declared, delivered and derived from files that exist."""
        here = {p.name for p in (self.root / self.name).iterdir()} - {MANIFEST}
        m = self.manifest
        delivered = {s["payload"] for s in m.get("rest", {}).values()} | set(
            m.get("ws", {}).get("private", [])
        )
        for ref in sorted(here - set(declared)):
            raise self._fail(f"{ref} is in the directory but no `files` entry declares it")
        for ref in sorted(set(declared) - here):
            raise self._fail(f"{ref} is declared but is not in the directory")
        for ref in sorted(set(declared) - delivered):
            raise self._fail(f"{ref} is declared but no rest stub or ws list delivers it")
        for ref in sorted(r for r in delivered if "/" not in r and r not in declared):
            raise self._fail(f"{ref} is delivered but no `files` entry declares it")
        for ref, entry in declared.items():
            for source in entry["derived_from"]:
                if not path_of(self.name, source, self.root).is_file():
                    raise self._fail(f"{ref} is derived from {source}, which does not exist")
                self._text(source)

    def _stub(self, call: str, stub: Mapping[str, Any]) -> RestReply:
        ref = stub["payload"]
        try:
            body = json.loads(self._text(ref))
        except ValueError as error:
            raise self._fail(f"{ref} is not JSON ({error})") from error
        return RestReply(call, stub.get("http_status", 200), body, ref)

    def _frames(self, ref: str) -> list[str]:
        """The file's lines: one JSON value each, no blank line, LF, a final newline."""
        text = self._text(ref)
        if "\r" in text or not text.endswith("\n") or "\n\n" in text or text.startswith("\n"):
            raise self._fail(f"{ref} must hold one JSON frame per line, LF, no blank line")
        lines = text.splitlines()
        for number, line in enumerate(lines, 1):
            try:
                json.loads(line)
            except ValueError as error:
                raise self._fail(f"{ref} line {number} is not JSON ({error})") from error
        return lines

    def _evidence(self, replies: Mapping[str, RestReply], ws: list[str]) -> None:
        """The declared class is the weakest class of what the scenario delivers."""
        delivered = [r.payload for r in replies.values()] + ws
        classes = ["derived" if "/" not in ref else self._corpus_class(ref) for ref in delivered]
        weakest = min(classes, key=EVIDENCE_RANK.__getitem__)
        if self.manifest["evidence"] != weakest:
            raise self._fail(
                f"evidence is {self.manifest['evidence']!r} but what it delivers is {weakest!r}"
            )

    def _corpus_class(self, ref: str) -> str:
        """The class of a corpus file, from its manifest `source`: a documented-shape file is
        built, not captured, so it counts as derived; an unknown source fails closed."""
        parts = PurePosixPath(ref).parts
        entries = {e["path"]: e for e in corpus_manifest(capture_date=parts[2])["fixtures"]}
        entry = entries.get("/".join(parts[3:]))
        if entry is None:
            raise self._fail(f"{ref} is not listed in its corpus manifest")
        source = str(entry["source"])
        if source == "docs-transcribed":
            return "docs-transcribed"
        if source == "derived" or source.startswith("documented-shape"):
            return "derived"
        if source == "recorded" or source.startswith("capture_fixture.py"):
            return "recorded"
        raise self._fail(f"{ref} has a corpus source, {source!r}, that is in no evidence class")

    def _injections(self, replies: Mapping[str, RestReply], count: int) -> tuple[Injection, ...]:
        """Each fault carries exactly the fields of its kind and hits something that exists."""
        out: list[Injection] = []
        for position, raw in enumerate(self.manifest.get("inject", [])):
            kind = raw["kind"]
            fields = {k for k in raw if k not in ("kind", "note")}
            where = f"inject[{position}] ({kind})"
            if kind in REST_FAULTS:
                if fields != {"call"} or raw["call"] not in replies:
                    raise self._fail(f"{where} needs `call` alone, naming a stubbed call")
            else:
                wanted = {"frame", "to"} if kind == "reorder" else {"frame"}
                if fields != wanted:
                    raise self._fail(
                        f"{where} needs {' and '.join(f'`{f}`' for f in sorted(wanted))}"
                    )
                if raw["frame"] >= count or raw.get("to", 0) >= count:
                    raise self._fail(f"{where} hits a frame the sequence does not have")
                if kind == "reorder" and raw["to"] == raw["frame"]:
                    raise self._fail(f"{where} moves a frame to where it already is")
                count += {"drop": -1, "duplicate": 1}.get(kind, 0)
            out.append(Injection(kind, raw.get("call"), raw.get("frame"), raw.get("to")))
        return tuple(out)
