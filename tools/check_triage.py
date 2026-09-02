#!/usr/bin/env python3
"""Report triage that has stalled: what entered recently and is still waiting to be qualified.

`To analyze` says « we do not yet know what this is », `Backlog` says « we know, and not now ». The
first is only a real column if it empties at the pace of triage; left alone it becomes a second
backlog. This is the guard for that pace.

    python3 tools/check_triage.py

Exit codes: 0 in step, 1 triage has stalled, 2 the run could not be trusted.

Why it does not simply flag the oldest: the queue holds a historical debt — a median past a year —
that no cadence can be blamed for. An alarm that can never go green is ignored, so the inflow decides
the exit code, and the debt only has to stop growing. An item with no Status at all is a third
finding: it is not in the queue, and it is not triaged either.

Repository names and issue numbers stay out of CI output: they belong to private repositories and
these logs are public.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from typing import NoReturn

PROJECT_ID = "PVT_kwDOCLiMnc4AqDKU"          # ekwi-tech/projects/2 — The Yard
QUEUE = "To analyze"
GRACE_DAYS = 14                              # a fortnight to qualify what just arrived
RECENT_DAYS = 90                             # past that, it is debt to plan, not a cadence to hold
# Without it, ignoring a card long enough silences it. Raising the ceiling is a decision to stop
# paying, and reads as one in a diff.
DEBT_CEILING = 116
PUBLIC_LOG = os.environ.get("GITHUB_ACTIONS") == "true"

STATUS_OPTIONS = """{ node(id: "%s") { ... on ProjectV2 {
  field(name: "Status") { ... on ProjectV2SingleSelectField { options { name } } } } } }""" % PROJECT_ID

ITEMS = """query($c: String) {
  node(id: "%s") { ... on ProjectV2 { items(first: 100, after: $c) {
    totalCount
    pageInfo { hasNextPage endCursor }
    nodes {
      type
      content { ... on Issue { number createdAt repository { name } } }
      status: fieldValueByName(name: "Status") {
        ... on ProjectV2ItemFieldSingleSelectValue { name } } } } } }
}""" % PROJECT_ID


def die(message: str) -> NoReturn:
    """Exit 2, never 1: a scheduled run must tell a broken tool from a real finding."""
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(2)


def gh(*args: str) -> str:
    """Any gh failure is fatal: a partial read would understate the queue.

    stderr only, never stdout: a failed graphql call still prints the response body, repository
    names included, and this repository's Actions logs are public.
    """
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        die(f"gh {' '.join(args)}\n{done.stderr.strip()}")
    return done.stdout


def queue() -> tuple[list[tuple[str, int, date]], int, int]:
    # A renamed option makes every comparison below false, and an empty queue reads as a clean
    # triage.
    field = json.loads(gh("api", "graphql", "-f", "query=" + STATUS_OPTIONS))["data"]["node"]["field"]
    if not field or QUEUE not in [o["name"] for o in field["options"]]:
        die(f"no {QUEUE!r} option on the Status field — refusing to report an empty queue")

    cursor, waiting, seen, triageable, statused, total = None, [], 0, 0, 0, None
    while True:
        args = ["api", "graphql", "-f", "query=" + ITEMS] + (["-f", f"c={cursor}"] if cursor else [])
        page = json.loads(gh(*args))["data"]["node"]["items"]
        total = page["totalCount"] if total is None else total
        for item in page["nodes"]:
            seen += 1
            # Triage never applies to a pull request: it carries neither client nor priority, so
            # counting one as unstatused would keep the check red over an item it exempts.
            if item["type"] == "PULL_REQUEST":
                continue
            triageable += 1
            status = (item["status"] or {}).get("name")
            if status:
                statused += 1
            if status != QUEUE:
                continue
            # A draft does need triage, but its age is off the path this query reads.
            if item["type"] == "DRAFT_ISSUE":
                die("a draft issue sits in the queue — convert it or move it out")
            # An issue the token cannot read comes back empty; counting it as absent would
            # understate the queue.
            content = item["content"]
            if not content:
                die("an item in the queue returned no content — the read is partial")
            waiting.append((content["repository"]["name"], content["number"],
                            date.fromisoformat(content["createdAt"][:10])))
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    if not seen:
        die("the project returned no item at all — refusing to call that a clean triage")
    # A short page reads exactly like a short queue, and the board says how many it holds.
    if seen != total:
        die(f"read {seen} where the board holds {total} items — refusing to measure a queue on a "
            f"count that does not add up")
    # An unread field is not an empty column: a token can list every item and still see no value.
    # Blind everywhere is a broken read; blind in places is a finding.
    if triageable and not statused:
        die(f"none of the {triageable} triageable items carries a Status — the field reads as "
            f"empty, refusing to call that a clean triage")
    return waiting, seen, triageable - statused


def main() -> int:
    if len(sys.argv) > 1:
        die("this tool takes no argument — it reports and never writes")

    today = date.today()
    waiting, seen, unstatused = queue()
    overdue = [w for w in waiting
               if today - timedelta(days=RECENT_DAYS) <= w[2] <= today - timedelta(days=GRACE_DAYS)]
    debt = [w for w in waiting if w[2] < today - timedelta(days=RECENT_DAYS)]

    print(f"{len(waiting)} in {QUEUE}, of {seen} items on the board — {len(debt)} older than "
          f"{RECENT_DAYS} days, ceiling {DEBT_CEILING}")
    if not overdue and not unstatused and len(debt) <= DEBT_CEILING:
        print(f"✓ nothing recent has been waiting more than {GRACE_DAYS} days, and the debt holds")
        return 0

    if overdue and PUBLIC_LOG:
        print(f"  ~ {len(overdue)} opened in the last {RECENT_DAYS} days and untriaged "
              f"past {GRACE_DAYS} days — run the check locally for the list")
    elif overdue:
        oldest = sorted(overdue, key=lambda w: w[2])
        print(f"  ~ {len(overdue)} opened in the last {RECENT_DAYS} days and untriaged "
              f"past {GRACE_DAYS} days: "
              + ", ".join(f"{repo}#{number}" for repo, number, _ in oldest))
    if unstatused:
        print(f"  ~ {unstatused} without a Status — unread or never set, untriaged either way")
    if len(debt) > DEBT_CEILING:
        print(f"  ~ debt grew to {len(debt)}, past the {DEBT_CEILING} it was left at")
    print(f"\n✗ triage has fallen behind — qualify them: set a Status, or move them out of {QUEUE}",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                  # exit 1 means a finding; a crash must never say that
        print(f"✗ unexpected failure: {exc!r}", file=sys.stderr)
        sys.exit(2)
