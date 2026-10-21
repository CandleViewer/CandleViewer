"""Orchestrator merge step (runs in the main session, never in a sub-agent sandbox).
Usage: python docs/plan/backlog/_tools/merge_ready.py <PR> <KEY> [--design]
Gates, in order: latest verdicts APPROVE (reviews+comments, after last commit) → CI checks pass →
verify_pr.py PASS → [design: Penpot link or page name + page id, and embedded PNG] → squash-merge → In Test.
Exit 0 merged, 1 gate failed (reason printed), 2 error."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import publish_board as pb
GH = pb.GH; REPO = pb.REPO
pr, key = sys.argv[1], sys.argv[2]; design = "--design" in sys.argv
def gh(*a):
    r = subprocess.run([GH, *a], capture_output=True, text=True, encoding="utf-8", errors="replace"); return r
def fail(msg): print(f"PR #{pr} {key}: GATE FAIL — {msg}"); sys.exit(1)
d = json.loads(gh("pr", "view", pr, "--json", "state,isDraft,mergeable,commits,reviews,comments,body,statusCheckRollup").stdout)
if d["state"] != "OPEN": fail(f"state={d['state']}")
if d["isDraft"]: fail("draft")
last = max(c["committedDate"] for c in d["commits"])
items = [(r["submittedAt"], r["body"]) for r in d["reviews"]] + [(c["createdAt"], c["body"]) for c in d["comments"]]
verdicts = sorted([(t, b) for t, b in items if re.search(r"VERDICT:\s*(APPROVE|REQUEST_CHANGES)", b or "", re.I)])
after = [(t, b) for t, b in verdicts if t > last]
if not after: fail(f"no VERDICT after last commit {last}")
if any(re.search(r"VERDICT:\s*REQUEST_CHANGES", b, re.I) and t == after[-1][0] for t, b in after): fail("latest verdict is REQUEST_CHANGES")
if not any(re.search(r"VERDICT:\s*APPROVE", b, re.I) for _, b in after): fail("no APPROVE after last commit")
rollup = d.get("statusCheckRollup") or []
def _name(c): return c.get("name") or c.get("context", "?")
def _failed(c): return c.get("conclusion") not in (None, "SUCCESS", "NEUTRAL", "SKIPPED") or c.get("state") in ("FAILURE", "ERROR")
# Only checks our workflows own gate the merge (C-9.1: the required-check list is resolved
# by `ci-required`; `governance` is its own required workflow). GitHub code-scanning
# "echo" check runs ("Semgrep OSS", "CodeQL", "Bandit" — SARIF uploads with no workflowName)
# re-surface the very alerts the `security/*` lanes already evaluated via security_gate.py
# and are not in C-9.1; they are reported but never block.
own = [c for c in rollup if c.get("workflowName")]
echo_bad = [c for c in rollup if not c.get("workflowName") and _failed(c)]
bad = [c for c in own if _failed(c)]
if bad: fail("failing checks: " + ", ".join(_name(c) for c in bad))
if not any(_name(c) == "ci-required" and c.get("conclusion") == "SUCCESS" for c in own): fail("ci-required not SUCCESS")
if echo_bad: print("note: non-gating code-scanning echo check(s) red (not in C-9.1): " + ", ".join(_name(c) for c in echo_bad))
r = subprocess.run([sys.executable, os.path.join(HERE, "verify_pr.py"), pr], capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:])
if r.returncode: fail("verify_pr FAIL")
if design:
    from done_gate import has_penpot_reference  # only design merges need it

    body = d["body"] or ""
    if not has_penpot_reference(body) or not re.search(r"!\[[^\]]*\]\([^)]*\.png", body): fail("design evidence missing (Penpot workspace link or page name + page id, and/or embedded PNG)")
if d["mergeable"] == "CONFLICTING": fail("CONFLICTING — needs rebase")
m = gh("pr", "merge", pr, "--squash", "--delete-branch")
if m.returncode: fail("merge: " + (m.stderr or m.stdout).strip()[-200:])
sha = json.loads(gh("pr", "view", pr, "--json", "mergeCommit").stdout).get("mergeCommit", {}).get("oid", "")[:7]
subprocess.run([sys.executable, os.path.join(HERE, "set_status.py"), key, "In Test", f"merged {sha}; reviews APPROVE; CI green; verify_pr PASS; QA verification pending"], check=False)
print(f"PR #{pr} {key}: MERGED {sha}")
