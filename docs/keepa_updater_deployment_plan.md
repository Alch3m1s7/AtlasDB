# Keepa Updater Deployment Plan

**Date:** 2026-05-04
**Status:** Draft — awaiting review before any deployment action
**Scope:** `update-keepa-sheets` command only. No SP-API, database, or SellerSnap components.

---

## 1. Recommendation

**Deploy to a Hostinger KVM 2 VPS (Ubuntu 24.04 LTS) running the updater via systemd timer.**

Start with a single marketplace (CA) at `--max-asins 50`, running hourly. Add additional marketplaces one at a time after confirming the first is stable.

The Hostinger KVM 2 is chosen over the cheaper Hetzner CX22 because this VPS will eventually serve as the broader AtlasDB automation box — n8n, scheduled ingestion, and other future workloads. The extra RAM (8 GB vs 4 GB) and disk (100 GB NVMe vs 40 GB SSD) eliminate the most likely reason to migrate servers within 12 months. The Keepa updater itself uses negligible resources either way.

---

## 2. Why This Option

The VPS wins over the alternatives for this specific workload because:

- **No code changes required.** The checkpoint file, log files, and OAuth token all work natively on a persistent Linux filesystem. Cloud Run would require moving checkpoint state to Cloud Storage (a non-trivial code change).
- **OAuth auto-refresh works.** The existing `google_sheets_client.py` uses InstalledAppFlow with a `refresh_token`. Copied once to the VPS, the token refreshes automatically on every run without any browser interaction, indefinitely, as long as runs happen at least once every 6 months. No service account migration required for MVP.
- **Always on.** Unlike the laptop, the VPS runs 24/7. The effective refresh cadence becomes what the token math actually allows, not what your screen-on time allows.
- **Logs are inspectable.** SSH in, `tail -f` the log, done.
- **Lowest new-concept count.** VPS + cron/systemd is a solved, well-documented pattern. Cloud Run requires Docker, GCP IAM, Secret Manager, Cloud Storage, and Cloud Run Jobs — five new systems for a job that runs 24 lines of Python logic.

### Why Hostinger KVM 2 over Hetzner CX22

| | Hostinger KVM 2 | Hetzner CX22 |
|---|---|---|
| RAM | 8 GB | 4 GB |
| Disk | 100 GB NVMe | 40 GB SSD |
| vCPU | 2 | 2 |
| Price | ~$8–9/month | ~€4–5/month |
| n8n headroom | Comfortable | Marginal (n8n + PostgreSQL + Docker will strain 4 GB) |
| Beginner panel | Yes | Minimal |

Hetzner CX22 is the right choice if the only goal is running the Keepa updater indefinitely at minimum cost. Hostinger KVM 2 is the right choice when this VPS will also host n8n, a local PostgreSQL instance, or other AtlasDB automation — avoiding a server migration within 6–12 months is worth the ~$4/month premium.

### Security note

Hostinger KVM 2 is not inherently more secure than any other VPS. Security on any platform depends entirely on what you configure:

- SSH key-only authentication (disable password auth)
- UFW or nftables firewall (allow only SSH + required outbound ports)
- Non-root service user with least-privilege access
- `chmod 600` on all secrets files and the `.env` file
- Limiting which credentials are deployed — only the Keepa API key and the Google OAuth token for this MVP; nothing else

A stock Hostinger VPS with default settings is no more secure than a stock Hetzner VPS with default settings. The hardening steps matter more than the provider.

---

## 3. Option Comparison

