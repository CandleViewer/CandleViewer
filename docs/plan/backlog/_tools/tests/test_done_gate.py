"""Unit tests for done_gate.py — no network; `gh` is injected."""

from __future__ import annotations

import os
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
    def fake(args: list[str]) -> Any:
        if args[0] == "issue":
            return issue([QA_PASS])
        return [
            {"number": 1, "body": "Closes #5", "reviews": [], "comments": []},
            {
                "number": 2,
                "body": "unrelated #5 mention",
                "reviews": [],
                "comments": [],
            },
        ]

    prs = dg.fetch("5", fake)[1]
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

    def fake_gh(args: list[str]) -> Any:
        return (
            {"body": "", "comments": [], "labels": [], "state": "OPEN"}
            if args[0] == "issue"
            else prs
        )

    _, linked = dg.fetch("380", fake_gh)
    assert [p["number"] for p in linked] == [1, 2]


def search_of(args: list[str]) -> str:
    return args[args.index("--search") + 1]


def test_fetch_reads_100_prs_and_adds_a_closing_search_when_saturated() -> None:
    """A ticket cited by many other PRs' review records fills the best-match search and
    pushes its closing PR past the limit; the closing-phrase search finds it, and a PR
    found by both queries is linked once."""
    both = {"number": 8, "body": "Closes #5", "mergedAt": None}
    crowd = [{"number": 100 + n, "body": "review of #5"} for n in range(99)]
    narrow_only = {"number": 7, "body": "Closes #5", "mergedAt": None}
    searches: list[list[str]] = []

    def fake_gh(args: list[str]) -> Any:
        if args[0] == "issue":
            return issue([QA_PASS])
        searches.append(args)
        return [both, narrow_only] if "closes" in search_of(args) else [both, *crowd]

    _, linked = dg.fetch("5", fake_gh)
    assert [search_of(a) for a in searches] == ["#5 in:body", '"closes #5" in:body']
    assert {a[a.index("--limit") + 1] for a in searches} == {"100"}
    assert [p["number"] for p in linked] == [8, 7]


@pytest.mark.parametrize(
    "found",
    [
        None,
        [],
        [{"number": 1, "body": "Closes #5", "mergedAt": None}],
        [{"number": n, "body": "see #5"} for n in range(99)],
    ],
    ids=["null", "empty", "one", "99"],
)
def test_fetch_adds_no_closing_search_below_the_limit(found: Any) -> None:
    searches: list[list[str]] = []

    def fake_gh(args: list[str]) -> Any:
        if args[0] == "issue":
            return issue([QA_PASS])
        searches.append(args)
        return found

    dg.fetch("5", fake_gh)
    assert [search_of(a) for a in searches] == ["#5 in:body"]


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
