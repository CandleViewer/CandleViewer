"""E40-X01 (#1204) Part A: the webhook SSRF corpus has the shape E40-S03's policy tests read.

`ssrf_corpus.json` is data (the ruling on #1204, BQ-9): each entry carries its class, a URL, the
resolver script it runs with where it has one, and one expected outcome; `order` gives the policy's
steps and the precedence among address classes. This test reads the corpus only: no network, no
resolver and no policy (E40-S03 builds the policy and runs every entry, AC-AL-18).
"""

from __future__ import annotations

import ipaddress
import json
import re
from functools import cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

_CORPUS: Final = Path(__file__).with_name("ssrf_corpus.json")
_FIELDS: Final = frozenset(
    {"id", "class", "url", "via", "attempt", "redirect_to", "connect_to", "expect"}
)
#: Reasons only the url step gives: an entry refused with one never reaches a lookup.
_URL_STEP: Final = frozenset({"malformed_url", "userinfo"})


@cache
def _corpus() -> dict[str, Any]:
    corpus: dict[str, Any] = json.loads(_CORPUS.read_text(encoding="utf-8"))
    return corpus


def _reaches_lookup(entry: dict[str, Any], names: dict[str, dict[str, str]]) -> bool:
    """`entry`'s host is a name the url and name steps pass, so only a lookup decides it; an IP
    literal (IPv6, or IPv4 in any form whose last label is a number) stands for itself."""
    parts = urlsplit(entry["url"])
    if entry["expect"] in _URL_STEP or parts.scheme not in {"https", "http"}:
        return False
    # `name_normalisation`: ASCII only, so a host with any other character is refused at the url
    # step (`malformed_url`, returned above; the last test pins it); then lower case, one trailing
    # dot removed
    host = (parts.hostname or "").lower().removesuffix(".")
    if host in names["exact"] or host.endswith(tuple(names["suffix"])):
        return False
    return ":" not in host and not re.fullmatch(r"0x[0-9a-f]*|[0-9]+", host.rsplit(".", 1)[-1])


def test_ssrf_corpus_entries_are_classed_reasoned_and_scripted() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation

    (Every entry has its own class, a URL and one outcome the corpus declares; every resolver
    script, attempt, redirect and pin it names resolves inside the corpus; and a name the url and
    name steps pass has its resolver script, since the harness never asks the system resolver.)
    """
    corpus = _corpus()
    entries, resolvers = corpus["entries"], corpus["resolvers"]
    assert [e["id"] for e in entries] == [f"SSRF-{n:02d}" for n in range(1, len(entries) + 1)]
    assert len(entries) >= 87  # SSRF-01 to SSRF-87 when this was written
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
        if _reaches_lookup(e, corpus["refused_names"]):
            assert "via" in e, f"{e['id']}: a name with no resolver script"
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
    ranges, and loopback before the host's own services; the policy's own address lists and
    allow-list parse.)
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
    for net in corpus["tailnet_cidrs"]:
        ipaddress.ip_network(net)  # raises on a range that does not parse
    for key in ("tailnet_services", "metadata_addresses", "host_addresses"):
        for address in corpus[key]:
            ipaddress.ip_address(address)  # raises on an address that does not parse
    for endpoint in corpus["allow_list"]:  # a scheme, a host and a port, nothing more
        parts = urlsplit(endpoint)  # `.port` raises on a port that does not parse
        assert parts.scheme in {"https", "http"} and parts.hostname and parts.port != 0, endpoint
        assert not (parts.username or parts.path or parts.query or parts.fragment), endpoint


def test_ssrf_corpus_entries_that_pass_are_exactly_the_permitted_and_pinned_ones() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation

    (The entries that pass the policy are a fixed set: SSRF-01 and SSRF-02 are `permitted`, as
    are SSRF-82 and SSRF-83, the allow-listed name with a trailing dot and in upper case; SSRF-54
    is `pinned` to its first lookup's address. An entry moved into or out of the set fails here,
    before E40-S03 runs the corpus.)
    """
    entries = _corpus()["entries"]
    permitted = {e["id"] for e in entries if e["expect"] == "permitted"}
    pinned = {e["id"]: e.get("connect_to") for e in entries if e["expect"] == "pinned"}
    assert permitted == {"SSRF-01", "SSRF-02", "SSRF-82", "SSRF-83"}
    assert pinned == {"SSRF-54": "203.0.113.20"}


def test_ssrf_corpus_entries_with_a_non_ascii_host_expect_malformed_url() -> None:
    """Scenario: Abuse cases are executable (edge)
    Then each abuse case is written concretely enough that E40-X01 can automate it without
    further interpretation

    (The egress policy reads a host as ASCII only, with no IDNA mapping, the ruling on #1400: a
    host holding any non-ASCII character is `malformed_url` at the url step, whatever a mapping
    would make of it, and an internationalised endpoint is allow-listed in its punycode form.
    `name_normalisation` and the `url` step say so, and each such entry expects `malformed_url`.)
    """
    corpus = _corpus()
    assert corpus["name_normalisation"].startswith("ASCII only")
    url_step = corpus["order"][0]  # the first step, where such a host is refused
    assert url_step["step"] == "url", url_step
    for rule in (corpus["name_normalisation"], url_step["rule"]):  # `order` says it too
        assert "ASCII only" in rule, rule
    expects = {
        e["id"]: e["expect"]
        for e in corpus["entries"]
        if not (urlsplit(e["url"]).hostname or "").isascii()
    }
    # SSRF-62 fullwidth digits, SSRF-63 ideographic full stops, SSRF-84 a Cyrillic look-alike letter
    assert expects.keys() >= {"SSRF-62", "SSRF-63", "SSRF-84"}
    assert set(expects.values()) == {"malformed_url"}, expects