| Criterion | Hostinger KVM 2 ✓ recommended | Hetzner CX22 (low-cost alt) | Cloud Run Job + Scheduler | Local Task Scheduler |
|---|---|---|---|---|
| **Solves always-on problem** | Yes | Yes | Yes | No — laptop-dependent |
| **Code changes needed** | None | None | Yes — checkpoint to GCS | None |
| **Google Sheets auth** | Copy token once, auto-refreshes | Copy token once, auto-refreshes | Service account required | Works as-is |
| **Service account migration** | Not required for MVP | Not required for MVP | Required | Not required |
| **Keepa API key** | `.env` + systemd env file | `.env` + systemd env file | GCP Secret Manager | `.env` locally |
| **Checkpoint persistence** | Native filesystem | Native filesystem | Cloud Storage (code change) | Native filesystem |
| **Logs** | Files on VPS, SSH-inspectable | Files on VPS, SSH-inspectable | Cloud Logging (excellent) | Files on laptop |
| **Cost/month** | ~$8–9 | ~€4–5 | ~$0 (below free tier) | $0 |
| **RAM / disk** | 8 GB / 100 GB NVMe | 4 GB / 40 GB SSD | Managed (no VPS) | Laptop resources |
| **Future n8n headroom** | Comfortable | Marginal | N/A — separate service | N/A |
| **Maintenance burden** | Low — OS updates | Low — OS updates | Very low | Low — laptop-dependent |
| **Beginner-friendliness** | Medium + control panel | Medium | Low — Docker + GCP | High |
| **Reliability** | High (VPS SLA ~99.9%) | High (VPS SLA ~99.9%) | Very high (managed) | Low (laptop uptime) |
| **Deployment complexity** | Low-medium | Low-medium | High | Very low |
| **Security surface** | VPS SSH + env file | VPS SSH + env file | GCP IAM + Secret Manager | Laptop local |
| **Rollback** | SSH in, disable timer | SSH in, disable timer | Disable Cloud Scheduler | Disable Task Scheduler |

**Winner for Keepa-only workload at minimum cost: Hetzner CX22.** It is cheaper and sufficient for this job alone.

**Winner for the broader AtlasDB automation box: Hostinger KVM 2.** The extra RAM and disk make n8n, Docker, and future scheduled ingestion viable on the same machine without a forced migration. This is the recommendation.

**Cloud Run** becomes the better choice only if checkpoint state needs to be shared across processes or if zero-maintenance infrastructure is a hard requirement. Neither applies here.

**Local Task Scheduler** does not solve the core problem.

---

## 4. Trust Boundaries

```
[Keepa API] <── KEEPA_API_KEY ── [VPS process]
[Google Sheets API] <── OAuth token ── [VPS process]
[VPS filesystem] ── checkpoint JSON, log files ── (VPS only, not internet-accessible)
[GitHub repo] ── source code only, NO secrets ── (public or private, your choice)
[.env file] ── on VPS only, never committed ── (KEEPA_API_KEY, token paths)
[SSH keypair] ── your laptop ↔ VPS ── (no password auth)
```

**What crosses the trust boundary:**
- Keepa API key → sent as HTTP header to `api.keepa.com` (TLS)
- OAuth token → sent as Bearer header to `sheets.googleapis.com` (TLS)
- ASIN lists → read from Google Sheets, sent to Keepa (TLS)
- Updated cell values → written to Google Sheets (TLS)

**What never leaves the VPS:**
- `.env` file content
- `token.json` content
- `keepa_rolling_checkpoint.json`
- Log files

---

## 5. Secrets Plan

### Secrets required

| Secret | Env var | Where stored on VPS |
|---|---|---|
| Keepa API key | `KEEPA_API_KEY` | `/home/keepa/.env` (chmod 600) |
| Google OAuth token | `GOOGLE_OAUTH_TOKEN_JSON` | Path to `/home/keepa/secrets/token.json` |
| Google OAuth client secret | `GOOGLE_OAUTH_CLIENT_SECRET_JSON` | Path to `/home/keepa/secrets/client_secret.json` |

### How to handle them

- `.env` file owned by the `keepa` service user, `chmod 600`, not world-readable.
- systemd unit file loads the env file via `EnvironmentFile=/home/keepa/atlas/.env`.
- The `token.json` and `client_secret.json` files live outside the repo directory, under `/home/keepa/secrets/`.
- `.gitignore` already excludes `.env`. Verify `secrets/` is also excluded before any `git push`.
- **Never commit either JSON file.** They contain live credentials.

### OAuth token — copy procedure (one-time, MVP)

1. On your laptop, locate the current `token.json` (the file at `GOOGLE_OAUTH_TOKEN_JSON`).
2. `scp token.json keepa@<vps-ip>:/home/keepa/secrets/token.json`
3. `scp client_secret.json keepa@<vps-ip>:/home/keepa/secrets/client_secret.json`
4. Set permissions: `chmod 600 /home/keepa/secrets/*.json`
5. The process auto-refreshes the token on each run; the file is rewritten with a new access token. The `refresh_token` field remains valid until you explicitly revoke it in Google Cloud Console.

