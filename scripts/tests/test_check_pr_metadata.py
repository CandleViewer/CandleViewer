"""Unit tests for tools/ci/check_pr_metadata.py (#2249)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import check_pr_metadata as m  # noqa: E402

GOOD_TITLE = "ci(infra-devops): add pr-metadata gate"
GOOD_BODY = "Implements C-4.8.\n\nCloses #2249\n"
CL = (ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
ATTRS = (ROOT / ".gitattributes").read_text(encoding="utf-8")
RR = m._load_rule_refs(ROOT)
DECLARED = RR.load_declared_ids(str(ROOT))
OWNERS = "* @alice\n/services/ @bob @org/team\n"


GEN = ("set", "unset", "unspecified")  # real protocol dirs: generated AND -diff
NONE = ("unspecified", "unspecified", "unspecified")


def states(r, base_gen=(), head_gen=()):
    """Fake attr states: paths in `*_gen` are linguist-generated (plus real ATTRS patterns)."""
    def mk(gen):
        out = {}
        for _a, _d, path in r:
            hit = path in gen or path.startswith("packages/protocol/src/generated/")
            out[path] = GEN if hit else NONE
        return out
    return mk(base_gen), mk(head_gen or base_gen)


def pr(title=GOOD_TITLE, body=GOOD_BODY, labels=()):
    return {"title": title, "body": body, "labels": [{"name": n} for n in labels]}


def rows(*specs):
    return [(a, d, p) for a, d, p in specs]


def run(p=None, r=None, base=ATTRS, head=None, base_gen=(), head_gen=(), **kw):  # noqa: D103
    r = r if r is not None else rows(("1", "1", "src/a.py"))
    bs, hs = states(r, base_gen, head_gen)
    return m.check(
        p or pr(), r, bs, hs, base, base if head is None else head, CL, DECLARED,
        RR.RULE_ID_RE, **kw,
    )


def codes(errs):
    return [e.split()[0] for e in errs]


def labeled(actor="alice", at="2026-10-12T10:00:00Z"):
    return [{"event": "labeled", "label": {"name": m.LABEL}, "actor": {"login": actor},
             "created_at": at}]


def comment(user="alice", text="large-pr-approved: single atomic migration, cannot be split safely",
            at="2026-10-12T10:01:00Z"):
    return [{"user": {"login": user}, "body": text, "created_at": at}]


def test_clean_pr_passes():
    assert run() == ([], [])


def test_size_warns_above_400_fails_above_800():
    assert run(r=rows(("401", "0", "a")))[1]
    assert run(r=rows(("800", "0", "a")))[0] == []
    assert codes(run(r=rows(("801", "0", "a")))[0]) == ["PR-SIZE-001"]


def test_label_with_provenance_allows_large_pr():
    errs, warns = run(pr(labels=[m.LABEL]), rows(("900", "0", "a")), events=labeled(),
                      comments=comment(), base_codeowners=OWNERS)
    assert errs == [] and warns


def test_label_applied_by_non_owner_fails():
    errs, _ = run(pr(labels=[m.LABEL]), rows(("900", "0", "a")), events=labeled("mallory"),
                  comments=comment(), base_codeowners=OWNERS)
    assert codes(errs) == ["PR-SIZE-004", "PR-SIZE-005"]  # alice's comment is not the labeller's


def test_label_without_justification_fails():
    errs, _ = run(pr(labels=[m.LABEL]), rows(("900", "0", "a")), events=labeled(),
                  comments=comment(text="ok"), base_codeowners=OWNERS)
    assert codes(errs) == ["PR-SIZE-005"]
    errs, _ = run(pr(labels=[m.LABEL]), rows(("900", "0", "a")), events=labeled(),
                  comments=comment(user="mallory"), base_codeowners=OWNERS)
    assert codes(errs) == ["PR-SIZE-005"]


def test_justification_must_be_by_labeller_and_not_older_than_label():
    big = rows(("900", "0", "a"))
    kw = dict(base_codeowners=OWNERS, repo_owner="basiltt")
    errs, _ = run(pr(labels=[m.LABEL]), big, events=labeled("alice"),
                  comments=comment("basiltt"), **kw)
    assert codes(errs) == ["PR-SIZE-005"]  # a different owner's comment does not count
    errs, _ = run(pr(labels=[m.LABEL]), big, events=labeled(at="2026-10-12T10:00:00Z"),
                  comments=comment(at="2026-10-12T09:00:00Z"), **kw)
    assert codes(errs) == ["PR-SIZE-005"]  # justification predates the labelling
    errs, _ = run(pr(labels=[m.LABEL]), big, events=labeled(),
                  comments=comment(text="Do NOT apply large-pr-approved here, please split it up!"), **kw)
    assert errs == []  # wording is not judged; documented limitation of a text check


def test_repo_owner_may_apply_label():
    errs, _ = run(pr(labels=[m.LABEL]), rows(("900", "0", "a")), events=labeled("basiltt"),
                  comments=comment("basiltt"), base_codeowners=OWNERS, repo_owner="basiltt")
    assert errs == []


def test_owners_exclude_teams_and_use_last_match():
    assert m.owners_for(OWNERS, ["services/api/x.py"]) == {"bob"}
    assert m.owners_for(OWNERS, ["docs/x.md"]) == {"alice"}


def test_generated_and_lockfiles_excluded_from_base_attrs():
    r = rows(("5000", "0", "packages/protocol/src/generated/x.ts"), ("3000", "10", "pnpm-lock.yaml"),
             ("10", "0", "services/api/uv.lock"), ("20", "5", "src/a.py"))
    bs, _ = states(r)
    assert m.count_loc(r, bs)[:2] == (25, 8020)
    assert run(r=r)[0] == []


def test_uv_lock_elsewhere_is_not_excluded():
    assert m.count_loc(rows(("10", "0", "services/api/candleviewer/oms/uv.lock")), {})[0] == 10


def test_pr_cannot_exempt_itself_via_new_generated_pattern():
    head = ATTRS + "\nservices/api/candleviewer/oms/** linguist-generated=true\n"
    p = "services/api/candleviewer/oms/engine.py"
    r = rows(("5000", "0", p), ("2", "0", ".gitattributes"))
    errs, _ = run(r=r, head=head, head_gen=(p,))
    assert codes(errs) == ["PR-SIZE-001", "PR-SIZE-002"]
    assert "5000 LOC would be newly excluded" in errs[1]


def test_attribute_change_needs_label_even_when_small():
    errs, _ = run(r=rows(("1", "0", ".gitattributes")), head=ATTRS + "x.bin binary\n")
    assert codes(errs) == ["PR-SIZE-002"]
    assert run(r=rows(("1", "0", ".gitattributes")), head=ATTRS + "# comment only\n")[0] == []


def test_hash_midline_pattern_is_not_a_comment():
    assert m.attr_lines("a#b/** linguist-generated=true\n") == ["a#b/** linguist-generated=true"]
    assert m.attr_lines("# a -diff\n") == []


def test_reordering_attribute_lines_triggers_size_002():
    a = "svc/** linguist-generated=true\nsvc/core/** -linguist-generated\n"
    b = "svc/core/** -linguist-generated\nsvc/** linguist-generated=true\n"
    errs, _ = run(r=rows(("1", "0", ".gitattributes")), base=a, head=b)
    assert codes(errs) == ["PR-SIZE-002"]


def bin_run(paths, **kw):
    r = rows(*[("5", "0", p) for p in paths])
    return run(r=r, binary_paths=frozenset(paths), **kw)


def test_images_and_fonts_are_allowlisted_and_count_no_loc():
    assert bin_run([f"docs/{i}.png" for i in range(10)] + ["f.woff2"]) == ([], [])


def test_any_other_binary_needs_approval_whatever_the_count():
    for path in ("src/evil.ts", "oms/core.cpython-312-x86_64-linux-gnu.so", "LICENSE_BLOB",
                 ".husky/pre-commit", "x.wasm", "icon.svg"):
        errs, warns = bin_run([path], binary_sizes={path: "42"})
        assert codes(errs) == ["PR-SIZE-003"], path
        assert path in warns[0] and "42 bytes" in warns[0]


def test_binary_that_is_generated_in_base_is_excluded_not_flagged():
    p = "packages/protocol/src/generated/rest/index.ts"
    errs, warns = bin_run([p])
    assert errs == [] and warns == []


def test_gate_files_need_approval():
    for f in sorted(m.GATE_FILES):
        assert codes(run(r=rows(("1", "0", f)))[0]) == ["PR-SIZE-006"], f


def test_attr_drift_uses_merge_base_state():
    r = rows(("5", "0", "new/x.py"))
    bs, hs = states(r, head_gen=("new/x.py",))  # base tip says generated; merge-base agrees
    mb = dict(hs)
    errs, _ = m.check(pr(), r, hs, hs, ATTRS, ATTRS, CL, DECLARED, RR.RULE_ID_RE, merge_base_state=mb)
    assert errs == []
    errs, _ = m.check(pr(), r, hs, hs, ATTRS, ATTRS, CL, DECLARED, RR.RULE_ID_RE)
    assert errs == []  # no merge-base state: falls back to base state


def test_numstat_z_parsing_keeps_odd_paths():
    raw = "3\t1\tweird \"name\" é.py\0-\t-\tb.png\0"
    assert m.parse_numstat_z(raw) == [("3", "1", 'weird "name" é.py'), ("-", "-", "b.png")]


def test_title_checks():
    assert codes(run(pr(title="Add stuff"))[0]) == ["PR-TITLE-001"]
    assert codes(run(pr(title="wip(infra-devops): x"))[0]) == ["PR-TITLE-002"]
    assert codes(run(pr(title="ci(nonsense): x"))[0]) == ["PR-TITLE-003"]
    assert codes(run(pr(title="ci: x"))[0]) == ["PR-TITLE-001"]  # scope-empty is `never`
    assert run(pr(title="feat(oms-execution)!: x"))[0] == []


def test_scope_optional_when_commitlint_allows_it():
    lax = CL.replace('"scope-empty": [2, "never"]', '"scope-empty": [0]')
    assert m.parse_commitlint(lax)[2] is False
    assert m.parse_commitlint(CL)[2] is True


def test_empty_commitlint_parse_fails_loudly():
    with pytest.raises(m.ConfigError, match="PR-CONFIG-001"):
        m.parse_commitlint("module.exports = {};")


def test_body_requires_closes_or_fixes_not_refs():
    assert codes(run(pr(body="no link"))[0]) == ["PR-BODY-001"]
    assert codes(run(pr(body="Refs #12"))[0]) == ["PR-BODY-002"]
    assert run(pr(body="Fixes #12"))[0] == []
    assert codes(run(pr(body=None))[0]) == ["PR-BODY-001"]


def test_closes_inside_code_or_comment_ignored():
    assert codes(run(pr(body="`Closes #1`"))[0]) == ["PR-BODY-001"]
    assert codes(run(pr(body="<!-- Closes #1 -->"))[0]) == ["PR-BODY-001"]
    assert codes(run(pr(body="```\nCloses #1\n```"))[0]) == ["PR-BODY-001"]


def test_dangling_rule_reference():
    errs, _ = run(pr(title="ci(docs): per C-99.99", body="C-4.7 and C-88.1\nCloses #1"))
    assert codes(errs) == ["PR-RULE-001", "PR-RULE-001"]
    assert "C-4.7" not in " ".join(errs)
    errs, _ = run(pr(title="ci(nonsense): C-99.99"))
    assert sorted(codes(errs)) == ["PR-RULE-001", "PR-TITLE-003"]


# --- main(): real git diff against a throwaway repo, API replaced by a fake fetch -------------

def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/check_rule_refs.py", tmp_path / "scripts")
    shutil.copy(ROOT / "CONSTITUTION.md", tmp_path)
    shutil.copy(ROOT / "commitlint.config.cjs", tmp_path)
    (tmp_path / ".gitattributes").write_text("gen/** linguist-generated=true\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    return tmp_path, base


def _commit_head(root, files, attrs=None):
    _git(root, "checkout", "-qb", "feat")
    for name, n in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n" * n)
    if attrs:
        (root / ".gitattributes").write_text(attrs)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "head")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _fake(base, head, p, events=(), comments=()):
    def fetch(path):
        if path.endswith("/events"):
            return list(events)
        if path.endswith("/comments"):
            return list(comments)
        return {**p, "base": {"sha": base}, "head": {"sha": head}}
    return fetch


def test_main_runs_git_diff_with_base_attrs(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    head = _commit_head(root, {"gen/a.txt": 1000, "src/a.py": 5})
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, pr())) == 0
    assert "ok" in capsys.readouterr().out


def test_main_pr_adding_own_generated_pattern_fails(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    head = _commit_head(root, {"svc/a.py": 900},
                        attrs="gen/** linguist-generated=true\nsvc/** linguist-generated=true\n")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, pr())) == 1
    err = capsys.readouterr().err
    assert "PR-SIZE-001" in err and "PR-SIZE-002" in err and "900 LOC" in err


def test_main_uses_live_labels(repo, monkeypatch):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    head = _commit_head(root, {"svc/a.py": 900})
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, pr())) == 1
    live = pr(labels=[m.LABEL])
    assert m.main(["--repo-root", str(root)],
                  fetch=_fake(base, head, live, labeled("o"), comment("o"))) == 0


def test_main_requires_env_without_fetch(monkeypatch, capsys):
    for k in ("GITHUB_REPOSITORY", "PR_NUMBER", "GH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    assert m.main(["--repo-root", str(ROOT)]) == 2


def test_main_pr_cannot_hide_lines_with_own_diff_attribute(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    head = _commit_head(root, {"svc/a.py": 900},
                        attrs="gen/** linguist-generated=true\nsvc/** -diff\n")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, pr())) == 1
    err = capsys.readouterr().err
    assert "PR-SIZE-001" in err and "901 changed LOC" in err


def test_refs_with_partial_line_warns_not_fails():
    errs, warns = run(pr(body="Refs #12\nPartial: stack slice 2 of 5\n"))
    assert errs == [] and any("Partial" in w for w in warns)


def test_refs_with_empty_or_quoted_partial_fails():
    assert codes(run(pr(body="Refs #12\nPartial:\n"))[0]) == ["PR-BODY-002"]
    assert codes(run(pr(body="Refs #12\n`Partial: x`"))[0]) == ["PR-BODY-002"]
    assert codes(run(pr(body="Partial: x"))[0]) == ["PR-BODY-001"]


def test_closes_wins_over_refs_without_warning():
    assert run(pr(body="Closes #1\nRefs #2"))[1] == []


def _head_sha(root):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_main_nul_byte_source_counts_real_loc_warns_and_fails(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    _git(root, "checkout", "-qb", "feat")
    (root / "src").mkdir()
    (root / "src/evil.ts").write_bytes(b"export const x = 1;\n\0\n" * 500)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "head")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, _head_sha(root), pr())) == 1
    cap = capsys.readouterr()
    assert "PR-SIZE-003" in cap.err and "PR-SIZE-001" in cap.err  # 1000 real lines, not 0
    assert "src/evil.ts" in cap.out and "bytes" in cap.out


def test_main_real_nested_minus_diff_on_generated_dir_is_not_flagged(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    pkg = root / "packages/protocol"
    pkg.mkdir(parents=True)
    (pkg / ".gitattributes").write_text("src/generated/** linguist-generated=true\n"
                                        "src/generated/** -diff\n")
    (root / ".gitattributes").write_text("")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "attrs on base")
    base = _head_sha(root)
    _git(root, "checkout", "-qb", "feat")
    (pkg / "src/generated").mkdir(parents=True)
    (pkg / "src/generated/index.ts").write_text("export {};\n" * 3000)
    (pkg / "src/generated/.manifest.json").write_text("{}\n" * 10)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "regen")
    head = _head_sha(root)
    raw = subprocess.check_output(["git", "--attr-source=" + base, "diff", "--numstat", base, head],
                                  cwd=root, text=True)
    assert "-\t-\t" in raw  # git really reports these as binary
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, pr())) == 0
    assert "PR-SIZE" not in capsys.readouterr().err


def test_main_deleting_and_moving_binaries_does_not_crash(repo, monkeypatch, capsys):
    root, _ = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    (root / "docs").mkdir()
    (root / "docs/old.png").write_bytes(b"\x89PNG\0\0")
    (root / "docs/a.png").write_bytes(b"\x89PNG\0\1")
    (root / "blob.bin").write_bytes(b"\0\1\2")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "add bins")
    base = _head_sha(root)
    _git(root, "checkout", "-qb", "feat")
    _git(root, "rm", "-q", "docs/old.png", "blob.bin")
    _git(root, "mv", "docs/a.png", "docs/b.png")
    _git(root, "commit", "-qm", "rm/mv")
    rc = m.main(["--repo-root", str(root)], fetch=_fake(base, _head_sha(root), pr()))
    cap = capsys.readouterr()
    assert rc == 0 and "blob.bin" in cap.out and "deleted (info only)" in cap.out


def test_main_attribute_semantics_come_from_git_check_attr(repo):
    """`/gen` is root-anchored and `dist/` matches no files in git; our glob code must not decide."""
    root, base = repo
    (root / ".gitattributes").write_text("/top linguist-generated=true\ndist/ linguist-generated=true\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "attrs")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    st = m.attr_state(root, sha, ["top", "a/top", "dist/a.py"])
    assert m._generated(st["top"])
    assert not m._generated(st["a/top"])
    assert not m._generated(st["dist/a.py"])


def test_check_attr_honours_unset_and_last_match(repo):
    root, base = repo
    (root / ".gitattributes").write_text("a/** linguist-generated=true\na/keep/** -linguist-generated\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "attrs")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    st = m.attr_state(root, sha, ["a/x.ts", "a/keep/y.ts"])
    assert m._generated(st["a/x.ts"]) and not m._generated(st["a/keep/y.ts"])


def test_main_rule_ids_come_from_head_constitution_as_data(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    _git(root, "checkout", "-qb", "feat")
    c = root / "CONSTITUTION.md"
    c.write_text(c.read_text(encoding="utf-8") + "\n**C-98.1** New rule added by this PR.\n",
                 encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "head")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    _git(root, "checkout", "-q", "main")  # the gate's worktree is BASE; head is only data
    p = pr(body="Closes #1\nSee C-98.1")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, p)) == 0
    p = pr(body="Closes #1\nSee C-98.2")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, head, p)) == 1


def test_api_pagination_fails_closed_at_page_limit(monkeypatch):
    import io
    import json as j

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(m.urllib.request, "urlopen", lambda req, timeout: R(j.dumps([{}] * 100).encode()))
    with pytest.raises(m.ConfigError, match="failing closed"):
        m.make_api_fetch("o/r", "t")("/issues/1/events")


def test_strip_markup_unclosed_and_indented_blocks():
    assert codes(run(pr(body="    Closes #1"))[0]) == ["PR-BODY-001"]
    assert codes(run(pr(body="~~~\nCloses #1\n~~~"))[0]) == ["PR-BODY-001"]
    assert codes(run(pr(body="<!-- hidden\nCloses #1"))[0]) == ["PR-BODY-001"]
    assert run(pr(body="text\n\nCloses #1\n"))[0] == []


def test_main_attribute_diff_is_against_merge_base_not_base_tip(repo, monkeypatch, capsys):
    root, old_base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    _git(root, "checkout", "-qb", "feat")
    (root / "src").mkdir()
    (root / "src/a.py").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "head")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    _git(root, "checkout", "-q", "main")  # main then edits .gitattributes after the branch point
    (root / ".gitattributes").write_text("gen/** linguist-generated=true\nnew/** linguist-generated=true\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "main moved")
    new_base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    assert m.main(["--repo-root", str(root)], fetch=_fake(new_base, head, pr())) == 0
    assert "PR-SIZE-002" not in capsys.readouterr().err


def test_so_under_generated_python_package_still_needs_approval():
    # generated in base but NOT declared binary there (ws/_generated/** has no -diff)
    p = "services/api/candleviewer/ws/_generated/x.cpython-313-x86_64-linux-gnu.so"
    r = rows(("5", "0", p))
    st = {p: ("set", "unspecified", "unspecified")}
    errs, _ = m.check(pr(), r, st, st, ATTRS, ATTRS, CL, DECLARED, RR.RULE_ID_RE,
                      binary_paths=frozenset({p}), binary_sizes={p: "10"})
    assert codes(errs) == ["PR-SIZE-003"]


def test_main_nul_so_under_ws_generated_fails_and_protocol_regen_passes(repo, monkeypatch, capsys):
    root, _ = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    (root / ".gitignore").write_text("__pycache__/\n")
    (root / ".gitattributes").write_text(
        "services/api/candleviewer/ws/_generated/** linguist-generated=true\n")
    pkg = root / "packages/protocol"
    pkg.mkdir(parents=True)
    (pkg / ".gitattributes").write_text("src/generated/** linguist-generated=true\n"
                                        "src/generated/** -diff\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "attrs")
    base = _head_sha(root)
    _git(root, "checkout", "-qb", "feat")
    so = root / "services/api/candleviewer/ws/_generated/m.cpython-313-x86_64-linux-gnu.so"
    so.parent.mkdir(parents=True)
    so.write_bytes(b"\x7fELF\0\0" * 20)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "so")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, _head_sha(root), pr())) == 1
    assert "PR-SIZE-003" in capsys.readouterr().err
    _git(root, "checkout", "-q", "main")
    _git(root, "checkout", "-qb", "regen")
    (pkg / "src/generated").mkdir(parents=True)
    (pkg / "src/generated/index.ts").write_text("export {};\n" * 500)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "regen")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, _head_sha(root), pr())) == 0


def test_text_loc_counts_plusplus_content_lines_after_hunk_header():
    patch = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -0,0 +1,3 @@\n+++0\n+--1\n+ok\n"
    assert m.text_loc(patch) == 3


def test_literal_pathspecs_recount_for_magic_names(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    _git(root, "checkout", "-qb", "feat")
    (root / ":!x").write_bytes(b"a\0\n" * 900)
    (root / "other.txt").write_text("1\n" * 3)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "magic")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, _head_sha(root), pr())) == 1
    err = capsys.readouterr().err
    assert "PR-SIZE-001" in err and "903 changed LOC" in err


def test_image_name_with_foreign_content_is_not_allowlisted(repo, monkeypatch, capsys):
    root, base = repo
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("PR_NUMBER", "7")
    _git(root, "checkout", "-qb", "feat")
    (root / "docs").mkdir()
    (root / "docs/a.png").write_bytes(b"not a png\0\n" * 900)
    (root / "docs/real.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "png")
    assert m.main(["--repo-root", str(root)], fetch=_fake(base, _head_sha(root), pr())) == 1
    err = capsys.readouterr().err
    assert "PR-SIZE-003" in err and "docs/a.png" in err and "real.png" not in err


def test_allowlist_regex_uses_fullmatch_not_trailing_newline():
    assert not m.BINARY_OK_RE.fullmatch("a.png\n")
    assert m.BINARY_OK_RE.fullmatch("docs/a.PNG")


def test_any_non_comment_gitattributes_change_triggers_size_002():
    base = "[attr]gen linguist-generated=true\n"
    errs, _ = run(r=rows(("1", "0", ".gitattributes")), base=base, head=base + "svc/** gen\n")
    assert codes(errs) == ["PR-SIZE-002"]


def test_codeowners_is_a_gate_file():
    assert ".github/CODEOWNERS" in m.GATE_FILES


def test_deleted_binary_is_info_only():
    errs, warns = bin_run(["data/old.bin"])
    assert errs == [] and "deleted (info only)" in warns[0]


def test_approvers_limited_to_owners_of_triggering_paths():
    owners = "/services/ @bob\n/docs/ @alice\n"
    big = rows(("900", "0", "services/a.py"), ("1", "0", "docs/x.md"))
    kw = dict(base_codeowners=owners, repo_owner="")
    # size trigger spans every changed path, so no single non-owner-of-all may approve
    errs, _ = run(pr(labels=[m.LABEL]), big, events=labeled("alice"), comments=comment("alice"), **kw)
    assert codes(errs) == ["PR-SIZE-004"]
    one = rows(("900", "0", "services/a.py"))
    errs, _ = run(pr(labels=[m.LABEL]), one, events=labeled("bob"), comments=comment("bob"), **kw)
    assert errs == []
