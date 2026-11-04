"""E40-X01 (#1204) Part A: the webhook SSRF corpus has the shape E40-S03's policy tests read.

`ssrf_corpus.json` is data (the ruling on #1204, BQ-9): each entry carries its class, a URL, the
resolver script it runs with where it has one, and one expected outcome; `order` gives the policy's
steps and the precedence among address classes. This test reads the corpus only: no network, no
resolver and no policy (E40-S03 builds the policy and runs every entry, AC-AL-18).
"""

from __future__ import annotations

import ipaddress
import json
from functools import cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

_CORPUS: Final = Path(__file__).with_name("ssrf_corpus.json")
_FIELDS: Final = frozenset(
    {"id", "class", "url", "via", "attempt", "redirect_to", "connect_to", "expect"}
)


@cache
def _corpus() -> dict[str, Any]:
    corpus: dict[str, Any] = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return corpus


def test_ssrf_corpus_entries_are_classed_reasoned_and_scripted() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation

    (Every entry has its own class, a URL and one outcome the corpus declares, and every resolver
    script, attempt, redirect and pin it names resolves inside the corpus.)
    """
    corpus = _corpus()
    entries, resolvers = corpus["entries"], corpus["resolvers"]
    assert [e["id"] for e in entries] == [f"SSRF-{n:02d}" for n in range(1, len(entries) + 1)]
    assert len(entries) >= 86  # SSRF-01 to SSRF-86 when this was written
    for e in entries:
        assert {"id", "class", "url", "expect"} <= set(e) <= _FIELDS, e["id"]
        assert e["class"] in corpus["classes"], f"{e['id']}: class {e['class']!r}"
        assert e["expect"] in {*corpus["reasons"], "permitted", "pinned"}, e["id"]
        assert ("redirect_to" in e) == (e["expect"] == "redirect"), e["id"]
        assert ("connect_to" in e) == (e["expect"] == "pinned"), e["id"]
        lookups = resolvers[e["via"]].get(urlsplit(e["url"]).hostname, []) if "via" in e else []
        if "attempt" in e:  # each attempt resolves afresh, one scripted lookup each
            assert 2 <= e["attempt"] <= len(lookups), e["id"]
        if e["expect"] == "pinned":
            assert e["connect_to"] == lookups[0][0], e["id"]
    for script in resolvers.values():
        for answers in script.values():
            assert answers, "a scripted name with no lookup"
            for address in (a for lookup in answers for a in lookup):
                ipaddress.ip_address(address)  # raises on an answer that is not an address
    assert {e["class"] for e in entries} == set(corpus["classes"])
    assert {e["expect"] for e in entries} >= set(corpus["reasons"])
    assert {e.get("via") for e in entries} >= set(resolvers)


def test_ssrf_corpus_order_refuses_every_reason_and_ranks_the_address_classes() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation

    (Each entry has one answer: every refusal reason has its step, the name step refuses by the
    corpus's own name rules, and the address step ranks metadata before link-local and private
    ranges, and loopback before the host's own services.)
    """
    corpus = _corpus()
    steps = {step["step"]: step["refuses"] for step in corpus["order"]}
    assert len(steps) == len(corpus["order"]) and all(step["rule"] for step in corpus["order"])
    assert {reason for refuses in steps.values() for reason in refuses} == set(corpus["reasons"])
    names = corpus["refused_names"]
    assert set(steps["name"]) == {*names["exact"].values(), *names["suffix"].values()}
    assert (
        all(suffix.startswith(".") for suffix in names["suffix"]) and corpus["name_normalisation"]
    )
    rank = steps["address"].index
    assert rank("metadata") < min(rank("link_local"), rank("private_address"))
    assert rank("loopback") < rank("host_service")
    for net in corpus["public_stand_ins"]:  # global only through the harness's injected classifier
        assert not ipaddress.ip_network(net).is_global, net