### OAuth token — expiry risk and mitigation

Google refresh tokens do not have a fixed expiry, but they are revoked if:
- You revoke access in Google Account security settings.
- The OAuth app is set to "Testing" status in Google Cloud Console and 7 days pass without use (unlikely if running hourly).
- The app exceeds the 100-user limit (not applicable for personal use).
- Inactivity for approximately 6 months (will not happen if running hourly).

**Mitigation:** Run at least one successful update per week. Set a calendar reminder for the 6-month mark to re-authenticate if the service goes quiet.

### Future: Service Account (recommended before sharing with others)

A Google service account never expires and requires no browser interaction. Migration steps:
1. Create a service account in Google Cloud Console; download the JSON key.
2. Share each of the 4 spreadsheets with the service account email (Editor permission).
3. Rewrite `get_sheets_service()` to use `google.oauth2.service_account.Credentials` instead of the OAuth flow. This is a ~10-line change.
4. Remove the `client_secret.json` and `token.json` from the VPS.

This is the correct long-term approach but is not required for MVP.

---

## 6. Checkpoint Persistence Plan

The checkpoint file (`data/state/keepa_rolling_checkpoint.json`) lives on the VPS filesystem under the cloned repo directory. No additional infrastructure is needed.

- The directory persists across systemd timer invocations because the VPS is stateful.
- The file is written only after a successful Sheets `batchUpdate`, so a mid-run crash leaves the previous checkpoint intact (at worst, the next run re-processes the last batch — a safe duplicate write).
- Back up the checkpoint file to your laptop periodically if you care about exact resume position: `scp keepa@<vps-ip>:~/atlas/data/state/keepa_rolling_checkpoint.json ./backups/`.
- If the VPS is destroyed, the next run starts from row 8 (first row) and re-processes the full ASIN list from the beginning. This is safe — the updater never overwrites non-null cells.

---

## 7. Logging and Monitoring Plan

### Log files

Each run writes: `data/logs/keepa_sheet_update_YYYYMMDD_HHMMSS.log`

On the VPS these accumulate in `~/atlas/data/logs/`. Add a weekly cron to prune old logs:

```bash
# Keep last 30 days of logs
find /home/keepa/atlas/data/logs -name "keepa_sheet_update_*.log" -mtime +30 -delete
```

### Inspecting logs

```bash
# Most recent log
ls -t /home/keepa/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -50

# Follow the current run in real time
ls -t /home/keepa/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -f
```

### systemd journal

systemd captures stdout/stderr. View recent runs:

```bash
journalctl -u keepa-updater.service --since "24 hours ago"
```

### Minimum viable alerting (no extra services)

Option A — email on failure via systemd `OnFailure=`:
```ini
[Unit]
OnFailure=keepa-failure-notify@%i.service
```
Requires configuring `msmtp` or similar on the VPS. Simple but requires one-time mail setup.

Option B — check the log from your laptop with a one-liner:
```bash
ssh keepa@<vps-ip> "ls -t ~/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -5"
```

Option C — check the Google Sheet itself. If cells stop updating, the updater has stalled.

For MVP, Option C (check the sheet manually when something looks stale) is acceptable. Escalate to Option A if you want automated failure notification.

---

## 8. Initial Scheduler Settings

### Token math (challenge to the suggested hourly/50-ASIN plan)

| Scenario | Tokens consumed | Tokens refilled | Verdict |
|---|---|---|---|
| 1 market × 50 ASINs, hourly | 150/hour | 300/hour | Safe — 150 surplus |
| 2 markets × 50 ASINs, hourly, staggered | 300/hour | 300/hour | Borderline — no surplus |
| 4 markets × 50 ASINs, hourly | 600/hour | 300/hour | Unsustainable — deficit builds |
| 4 markets × 20 ASINs, hourly, staggered | 240/hour | 300/hour | Safe — 60 surplus |
| 4 markets × 25 ASINs, every 2h, staggered | 300/2h | 600/2h | Comfortable |

