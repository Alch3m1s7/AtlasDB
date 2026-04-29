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