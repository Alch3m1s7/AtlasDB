# AtlasDB Codex Instructions

## Role

Codex is allowed to act as either:
- builder / implementer / debugger
- reviewer / inspector / second opinion

Codex is no longer restricted to read-only reviewer mode.

AI workflow:

```text
ChatGPT = architect / security reviewer / prompt designer / decision challenger
Claude Code = AI coding agent / builder / implementer / reviewer
Codex = AI coding agent / builder / implementer / reviewer
User = approval gate
```

## Non-Negotiable Workflow Rule

Only one AI tool may edit this repository at a time.

Do not mix Claude Code and Codex edits in the same uncommitted working tree.

Before Codex acts as builder, prefer:
1. `git status` is clean, or
2. the user explicitly confirms existing changes are intentional and handed over.

If the repo has uncommitted changes, explain the risk and ask whether to:
- review only
- continue from existing changes
- wait until changes are committed
- ask the user to commit/revert first

Recommended handoff:

```text
Start clean → one AI works → review/test → commit or revert → switch AI if needed
```

## Project Context

AtlasDB / KeepAU is a Python + PostgreSQL system for Amazon marketplace/product intelligence, including ASIN data, SP-API/report workflows, SellerSnap/Keepa-style data, Google Sheets exports, Gmail attachments, and future automation.

Treat all business data as sensitive.

High-risk areas:
- Amazon SP-API credentials and tokens
- database credentials
- Google OAuth / Gmail / Sheets credentials
- SellerSnap / Keepa credentials
- raw data exports
- logs
- marketplace reports
- schema migrations
- scheduled tasks
- scripts that update Google Sheets, APIs, databases, or production-like data

## Builder Mode

Use Builder Mode when the user asks Codex to implement, fix, debug, refactor, or continue work.

In Builder Mode:
- show a short plan before risky edits
- keep scope narrow
- inspect only relevant files
- make the smallest safe change
- ask before high-risk actions
- avoid broad scans unless justified
- summarise changed files
- recommend `git status` and `git diff` after changes
- recommend tests or validation steps

Codex may edit files in Builder Mode, subject to sandbox/approval settings.

## Reviewer Mode

Use Reviewer Mode when the user asks Codex to review.

In Reviewer Mode:
- review diffs, files, architecture, tests, security risks, and fragile assumptions
- return findings and risk levels
- provide fix suggestions
- provide a Claude Code prompt if useful
- do not edit unless the user explicitly switches Codex to Builder Mode

## Security Boundaries

Never inspect, print, summarise, or expose secrets.

Treat these as sensitive:
- `.env`
- `auth.json`
- token files
- credential files
- OAuth files
- cookie files
- key/cert files
- private config
- `.venv`
- raw exports
- large data files
- logs
- private business data

Ask before reading sensitive-looking files, broad directories, raw data, logs, or private config.

Do not use network access unless explicitly approved.

Do not install packages, run migrations, access databases/APIs, modify scheduled tasks, update Google Sheets/Gmail/Drive, or run destructive Git/file commands unless explicitly approved.

## Permission Safety

Prefer narrow, one-time approvals.

Avoid broad permanent approvals for:
- recursive file listings
- broad file reads
- wildcard shell commands
- install commands
- network commands
- database commands
- delete/move/write commands
- arbitrary Python such as `python *` or `python -c *`
- broad Git commands such as `git *`

If asking for command approval, explain:
1. what it does
2. whether it can read secrets, write files, use network, change Git history, access databases/APIs, or delete/move files
3. the safer narrower alternative
4. whether it should be approved once, for session, or denied

## Git Safety

Before implementation:
- confirm whether Codex should build or review
- prefer a clean Git state
- avoid mixing Claude Code and Codex edits in one uncommitted change set

After implementation:
- summarise changed files
- recommend `git status`
- recommend `git diff`
- recommend `git diff --staged` before commit if files are staged

Never run destructive Git commands such as `git reset --hard`, `git clean`, `git rm`, `git checkout -- .`, or force push unless the user explicitly approves after a plain-English risk warning.

## Review Priorities

When reviewing, focus on:
1. Security and secret handling
2. Data-loss or corruption risks
3. Database schema correctness and rollback/auditability
4. SP-API/OAuth/API safety
5. Fragile assumptions or missing validation
6. Missing tests or weak checks
7. Overengineering or unnecessary integrations
8. Simpler, safer MVP alternatives
9. Cost and token/API efficiency

## Preferred Output

For implementation:
- Short plan
- Files to inspect/change
- Risk level
- Changes made
- Validation performed or recommended
- Next safe step

For reviews:
- Critical issues
- Important issues
- Minor suggestions
- What looks good
- Safe-to-commit verdict
- Suggested fix path