The updater already trims the batch when tokens are insufficient, so it will not crash. But running at a sustained deficit means later batches always process fewer ASINs than requested, degrading refresh cadence. Design the schedule to stay under the refill rate.

### Recommended schedule

**Phase 1 (first week):** Single marketplace, one systemd timer unit.

```
Marketplace: CA
Schedule: every 60 minutes
max-asins: 50
Tokens consumed: 150/hour (50% of refill capacity)
```

**Phase 2 (after CA is confirmed stable):** Add remaining markets, staggered.

```
US:  :00 past each hour, max-asins 25
CA:  :15 past each hour, max-asins 25
UK:  :30 past each hour, max-asins 25
DE:  :45 past each hour, max-asins 25
Total tokens: 4 × 75 = 300/hour = exactly refill rate
```

At 300 tokens/hour consumed and refilled, the system sustains indefinitely. If Keepa observes a slightly higher refill rate (which you observed at ~5 tokens/min = 300/hour), there is no surplus — consider dropping to 20 ASINs per market to leave headroom.

**Safer Phase 2 setting:**

```
Each market: max-asins 20, staggered every 15 min
Total: 4 × 60 = 240/hour consumed, 300 refilled, 60 surplus
```

### Refresh cadence estimate (Phase 2, 20 ASINs/market/hour)

If each marketplace has ~150 ASINs: 150 ÷ 20 = 7.5 hours to cycle through once. Every ASIN refreshed at least every 8 hours. Well within the 36–72h target. Target is comfortably met.

---

## 9. MVP Deployment Steps

These steps are ordered. Do not skip or reorder.

**Prerequisites — on your laptop:**
- [ ] Confirm the working command: `python src/main.py update-keepa-sheets --marketplace CA --max-asins 50 --dry-run`
- [ ] Locate `token.json` path (value of `GOOGLE_OAUTH_TOKEN_JSON` in local `.env`)
- [ ] Locate `client_secret.json` path (value of `GOOGLE_OAUTH_CLIENT_SECRET_JSON` in local `.env`)
- [ ] Have Keepa API key available (value of `KEEPA_API_KEY` in local `.env`)

**Step 1 — Provision VPS**
- [ ] Create Hostinger KVM 2 (Ubuntu 24.04 LTS, ~$8–9/month)
- [ ] Add your SSH public key during creation (Hostinger: Settings → SSH Keys)
- [ ] Note the VPS IP address

**Step 2 — Initial VPS setup (run once via SSH)**
```bash
# Log in
ssh root@<vps-ip>

# Create a non-root service user
useradd -m -s /bin/bash keepa

# Install Python 3.12 and Git (Ubuntu 24.04 ships Python 3.12)
apt update && apt install -y python3.12 python3.12-venv git

# Switch to service user
su - keepa
```

**Step 3 — Clone repo and create venv**
```bash
# As user 'keepa'
git clone <your-repo-url> atlas
cd atlas
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # or pip install keepa google-auth google-auth-oauthlib google-api-python-client python-dotenv
```

**Step 4 — Upload secrets (from your laptop)**
```bash
# Run these on your laptop, not the VPS
ssh keepa@<vps-ip> "mkdir -p /home/keepa/secrets && chmod 700 /home/keepa/secrets"
scp /path/to/token.json keepa@<vps-ip>:/home/keepa/secrets/token.json
scp /path/to/client_secret.json keepa@<vps-ip>:/home/keepa/secrets/client_secret.json
ssh keepa@<vps-ip> "chmod 600 /home/keepa/secrets/*.json"
```

**Step 5 — Create `.env` on VPS**
```bash
# As user 'keepa' on VPS
cat > /home/keepa/atlas/.env << 'EOF'
KEEPA_API_KEY=<your-keepa-key>
GOOGLE_OAUTH_TOKEN_JSON=/home/keepa/secrets/token.json
GOOGLE_OAUTH_CLIENT_SECRET_JSON=/home/keepa/secrets/client_secret.json
EOF
chmod 600 /home/keepa/atlas/.env
```

**Step 6 — Test manually on VPS**
```bash
# As user 'keepa' on VPS
cd /home/keepa/atlas
source .venv/bin/activate
source .env  # or: export $(grep -v '^#' .env | xargs)
python src/main.py update-keepa-sheets --marketplace CA --max-asins 5 --dry-run
```
Confirm: Keepa API connects, reads ASINs from sheet, no errors.

