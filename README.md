# .github

Organization-level defaults for `ekwi-tech`. Everything here is world-readable, Actions logs
included; anything added should be written on that basis.

## Contents

| Path | Purpose |
| --- | --- |
| `.github/ISSUE_TEMPLATE/` | Issue forms offered to repositories that do not define their own |
| `.github/workflows/` | Scheduled maintenance, and reusable workflows other repositories call |
| `tools/` | Maintenance scripts, each documented in its own module docstring |

GitHub falls back here only for what a repository does not provide itself; nothing in this
repository overrides a file a repository ships. Workflows are the exception — they are never
inherited, so a repository that wants one calls it explicitly.

## Conventions

- Interface text is English: templates, field names, labels, workflow names. Issues are written in
  the language of whoever files them.
- Commit messages and pull request titles are English; pull request bodies are French.
- A label carries the domain of a change. Type, priority, client and status are fields, not labels —
  a label that restates one of them is a second copy that drifts.

## Tools

Read-only by default; writing takes an explicit flag and an explicit scope. Each script states its
usage and its exit codes at the top of the file, which is the reference — this page does not repeat
them, so it cannot fall out of step with them.
