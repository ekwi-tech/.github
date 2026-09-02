#!/usr/bin/env python3
"""Report drift between the client roster and the organization's `Client` issue field.

A client exists once its `instance-<name>` repository does. The `Client` field is a copy, kept by
hand in the organization settings — this script only says what drifted, on names and order.

    python3 tools/check_clients.py

Exit codes: 0 in step, 1 drift found, 2 the run could not be trusted.

Why it never writes: `updateIssueField` takes options without an id, so it cannot amend a set — every
divergent one is rejected, and the only accepted rewrite replaces the whole set, erasing the values it
carried. Detection is the only safe half.

Client names are withheld from CI output: this repository is public, and so are its Actions logs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import NoReturn

ORG, FIELD, REPO_LIMIT, FIELD_LIMIT = "ekwi-tech", "Client", 300, 50
PUBLIC_LOG = os.environ.get("GITHUB_ACTIONS") == "true"

# One client per instance repository, name verbatim — work is tracked per instance, so two
# instances of one group stay two entries. `cross-cutting` and `internal` are reserved by TRAILING
# below: an instance repository of either name would yield a duplicate the field refuses.
NOT_CLIENTS = {"skeleton", "ekwi-demo", "ekwi-sandbox", "ekwi-tech", "cross-cutting", "internal"}
# A client exists before its repository does; the roster, derived from repositories, cannot know it
# yet. Naming it in the title is the honest answer — inventing an option would be a guess.
TRAILING = ["cross-cutting", "internal", "to be created"]


def die(message: str) -> NoReturn:
    """Exit 2, never 1: a scheduled run must tell a broken tool from a real drift."""
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(2)


def gh(*args: str) -> str:
    """Any gh failure is fatal: a partial read would report removals that never happened.

    stderr only, never stdout: a failed graphql call still prints the response body, client names
    included, and this repository's Actions logs are public.
    """
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        die(f"gh {' '.join(args)}\n{done.stderr.strip()}")
    return done.stdout


def fleet() -> list[str]:
    page = json.loads(gh("repo", "list", ORG, "--limit", str(REPO_LIMIT), "--json", "name,isArchived"))
    # Checked on the raw page: a full page may be truncated, and a short roster would report a
    # phantom removal.
    if len(page) >= REPO_LIMIT:
        die(f"{REPO_LIMIT} repositories returned — the listing may be truncated, raise REPO_LIMIT")
    repos = [r["name"] for r in page if not r["isArchived"]]
    clients = sorted(n.removeprefix("instance-") for n in repos if n.startswith("instance-"))
    clients = [c for c in clients if c not in NOT_CLIENTS]
    if not clients:
        die("no instance-* repository found — refusing to report the whole roster as removed")
    return clients + TRAILING


def field_options() -> list[str]:
    query = f"""{{organization(login:{json.dumps(ORG)}){{issueFields(first:{FIELD_LIMIT}){{
      totalCount nodes{{... on IssueFieldSingleSelect{{name options{{name}}}}}}}}}}}}"""
    fields = json.loads(gh("api", "graphql", "-f", "query=" + query))["data"]["organization"]["issueFields"]
    # Past the page, a missing field reads as a missing field rather than as an unread one.
    if fields["totalCount"] > FIELD_LIMIT:
        die(f"{fields['totalCount']} issue fields on the organization — raise FIELD_LIMIT")
    for node in fields["nodes"]:
        if node.get("name") == FIELD:
            return [o["name"] for o in node["options"]]
    die(f"no single-select issue field named {FIELD!r} on the organization")


def main() -> int:
    # The tool used to write, and --apply is still in muscle memory; silently checking would look
    # like a successful apply.
    if len(sys.argv) > 1:
        die("this tool takes no argument — it reports drift and never writes")

    wanted, current = fleet(), field_options()
    print(f"{len(wanted) - len(TRAILING)} clients derived from the fleet")

    if wanted == current:
        print(f"✓ the {FIELD} field matches the fleet")
        return 0

    missing = [c for c in wanted if c not in current]
    extra = [c for c in current if c not in wanted]
    if not (missing or extra):
        order = "" if PUBLIC_LOG else f" — expected {', '.join(wanted)}"
        print(f"  ~ {FIELD} field: same names, wrong order{order}")
    elif PUBLIC_LOG:
        # A client name in a public log is the very exposure the roster was moved off this repo to end.
        print(f"  ~ {FIELD} field: {len(missing)} missing, {len(extra)} unknown "
              f"— run the check locally for names")
    else:
        print(f"  ~ {FIELD} field: missing {', '.join(missing) or 'nothing'} / "
              f"unknown {', '.join(extra) or 'nothing'}")
    print(f"\n✗ drift found — fix it under {ORG} settings, Issues > Issue fields > {FIELD}",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # exit 1 means drift; a crash must never say that
        print(f"✗ unexpected failure: {exc!r}", file=sys.stderr)
        sys.exit(2)