**Step 7 — Run first live write on VPS**
```bash
python src/main.py update-keepa-sheets --marketplace CA --max-asins 3
```
Confirm: 3 rows in KeepaCA updated correctly. Check the sheet manually.

**Step 8 — Create systemd service and timer (as root)**
```bash
# /etc/systemd/system/keepa-updater-ca.service
cat > /etc/systemd/system/keepa-updater-ca.service << 'EOF'
[Unit]
Description=Keepa sheet updater — CA marketplace
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=keepa
WorkingDirectory=/home/keepa/atlas
EnvironmentFile=/home/keepa/atlas/.env
ExecStart=/home/keepa/atlas/.venv/bin/python src/main.py update-keepa-sheets --marketplace CA --max-asins 50
StandardOutput=journal
StandardError=journal
EOF

# /etc/systemd/system/keepa-updater-ca.timer
cat > /etc/systemd/system/keepa-updater-ca.timer << 'EOF'
[Unit]
Description=Run Keepa CA updater hourly

[Timer]
OnBootSec=5min
OnUnitActiveSec=60min
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now keepa-updater-ca.timer
```

**Step 9 — Verify timer is running**
```bash
systemctl list-timers keepa-updater-ca.timer
journalctl -u keepa-updater-ca.service -n 50
```

**Step 10 — Monitor first automated run**
After the first automated run fires (~60 min after step 9):
```bash
ls -t /home/keepa/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -30
```
Check the Google Sheet for updated rows. Confirm checkpoint file updated:
```bash
cat /home/keepa/atlas/data/state/keepa_rolling_checkpoint.json
```

---

## 10. Rollback Plan

**Disable the timer immediately (no data is lost):**
```bash
systemctl stop keepa-updater-ca.timer
systemctl disable keepa-updater-ca.timer
```

The timer stopping does not affect the Google Sheet, the checkpoint, or the Keepa token balance. The last checkpoint remains intact; re-enabling the timer resumes from where it stopped.

**If a bad write corrupted sheet data:**
- Google Sheets has a native version history (File → Version history → See version history).
- The updater only writes fields present in `_COL_MAP` and never clears cells — the blast radius is limited to those 16 columns.
- Restore the affected rows from version history manually.

**If the VPS needs to be destroyed:**
- Disable the timer first.
- Copy checkpoint and logs to your laptop before destroying.
- The next deployment starts from row 8 for each marketplace — safe to do.

**If the OAuth token becomes invalid:**
- Run the auth flow on your laptop: `python src/main.py update-keepa-sheets --marketplace CA --max-asins 1 --dry-run` (triggers re-auth if token is stale).
- Copy the refreshed `token.json` back to the VPS.

---

## 11. What Not to Deploy Yet

The following components are explicitly **excluded from this MVP:**

| Component | Reason to exclude |
|---|---|
| SP-API report refresh | Different credential type (AWS + LWA), higher blast radius, separate deployment decision needed |
| SellerSnap import | External service integration, separate credential scope |
| AtlasDB PostgreSQL database | Requires DB on VPS or external host, not needed for Keepa sheets |
| n8n | See section 12 — planned for later, not part of this deployment |
| Multi-marketplace simultaneous launch | Phase 2 only — validate CA alone first |
| Google service account migration | Not required for MVP; document as future step |
| Cloud Run / GCP | Overcomplicated for this workload without code changes |
| Keepa `update=0` (live re-fetch) | Extra token cost, not needed; cached data is sufficient |
| Automated email alerting | Phase 2 — manual log inspection is sufficient to start |

---

## 12. Future n8n Readiness — Not Part of This Deployment

The Hostinger KVM 2 is sized to eventually host n8n alongside the Keepa updater. The following guidance applies when that time comes. **None of this should be done during the Keepa MVP deployment.**

### Install n8n later via Docker Compose

n8n should be run as a Docker Compose service with a dedicated PostgreSQL container for workflow state. This keeps n8n isolated from the Keepa Python environment and makes it easy to upgrade or remove independently.

Do not install n8n manually (non-Docker) — the upgrade path is fragile and updates can break workflows silently.

