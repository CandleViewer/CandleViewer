"""Set the Project #3 Status (and optionally comment) for a ticket key. Usage:
   python docs/plan/backlog/_tools/set_status.py E02-T01 "In Progress" ["comment text"]
Statuses: Backlog, Ready, In Progress, In Review, In Test, Blocked, Done."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_board as pb  # noqa: E402

def main():
    key, status = sys.argv[1], sys.argv[2]
    led = json.load(open(pb.LEDGER_PATH, encoding="utf-8"))
    item = led[key]["item_id"]; num = led[key]["number"]
    opt = pb.STATUS_OPTS[status]
    q = ('mutation{updateProjectV2ItemFieldValue(input:{projectId:"%s",itemId:"%s",fieldId:"%s",'
         'value:{singleSelectOptionId:"%s"}}){projectV2Item{id}}}') % (pb.PROJECT_ID, item, pb.FIELD_IDS["Status"], opt)
    r = subprocess.run([pb.GH, "api", "graphql", "-f", "query=" + q], capture_output=True, text=True)
    if r.returncode: raise SystemExit(r.stderr[:300])
    if len(sys.argv) > 3:
        subprocess.run([pb.GH, "issue", "comment", str(num), "-R", pb.REPO, "--body", sys.argv[3]], check=True)
    print(f"{key} (#{num}) -> {status}")

if __name__ == "__main__":
    main()
