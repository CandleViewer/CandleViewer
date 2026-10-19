"""Dump Project #3 items (issue number, title, status, sprint, assignees, labels, state) to
_board_snapshot.json for autonomous planning. Read-only. Usage: python board_snapshot.py"""

import json
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import publish_board as pb  # sibling tool; sys.path set above

Q = """{node(id:"%s"){... on ProjectV2{items(first:100%s){pageInfo{hasNextPage endCursor} nodes{id
 status:fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}}
 sprint:fieldValueByName(name:"Sprint"){... on ProjectV2ItemFieldSingleSelectValue{name}}
 content{... on Issue{number title state url assignees(first:5){nodes{login}} labels(first:20){nodes{name}}}}}}}}}"""


def main() -> None:
    out: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        after = f', after:"{cursor}"' if cursor else ""
        r = subprocess.run(
            [pb.GH, "api", "graphql", "-f", "query=" + (Q % (pb.PROJECT_ID, after))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if r.returncode:
            raise SystemExit(r.stderr[:500])
        d = json.loads(r.stdout)["data"]["node"]["items"]
        for n in d["nodes"]:
            c = n.get("content") or {}
            if not c:
                continue
            out.append(
                {
                    "item_id": n["id"],
                    "number": c["number"],
                    "title": c["title"],
                    "state": c["state"],
                    "status": (n["status"] or {}).get("name"),
                    "sprint": (n["sprint"] or {}).get("name"),
                    "assignees": [a["login"] for a in c["assignees"]["nodes"]],
                    "labels": [lb["name"] for lb in c["labels"]["nodes"]],
                }
            )
        if not d["pageInfo"]["hasNextPage"]:
            break
        cursor = d["pageInfo"]["endCursor"]
    path = os.path.join(HERE, "_board_snapshot.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(len(out), "items ->", path)
    print("by status:", dict(Counter(i["status"] for i in out)))


if __name__ == "__main__":
    main()