### Do not expose n8n until hardening is complete

Before n8n is accessible from the internet, all of the following must be in place:
- HTTPS via a domain name and Let's Encrypt certificate (e.g. via Caddy or nginx reverse proxy)
- n8n `N8N_BASIC_AUTH_ACTIVE=true` or equivalent authentication enabled
- UFW firewall restricting inbound to ports 22 (SSH), 80, and 443 only
- Automated backups of the n8n PostgreSQL database

An exposed n8n instance with no HTTPS and no authentication is a full credential leak vector — every credential stored in n8n workflows is readable.

### Do not add broad credentials to n8n until workflows are validated

- Do not add SP-API credentials (AWS keys, LWA client secret, refresh token) to n8n until at least one workflow has been tested end-to-end in a limited scope.
- Do not add Google Workspace credentials with broad Drive or Gmail scopes until the specific workflow that needs them is ready.
- Add credentials to n8n one workflow at a time, with the narrowest OAuth scope that gets the job done.

### Keep Keepa updater and n8n operationally separate at first

The Keepa updater runs as a systemd timer under the `keepa` service user. n8n will run as a Docker Compose service under a separate user. These should not share credentials, directories, or service accounts. If n8n later needs to trigger the Keepa updater, the cleanest approach is a webhook that calls a local script — not giving n8n direct access to the `keepa` user's secrets.

---

## 13. Open Questions Before Implementation

These must be resolved before beginning Step 1 above.

**Q1 — Repository access on VPS**
Is the AtlasDB repo private on GitHub? If yes, you need either:
- A deploy key (read-only SSH key added to the repo), or
- A GitHub Personal Access Token with `repo` scope for `git clone`.
Decision needed before Step 3.

**Q2 — Hostinger account**
Do you have a Hostinger account already? If not: create one at hostinger.com, select the KVM 2 VPS plan, choose Ubuntu 24.04 LTS, and add your SSH public key during setup. Note that Hostinger often requires selecting a data centre region at checkout — choose the region closest to your primary location or your Google Sheets data residency preference.

**Q3 — Which marketplaces to eventually schedule, and ASIN counts**
Approximate number of ASINs per marketplace will determine whether 20 or 25 ASINs per run per market is the right batch size for Phase 2. If any market has fewer than 50 ASINs total, the batch cap is irrelevant.

**Q4 — Google Cloud Console app status**
Open [Google Cloud Console → APIs & Services → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent). If the app is set to "Testing" (not "In production"), refresh tokens expire after 7 days of OAuth inactivity. The updater will run daily so this is unlikely to matter, but it should be set to "In production" (with yourself as the only user) to remove the limit. Confirm the current status.

**Q5 — `requirements.txt` completeness**
Does `requirements.txt` exist and include all packages needed by the Keepa updater (`keepa`, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `python-dotenv`)? If there is no `requirements.txt`, a minimal one should be created before deployment to make the VPS install reproducible.

**Q6 — Log rotation preference**
The default behaviour produces one log file per run (up to 24 files/day). A 30-day purge cron is suggested. Confirm this is acceptable or specify a different retention period.

---

## Summary

| Item | Decision |
|---|---|
| **Deployment target** | Hostinger KVM 2, Ubuntu 24.04 LTS |
| **Rationale for Hostinger over Hetzner** | 8 GB RAM / 100 GB NVMe — headroom for future n8n + AtlasDB workloads |
| **Scheduler** | systemd timer, `OnUnitActiveSec=60min` |
| **Phase 1 markets** | CA only |
| **Phase 1 batch size** | `--max-asins 50` |
| **Phase 2 markets** | US, CA, UK, DE staggered every 15 min |
| **Phase 2 batch size** | `--max-asins 20` per market |
| **Google Sheets auth** | OAuth token copied from laptop, auto-refreshes |
| **Keepa API key** | `.env` file, `chmod 600`, not committed |
| **Checkpoint** | Native VPS filesystem, no code changes |
| **Logs** | Native VPS filesystem, inspectable via SSH |
| **Monthly cost** | ~$8–9 |
| **Code changes required** | None |
| **n8n** | Not deployed now — future phase, Docker Compose, separate from Keepa user |
