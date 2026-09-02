#!/usr/bin/env python3
"""Align repository labels on the organization's domain set.

Labels carry the one axis nothing else does: the domain. Type, priority, client and status each have
a field of their own, so anything a label would restate about them is a duplicate that drifts.

It creates and repairs; it never deletes — removing a label strips it from every issue carrying
it, which is a decision, not a repair.

    python3 tools/align_labels.py                            # check the repositories that carry it
    python3 tools/align_labels.py --repos ekwi-core --apply   # writing needs an explicit scope

Naming a repository is how it joins: the sweep only checks those already carrying part of the set.

Exit codes: 0 aligned, 1 drift found, 2 the run could not be trusted.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from typing import NoReturn

ORG, REPO_LIMIT = "ekwi-tech", 300
# It names every repository it touches; this repository's Actions logs are public.
IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"

LABELS = {
    "CI/CD":            ("C06513", "Pipelines, gates, release automation"),
    "CleanCode":        ("5E8B05", "Readability or structure, no behaviour change"),
    "Doc":              ("0075CA", "Improvements or additions to documentation"),
    "HelpNeeded":       ("008672", "Needs a hand from someone else on the team"),
    "Parameters":       ("5319E7", "Parameters handling"),
    "Regression":       ("B60205", "Worked before, does not any more"),
    "Scripting":        ("FEF2C0", "Ships an upgrade script to run"),
    "StandBy":          ("D1B5FD", "Parked on purpose, no action expected for now"),
    "Testing":          ("1D76DB", "Test coverage or test tooling"),
    "ToDiscuss":        ("D876E3", "Further information is requested"),
    "Translation":      ("FBCA04", "Missing or wrong translation"),
    "UI/UX":            ("20B3D1", "Layout, interaction, visual behaviour"),
    "Wording":          ("C7DBD4", "Wording of user-facing text"),
}
# Everything the fleet carries outside this set is machine-owned — Dependabot's tags, the
# skeleton's `template_sync` — and recreated on the next run: reporting it is a permanent false
# positive.


def die(message: str) -> NoReturn:
    """Exit 2, never 1: a broken run must not read as an aligned fleet."""
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(2)


def gh(*args: str) -> str:
    """Any gh failure is fatal: a partial read would plan against a half-known repository."""
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        die(f"gh {' '.join(args)}\n{done.stderr.strip()}")
    return done.stdout


def repositories(only: list[str] | None) -> list[str]:
    page = json.loads(gh("repo", "list", ORG, "--limit", str(REPO_LIMIT), "--json", "name,isArchived"))
    # A full page is indistinguishable from a truncated one, and a short list would silently skip
    # repositories rather than report them.
    if len(page) >= REPO_LIMIT:
        die(f"{REPO_LIMIT} repositories returned — the listing may be truncated, raise REPO_LIMIT")
    active = [r["name"] for r in page if not r["isArchived"]]      # archived repos reject writes
    if only is None:
        return sorted(active)
    unknown = sorted(set(only) - set(active))
    if unknown:
        die(f"unknown or archived in {ORG}: {unknown}")
    return sorted(only)


def plan_for(repo: str, adopted_only: bool) -> list[tuple[str, str, dict[str, str]]] | None:
    """The steps to align one repository, or None when it has not adopted the set."""
    # One object per line: --paginate concatenates JSON arrays, which json.loads chokes on past
    # the first page.
    current = {held["name"]: held for held in (json.loads(line) for line in
               gh("api", f"repos/{ORG}/{repo}/labels", "--paginate", "--jq", ".[]").splitlines())}
    # A repository holding none of the set never joined, so it has not drifted. Sweeping all of them
    # would report work that policy forbids applying, and an alarm that cannot go green is not read.
    if adopted_only and not set(current) & set(LABELS):
        return None
    steps = []
    for name, (colour, description) in LABELS.items():
        held = current.get(name)
        if held is None:
            steps.append(("create", name, {"name": name, "color": colour,
                                           "description": description}))
        elif held["color"].lower() != colour.lower() or (held.get("description") or "") != description:
            steps.append(("update", name, {"color": colour, "description": description}))
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repos", nargs="+", metavar="NAME",
                        help="restrict the scope; default is every active repository")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()
    if IN_CI:
        die("this tool names every repository it touches — never run it in a public log")
    # Fleet-wide, this would recreate on 80 repositories the unused labels the set was trimmed
    # to avoid — not something one flag should trigger.
    if args.apply and not args.repos:
        die("--apply needs an explicit --repos")

    scope = repositories(args.repos)
    changes, adopted = 0, 0
    for repo in scope:
        steps = plan_for(repo, adopted_only=args.repos is None)
        if steps is None:
            continue
        adopted += 1
        if not steps:
            continue
        print(f"  {repo}")
        for action, name, payload in steps:
            print(f"      {action} {name}")
            changes += 1
            if not args.apply:
                continue
            # `UI/UX`: an unencoded slash would split the API path.
            path = f"repos/{ORG}/{repo}/labels" + (
                "" if action == "create" else "/" + urllib.parse.quote(name, safe=""))
            call = ["api", "-X", "POST" if action == "create" else "PATCH", path, "--silent"]
            for key, value in payload.items():
                call += ["-f", f"{key}={value}"]
            gh(*call)

    # At zero adopted every comparison above is vacuous: the sweep would report success while
    # watching nothing.
    if not adopted:
        die("no repository carries the domain set — refusing to call that in step")

    if not changes:
        print(f"✓ {adopted} of {len(scope)} repositories carry the domain set, all in step")
        return 0
    if args.apply:
        print(f"\n✓ {changes} changes applied")
        return 0
    print(f"\n✗ {changes} changes pending — rerun with --apply", file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # exit 1 means drift; a crash must never say that
        print(f"✗ unexpected failure: {exc!r}", file=sys.stderr)
        sys.exit(2)
