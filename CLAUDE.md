# AtlasDB / KeepAU Claude Code Instructions

## Project Purpose

AtlasDB is a Python + PostgreSQL system for Amazon reseller intelligence and operations.

Primary goals:
- Collect, normalize, and store Amazon marketplace product and seller data.
- Support AtlasDB / Nexus querying across marketplaces.
- Build reliable ingestion from Amazon Seller SP-API, SellerSnap reports/API, Google Sheets, Gmail attachments, and future controlled imports.
- Prioritize secure, low-cost, deterministic automation over repeated manual AI work.

This project is used for an Amazon reseller business, so assume all data is commercially sensitive.

---

## Operating Priorities

Optimize in this order:

1. Security
2. Correctness
3. Simplicity
4. Cost efficiency
5. Scalability
6. Maintainability
7. Speed

Prefer:
- APIs over browser automation
- Python scripts over repeated AI execution
- deterministic code over probabilistic AI where reliability matters
- small MVP changes over large rewrites
- explicit logs over silent failures

Do not overengineer unless volume, security, or reliability clearly requires it.

---

## Token & Agent Efficiency Rules

Claude must minimise token usage and avoid unnecessary expensive reasoning.

Before reading large files, Claude must first use cheap discovery methods:

1. Use Grep/Glob/List to identify relevant files, functions, classes, imports, or call sites.
2. Read only the smallest relevant file section or line range.
3. Avoid reading entire large files unless explicitly necessary.
4. Avoid spawning subagents for simple lookup, grep, summarisation, or single-file questions.
5. Use subagents only for genuinely complex tasks such as security review, multi-file debugging, architecture review, test strategy, or independent second opinion.
6. For simple questions, answer using direct tool calls and concise reasoning.
7. If a task may exceed roughly 10k tokens, pause and state the cheaper plan before proceeding.
8. Prefer deterministic commands over AI interpretation where possible.

Examples:

- "What functions exist in src/main.py?"
  - Do: grep for `^def `, `^class `, and maybe argparse/command branches.
  - Do not: read the full file or launch an Explore subagent.

- "What does function X do?"
  - Do: locate the function, read only that function and nearby helpers.
  - Do not: summarise the whole file.

- "Find where report generation happens"
  - Do: grep for report names, command names, and relevant function calls.
  - Do not: scan the whole repository with a subagent first.

- "Refactor this module"
  - Do: inspect structure first, propose a plan, then edit incrementally.
  - Do not: rewrite large files without tests and a rollback plan.

Default approach:
Cheap search → narrow read → plan → minimal edit → test → summary.

Cost efficiency must not override correctness, security, or task completion. If cheap discovery fails, if the task is security-sensitive, or if the solution requires deeper reasoning, escalate to a stronger model, subagent, or broader file review and briefly explain why.

Do not stay stuck in cheap mode. After 2 failed attempts using cheap search or narrow reads, escalate: read broader context, use a specialised subagent, or ask for permission to use a more capable model/workflow.

---

## Security Rules

Never print, commit, or expose secrets.

Secrets include:
- Amazon LWA client secret
- AWS access keys
- refresh tokens
- database passwords
- Google API credentials
- SellerSnap credentials
- cookies/session tokens

Use `.env` for local secrets.
Ensure `.env` is listed in `.gitignore`.

Before making changes involving credentials, external APIs, Google Workspace, browser automation, or database writes, explicitly identify:
- trust boundary
- credentials used
- blast radius if compromised
- safer alternative if available

Never add real credentials to test files, examples, markdown, logs, or commits.

---

## Python Environment

This is a Windows PowerShell project.

Assume the project path is:

`C:\DevProjects-b\AtlasDB`

Use the project virtual environment:

`.venv`

Do not recreate `.venv` unless it is missing or broken.

Normal activation command:

```powershell
.venv\Scripts\activate
