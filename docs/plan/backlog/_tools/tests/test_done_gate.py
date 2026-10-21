"""Unit tests for done_gate.py — no network; `gh` is injected."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import done_gate as dg

QA_PASS = {
    "body": "QA verification — VERDICT: PASS",
    "createdAt": "2026-10-01",
    "author": {"login": "qa"},
}
PENPOT = "https://design.penpot.app/#/workspace?team-id=t&file-id=f&page-id=p"
PAGE_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
# Literals on purpose: they pin the arguments done_gate passes to `gh`.
GH_REPO = "CandleViewer/CandleViewer"
GH_LIST_FIELDS = "number,body,mergedAt"
GH_VIEW_FIELDS = "number,body,files,reviews,comments,mergedAt"


def owner(body: str) -> dict[str, Any]:
    return {"body": body, "createdAt": "2026-10-02", "author": {"login": "basiltt"}}


def ticket(
    dod: list[str], labels: list[str] | None = None, kind: str = "Task"
) -> dict[str, Any]:
    body = "## Definition of Done\n" + "\n".join(dod) + "\n\n## Dependencies\n"
    return {"key": "T-1", "kind": kind, "labels": labels or [], "body": body}


def issue(
    comments: list[dict[str, Any]], labels: list[str] | None = None
) -> dict[str, Any]:
    return {
        "body": "",
        "comments": comments,
        "labels": [{"name": n} for n in labels or []],
    }


def rules(res: dict[str, Any]) -> list[str]:
    return [f["rule"] for f in res["failures"]]


def test_qa_missing_fails_and_present_passes() -> None:
    assert rules(dg.evaluate(ticket(["- [x] done"]), issue([]), [])) == ["qa"]
    assert dg.evaluate(ticket(["- [x] done"]), issue([QA_PASS]), [])["ok"]


def test_qa_latest_fail_verdict_fails() -> None:
    late = {"body": "QA re-verification — VERDICT: FAIL", "createdAt": "2026-10-03"}
    assert "qa" in rules(dg.evaluate(ticket([]), issue([QA_PASS, late]), []))


def test_design_absent_then_present() -> None:
    t = ticket(["- [x] spec"], ["type/design"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["design"] * 3
    c = [QA_PASS, owner(f"approved. {PENPOT} img/scr-1.png")]
    assert dg.evaluate(t, issue(c), [])["ok"]


def test_design_merged_pr_counts_as_approval() -> None:
    pr = {"body": f"{PENPOT} ![x](a/img/x.png)", "mergedAt": "2026-10-02", "files": []}
    assert dg.evaluate(ticket([], ["type/design"]), issue([QA_PASS]), [pr])["ok"]


def design_failures(ref: str) -> list[str]:
    """Failing rules for a design ticket whose only Penpot evidence is `ref`."""
    c = [QA_PASS, owner(f"approved. {ref} img/scr-1.png")]
    return rules(dg.evaluate(ticket([], ["type/design"]), issue(c), []))


def test_design_page_name_and_id_pass_without_workspace_link() -> None:
    assert design_failures(f"Page `E42-D02` · id `{PAGE_ID}`") == []


def test_design_page_name_without_page_id_still_fails() -> None:
    assert design_failures("page **`E42-D02`**") == ["design"]


def test_design_workspace_link_still_passes() -> None:
    assert design_failures(PENPOT) == []


@pytest.mark.parametrize(
    "ref",
    [
        f"Page `E42-D02` · id `{PAGE_ID}`",  # the wording of the open design PRs
        f"Page `E42-D02` — id `{PAGE_ID}`",
        f"Page `E42-D02`: id {PAGE_ID}",
        f"Page `E42-D02`, id {PAGE_ID}",
        f"page: `E42-D02` (id {PAGE_ID})",
        f"page **`E42-D02`**, page id `{PAGE_ID}`",
        f"page id `{PAGE_ID}`",
        f"page-id={PAGE_ID}",
        f"page_id: {PAGE_ID}",
        f"pageId: {PAGE_ID}",
        f"page ids {PAGE_ID}",
        f"Page ID: {PAGE_ID.upper()}",
        f"page id {'-' * 11}{PAGE_ID}",  # exactly 12 separator characters
        f"Page `{'x' * 60}` · id {PAGE_ID}",  # a 60-character name, the longest allowed
        f"Page `E42-D02`{' ' * 6}id {PAGE_ID}",  # 6 characters between name and `id`
        f"Page   `E42-D02` · id {PAGE_ID}",  # 3 blanks between `Page` and the name
        PENPOT,  # the workspace link
    ],
)
def test_has_penpot_reference_accepts_link_or_page_id(ref: str) -> None:
    assert dg.has_penpot_reference(ref)


@pytest.mark.parametrize(
    "ref",
    [
        "page **`E42-D02`**",  # a page name alone
        "page id `E42-D02`",  # a label, no UUID
        f"page id {PAGE_ID[:8]}",  # a label and an 8-hex run, not a UUID
        PAGE_ID,  # a UUID alone
        PAGE_ID[:8],  # an 8-hex run alone
        f"team id {PAGE_ID}",
        f"file id {PAGE_ID}",
        f"homepage id {PAGE_ID}",  # `page` inside another word
        f"webpage-id={PAGE_ID}",
        f"page id pending (file `{PAGE_ID}`)",  # prose between label and UUID
        f"page id TBD, file id `{PAGE_ID}`",
        f"page id pending; board ids `{PAGE_ID}`",
        f"board ids `{PAGE_ID}`, page id pending",
        f"page\nid {PAGE_ID}",  # label split over two lines
        f"page id {'-' * 12}{PAGE_ID}",  # 13 separator characters, one too many
        f"page id TBD {PAGE_ID}",
        f"page id\n{PAGE_ID}",  # a line break between label and UUID
        f"page id\r{PAGE_ID}",  # a lone carriage return
        f"page id{chr(0x0B)}{PAGE_ID}",  # a vertical tab
        f"page id{chr(0x0C)}{PAGE_ID}",  # a form feed
        f"page id{chr(0x85)}{PAGE_ID}",  # NEL
        f"page id{chr(0x2028)}{PAGE_ID}",  # LINE SEPARATOR
        f"Page `X`\nid {PAGE_ID}",  # a line break between the name and `id`
        f"Page\n`E42-D02` · id {PAGE_ID}",  # a line break between `Page` and the name
        f"Page    `E42-D02` · id {PAGE_ID}",  # 4 blanks between `Page` and the name
        f"Page `{'x' * 61}` · id {PAGE_ID}",  # a 61-character name, one too long
        f"Page `E42-D02`{' ' * 7}id {PAGE_ID}",  # 7 characters between name and `id`
        f"Page `E42-D02` · id pending (file `{PAGE_ID}`)",
        f"Page `E42-D02` · team id {PAGE_ID}",
        "https://design.penpot.app/",  # a bare host mention is not a workspace link
    ],
)
def test_has_penpot_reference_rejects_look_alikes(ref: str) -> None:
    assert not dg.has_penpot_reference(ref)


def test_perf_needs_number_or_exception() -> None:
    t = ticket(["- [x] p95 frame time recorded"], ["perf"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["perf"]
    pr = {"body": "p95 frame time 11.2 ms", "reviews": [], "comments": []}
    assert dg.evaluate(t, issue([QA_PASS]), [pr])["ok"]
    exc = owner("exception per #1778: DoD 1 waived, no reference hardware")
    res = dg.evaluate(t, issue([QA_PASS, exc]), [])
    assert res["ok"] and res["waived"]


def test_security_requires_approve_verdict() -> None:
    t = ticket([], ["security-review"])
    bad = {
        "body": "",
        "reviews": [{"body": "Security review — VERDICT: REQUEST_CHANGES"}],
    }
    ok = {"body": "", "reviews": [{"body": "Security review — VERDICT: APPROVE"}]}
    assert rules(dg.evaluate(t, issue([QA_PASS]), [bad])) == ["security"]
    assert dg.evaluate(t, issue([QA_PASS]), [ok])["ok"]


def test_ui_requires_a11y_evidence() -> None:
    t = ticket([], ["a11y"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["a11y"]
    pr = {"body": "axe: 0 serious/critical", "reviews": [], "comments": []}
    assert dg.evaluate(t, issue([QA_PASS]), [pr])["ok"]


def test_unchecked_box_fails_unless_specifically_waived() -> None:
    t = ticket(["- [x] a", "- [ ] second thing"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["dod"]
    exc = owner("waived #1778 — DoD 2 deferred to E37-Q04")
    assert dg.evaluate(t, issue([QA_PASS, exc]), [])["ok"]


def test_blanket_waiver_is_ignored() -> None:
    t = ticket(["- [ ] second thing"])
    res = dg.evaluate(
        t, issue([QA_PASS, owner("exception: waived everything #1778")]), []
    )
    assert rules(res) == ["dod"] and res["blanket_waivers_ignored"]


def test_waiver_by_non_owner_or_without_ref_ignored() -> None:
    t = ticket(["- [ ] second thing"])
    other = {"body": "waived #1778 DoD 1", "author": {"login": "agent"}}
    noref = owner("waived DoD 1")
    assert rules(dg.evaluate(t, issue([QA_PASS, other, noref]), [])) == ["dod"]


def test_waiver_by_quoted_fragment() -> None:
    t = ticket(["- [ ] Charters C2/C3 executed with session notes"])
    exc = owner('exception #1778: "Charters C2/C3 executed" deferred')
    assert dg.evaluate(t, issue([QA_PASS, exc]), [])["ok"]


# --- member-issue regressions -------------------------------------------------


def test_regress_1829_hardware_waived_but_inline_vs_worker_not() -> None:
    t = ticket(
        [
            "- [ ] Sweep completed across all listed environments (or gaps recorded)",
            "- [ ] Worker-vs-inline behavioural-equivalence result recorded",
        ],
        ["qa"],
    )
    exc = owner("exception #1778: DoD 1 hardware/browser sweep waived")
    res = dg.evaluate(t, issue([QA_PASS, exc]), [])
    assert not res["ok"]
    assert [f["item"] for f in res["failures"]] == [2]


def test_regress_1462_design_without_penpot_or_png() -> None:
    t = ticket(["- [x] hi-fi published"], ["type/design", "a11y"])
    res = dg.evaluate(t, issue([QA_PASS, owner("approved")]), [])
    details = " ".join(f["detail"] for f in res["failures"])
    assert "workspace link, or page name + page id" in details and "PNG" in details


def test_regress_1803_spike_measurement_not_run() -> None:
    t = ticket(
        ["- [x] benchmark table published for 60 s runs"], ["perf"], kind="Spike"
    )
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["perf"]


def test_regress_1830_missing_qa_signoff_contribution() -> None:
    t = ticket(["- [ ] QA sign-off comment posted; findings handed over"], ["qa"])
    assert rules(dg.evaluate(t, issue([QA_PASS]), [])) == ["dod"]


def test_run_gate_with_fake_gh_filters_prs_and_renders() -> None:
    found = [
        {"number": 1, "body": "Closes #5", "mergedAt": None},
        {"number": 2, "body": "unrelated #5 mention", "mergedAt": None},
    ]
    prs = dg.fetch("5", search_gh({"#5 in:body": found}, []))[1]
    assert [p["number"] for p in prs] == [1]
    out = dg.render(
        {
            "key": "K",
            "issue": 5,
            "ok": False,
            "waived": [],
            "blanket_waivers_ignored": [],
            "failures": [{"rule": "qa", "item": None, "detail": "x"}],
        }
    )
    assert out.startswith("K #5: FAIL")


# --- review round 2 ------------------------------------------------------------


def test_unchecked_box_evidenced_by_qa_table_row() -> None:
    t = ticket(["- [ ] Deterministic replay test green and reproducible"])
    qa = {
        "body": "QA verification — VERDICT: PASS\n| 1 | pass | deterministic replay test reproducible |",
        "createdAt": "2026-10-01",
    }
    res = dg.evaluate(t, issue([qa]), [])
    assert (
        res["ok"] and res["dod_items"][0]["status"] == "evidenced-by: QA PASS comment"
    )


def test_unchecked_box_evidenced_by_pr_body_and_explicit_ref() -> None:
    t = ticket(["- [ ] Coverage floor met", "- [ ] Demo done"])
    pr = {"number": 9, "body": "DoD 2 shown in review\nunit coverage floor met at 91%"}
    res = dg.evaluate(t, issue([QA_PASS]), [pr])
    assert [i["status"] for i in res["dod_items"]] == ["evidenced-by: PR #9 body"] * 2


def test_single_shared_word_is_not_evidence() -> None:
    t = ticket(["- [ ] Soak report attached"])
    assert rules(dg.evaluate(t, issue([QA_PASS, owner("soak later")]), [])) == ["dod"]


def test_waiver_comment_line_is_not_evidence_and_reports_waived_by() -> None:
    t = ticket(["- [ ] second thing here"])
    res = dg.evaluate(t, issue([QA_PASS, owner("waived #1778 DoD 1")]), [])
    assert res["ok"] and res["dod_items"][0]["status"].startswith("waived-by")


def test_ac_and_dod_waivers_are_separate_namespaces() -> None:
    t = ticket(["- [ ] second thing here"])
    res = dg.evaluate(t, issue([QA_PASS, owner("waived #1778: AC 1")]), [])
    assert rules(res) == ["dod"] and res["waived_acs"] == [1]


def test_perf_not_triggered_by_substrings_or_without_label() -> None:
    t = ticket(["- [x] works sometimes within a framework"])
    assert dg.evaluate(t, issue([QA_PASS]), [])["ok"]
    t2 = ticket(["- [x] memory use documented"])
    assert dg.evaluate(t2, issue([QA_PASS]), [])["ok"]
    assert rules(
        dg.evaluate(
            ticket(["- [x] memory use documented"], ["perf"]), issue([QA_PASS]), []
        )
    ) == ["perf"]


def test_security_later_request_changes_overrides_approve() -> None:
    t = ticket([], ["security-review"])
    rev = [
        {
            "body": "Security review — VERDICT: APPROVE",
            "author": {"login": "sec"},
            "submittedAt": "1",
        },
        {
            "body": "Security review — VERDICT: REQUEST_CHANGES",
            "author": {"login": "sec"},
            "submittedAt": "2",
        },
    ]
    assert rules(dg.evaluate(t, issue([QA_PASS]), [{"body": "", "reviews": rev}])) == [
        "security"
    ]
    rev.append(
        {
            "body": "Security review — VERDICT: APPROVE",
            "author": {"login": "sec"},
            "submittedAt": "3",
        }
    )
    assert dg.evaluate(t, issue([QA_PASS]), [{"body": "", "reviews": rev}])["ok"]


def test_design_not_approved_comment_does_not_count() -> None:
    t = ticket([], ["type/design"])
    c = [QA_PASS, owner(f"not approved yet. {PENPOT} a/x.png")]
    assert "design" in rules(dg.evaluate(t, issue(c), []))


def test_main_maps_json_decode_error_to_exit_2(monkeypatch: Any) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise ValueError("bad json")

    monkeypatch.setattr(dg, "run_gate", boom)
    assert dg.main(["K", "1"]) == 2


def test_fetch_links_closing_prs_and_merged_refs_prs_only() -> None:
    """Multi-PR tickets land parts with `Refs #N` and QA closes the ticket (E17-T02, #380):
    merged `Refs` PRs count as linked; an OPEN `Refs` PR never does (so it cannot satisfy
    the security gate before merge); unrelated mentions are ignored."""
    prs = [
        {"number": 1, "body": "Closes #380", "mergedAt": None},
        {
            "number": 2,
            "body": "Part B.\nRefs #380 #2042",
            "mergedAt": "2026-10-08T05:00:00Z",
        },
        {"number": 3, "body": "Refs #380", "mergedAt": None},
        {
            "number": 5,
            "body": "unrelated; see Refs #380 for context",
            "mergedAt": "2026-10-08T05:00:00Z",
        },
        {
            "number": 4,
            "body": "see #3800 and #380x",
            "mergedAt": "2026-10-08T05:00:00Z",
        },
    ]

    _, linked = dg.fetch("380", search_gh({"#380 in:body": prs}, []))
    assert [p["number"] for p in linked] == [1, 2]


def search_of(args: list[str]) -> str:
    return args[args.index("--search") + 1]


def crowd(n: int) -> list[dict[str, Any]]:
    """`n` PRs that merely cite issue 5, as other PRs' review records do."""
    return [
        {"number": 100 + i, "body": "review of #5", "mergedAt": None} for i in range(n)
    ]


def search_gh(
    answers: dict[str, Any], calls: list[list[str]], views: dict[int, Any] | None = None
) -> Any:
    """A `gh` stub that pins every argument. The issue view is empty; PR searches
    answer from `answers` (no entry: nothing found; an exception: raised) and PR views
    from `views` (default: the PR as a search returned it). PR calls go to `calls`."""
    found = {p["number"]: p for r in answers.values() if isinstance(r, list) for p in r}

    def fake_gh(args: list[str]) -> Any:
        if args[0] == "issue":
            return issue([QA_PASS])
        calls.append(args)
        if args[1] == "view":
            n = args[2]
            assert args == ["pr", "view", n, "-R", GH_REPO, "--json", GH_VIEW_FIELDS]
            return (views or found)[int(n)]
        query = search_of(args)
        assert args == [
            "pr",
            "list",
            "-R",
            GH_REPO,
            "--state",
            "all",
            "--search",
            query,
            "--limit",
            str(dg.PR_SEARCH_LIMIT),
            "--json",
            GH_LIST_FIELDS,
        ]
        result = answers.get(query, [])
        if isinstance(result, Exception):
            raise result
        return result

    return fake_gh


def queries(calls: list[list[str]]) -> list[str]:
    return [search_of(a) for a in calls if a[1] == "list"]


def viewed(calls: list[list[str]]) -> list[str]:
    return [a[2] for a in calls if a[1] == "view"]


def test_fetch_runs_the_fallback_searches_in_phrase_order_when_saturated() -> None:
    calls: list[list[str]] = []
    dg.fetch("5", search_gh({"#5 in:body": crowd(dg.PR_SEARCH_LIMIT)}, calls))
    assert queries(calls) == [
        "#5 in:body",
        '"closes #5" in:body',
        '"fixes #5" in:body',
        '"resolves #5" in:body',
        '"refs #5" in:body',
        '"ref #5" in:body',
    ]


def test_fetch_asks_every_search_for_pr_search_limit_prs() -> None:
    calls: list[list[str]] = []
    dg.fetch("5", search_gh({"#5 in:body": crowd(dg.PR_SEARCH_LIMIT)}, calls))
    limits = {a[a.index("--limit") + 1] for a in calls if a[1] == "list"}
    assert limits == {str(dg.PR_SEARCH_LIMIT)}


@pytest.mark.parametrize("phrase", ["closes", "fixes", "resolves", "refs", "ref"])
def test_fetch_links_a_pr_found_only_by_its_phrase_search(phrase: str) -> None:
    """A ticket cited by many other PRs' review records fills the best-match search and
    pushes its linked PR past the limit; the search for its own phrase finds it."""
    pr = {"number": 7, "body": f"{phrase.title()} #5", "mergedAt": "2026-10-20"}
    answers = {"#5 in:body": crowd(dg.PR_SEARCH_LIMIT), f'"{phrase} #5" in:body': [pr]}
    _, linked = dg.fetch("5", search_gh(answers, []))
    assert [p["number"] for p in linked] == [7]


def test_fetch_links_a_pr_found_by_two_searches_once_first_search_first() -> None:
    """The first search's results come first, then each phrase search's new ones."""
    in_first = {"number": 8, "body": "Closes #5", "mergedAt": None}
    closes_only = {"number": 6, "body": "Closes #5", "mergedAt": None}
    two_phrases = {"number": 9, "body": "Fixes #5, Resolves #5", "mergedAt": None}
    refs_only = {"number": 4, "body": "Refs #5", "mergedAt": "2026-10-20"}
    answers = {
        "#5 in:body": [in_first, *crowd(dg.PR_SEARCH_LIMIT - 1)],
        '"closes #5" in:body': [in_first, closes_only],
        '"fixes #5" in:body': [two_phrases],
        '"resolves #5" in:body': [two_phrases],
        '"refs #5" in:body': [refs_only, two_phrases],
    }
    _, linked = dg.fetch("5", search_gh(answers, []))
    assert [p["number"] for p in linked] == [8, 6, 9, 4]


def test_fetch_does_not_link_an_open_pr_found_by_the_refs_search() -> None:
    open_refs = {"number": 9, "body": "Refs #5", "mergedAt": None}
    answers = {
        "#5 in:body": crowd(dg.PR_SEARCH_LIMIT),
        '"refs #5" in:body': [open_refs],
    }
    _, linked = dg.fetch("5", search_gh(answers, []))
    assert linked == []


FULL_PR = {
    "number": 1,
    "body": "Closes #5",
    "mergedAt": "2026-10-20",
    "files": [{"path": "docs/design/img/a.png"}],
    "reviews": [{"body": "Security review — VERDICT: APPROVE"}],
    "comments": [],
}


def test_fetch_returns_the_pr_view_record_of_a_linked_pr() -> None:
    light = {"number": 1, "body": "Closes #5", "mergedAt": "2026-10-20"}
    answers = {"#5 in:body": [light]}
    _, linked = dg.fetch("5", search_gh(answers, [], views={1: FULL_PR}))
    assert linked == [FULL_PR]


def test_fetch_views_linked_prs_only() -> None:
    found = [
        {"number": 1, "body": "Closes #5", "mergedAt": None},
        {"number": 2, "body": "see #5", "mergedAt": None},
        {"number": 3, "body": "Refs #5", "mergedAt": None},
    ]
    calls: list[list[str]] = []
    dg.fetch("5", search_gh({"#5 in:body": found}, calls))
    assert viewed(calls) == ["1"]


@pytest.mark.parametrize(
    "found",
    [
        None,
        [],
        [{"number": 1, "body": "Closes #5", "mergedAt": None}],
        crowd(dg.PR_SEARCH_LIMIT - 1),
    ],
    ids=["null", "empty", "one", "limit-minus-one"],
)
def test_fetch_adds_no_fallback_search_below_the_limit(found: Any) -> None:
    calls: list[list[str]] = []
    dg.fetch("5", search_gh({"#5 in:body": found}, calls))
    assert queries(calls) == ["#5 in:body"]


def test_fetch_propagates_a_failing_fallback_search() -> None:
    answers = {
        "#5 in:body": crowd(dg.PR_SEARCH_LIMIT),
        '"fixes #5" in:body': RuntimeError("gh pr list failed: HTTP 502"),
    }
    with pytest.raises(RuntimeError, match="HTTP 502"):
        dg.fetch("5", search_gh(answers, []))


TIMEOUT = subprocess.TimeoutExpired("gh", dg.GH_TIMEOUT)


def done(rc: int, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["gh"], rc, out, err)


def gh_runs(monkeypatch: Any, *outcomes: Any) -> list[dict[str, Any]]:
    """Make `subprocess.run` give each of `outcomes` in turn (raising it if it is an
    exception); return the keyword arguments of every call."""
    queue, kwargs = list(outcomes), []

    def fake_run(cmd: list[str], **kw: Any) -> Any:
        kwargs.append(kw)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(dg.subprocess, "run", fake_run)
    return kwargs


def test_main_exits_2_when_a_fallback_search_fails(
    monkeypatch: Any, capsys: Any
) -> None:
    first = json.dumps(crowd(dg.PR_SEARCH_LIMIT))

    def fake_run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        args = cmd[1:]
        if args[0] == "issue":
            return done(0, json.dumps(issue([QA_PASS])))
        if search_of(args) == "#5 in:body":
            return done(0, first)
        return done(1, err="gh: HTTP 502: 502 Bad Gateway")

    monkeypatch.setattr(dg.subprocess, "run", fake_run)
    monkeypatch.setattr(dg, "load_ticket", lambda key: ticket([]))
    assert dg.main(["K", "5"]) == 2
    assert "done_gate error" in capsys.readouterr().err


@pytest.mark.parametrize(
    "first",
    [done(1, err="gh: HTTP 502: Bad Gateway"), done(1, err="HTTP 504"), TIMEOUT],
    ids=["502", "504", "timeout"],
)
def test_gh_json_retries_once_after_an_http_5xx_or_a_timeout(
    monkeypatch: Any, first: Any
) -> None:
    kwargs = gh_runs(monkeypatch, first, done(0, "[1]"))
    assert dg.gh_json(["pr", "list"]) == [1]
    assert len(kwargs) == 2


def test_gh_json_gives_each_call_a_timeout(monkeypatch: Any) -> None:
    kwargs = gh_runs(monkeypatch, done(0, "[]"))
    dg.gh_json(["pr", "list"])
    assert kwargs[0]["timeout"] == dg.GH_TIMEOUT


def test_gh_json_gives_up_after_one_retry(monkeypatch: Any) -> None:
    kwargs = gh_runs(monkeypatch, TIMEOUT, TIMEOUT)
    with pytest.raises(RuntimeError, match="timed out"):
        dg.gh_json(["pr", "list"])
    assert len(kwargs) == 2


def test_gh_json_does_not_retry_other_failures(monkeypatch: Any) -> None:
    kwargs = gh_runs(monkeypatch, done(1, err="HTTP 404: Not Found"))
    with pytest.raises(RuntimeError, match="404"):
        dg.gh_json(["issue", "view", "5"])
    assert len(kwargs) == 1


def test_security_rc_on_one_part_is_not_masked_by_later_approve_on_another() -> None:
    """Multi-PR tickets: verdicts are keyed per (PR, reviewer). Agent reviewers share one
    login, so a later APPROVE on part B must not override an RC on part A."""
    t = ticket([], ["security-review"])
    rc_then_ok = [
        {
            "number": 1,
            "body": "",
            "reviews": [],
            "comments": [
                {
                    "body": "Security review — VERDICT: REQUEST_CHANGES",
                    "createdAt": "2026-10-08T01:00:00Z",
                    "author": {"login": "basiltt"},
                }
            ],
        },
        {
            "number": 2,
            "body": "",
            "reviews": [],
            "comments": [
                {
                    "body": "Security review — VERDICT: APPROVE",
                    "createdAt": "2026-10-08T02:00:00Z",
                    "author": {"login": "basiltt"},
                }
            ],
        },
    ]
    assert rules(dg.evaluate(t, issue([QA_PASS]), rc_then_ok)) == ["security"]
    rc_then_ok[0]["comments"].append(
        {
            "body": "Security review (re-verdict) — VERDICT: APPROVE",
            "createdAt": "2026-10-08T03:00:00Z",
            "author": {"login": "basiltt"},
        }
    )
    assert dg.evaluate(t, issue([QA_PASS]), rc_then_ok)["ok"]
