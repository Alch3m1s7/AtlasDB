# Hostinger KVM 2 — Keepa Updater Deployment Runbook

**Scope:** Phase 1 — CA marketplace only, hourly, `--max-asins 50`.
No SP-API, SellerSnap, PostgreSQL, or n8n.

Follow every step in order. Do not skip the dry-run or the manual live test.

---

## 1. Hostinger VPS Creation Checklist

- [ ] Log in to [hpanel.hostinger.com](https://hpanel.hostinger.com)
- [ ] VPS → Create new VPS → **KVM 2** plan
- [ ] OS: **Ubuntu 24.04 LTS** (not Ubuntu 22.04, not Debian)
- [ ] Data centre: choose the region closest to your location
- [ ] Add your SSH public key during creation (see section 2)
- [ ] Disable root password login if Hostinger offers the option
- [ ] Note the VPS IPv4 address — you will need it throughout

---

## 2. SSH Key Setup

If you do not already have an SSH keypair on your laptop:

```powershell
# Run on your laptop (PowerShell or Git Bash)
ssh-keygen -t ed25519 -C "atlasdb-vps"
# Accept the default path (~/.ssh/id_ed25519) or specify one
# Set a passphrase when prompted
```

Copy the public key content to paste into Hostinger:

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

Paste the full output (`ssh-ed25519 AAAA... atlasdb-vps`) into the Hostinger SSH key field during VPS creation, or add it later via hPanel → VPS → SSH Keys.

---

## 3. Initial SSH Login

```powershell
# From your laptop — replace <vps-ip> with the actual IP
ssh root@<vps-ip>
```

If the connection is refused, wait 2–3 minutes after VPS creation for the image to boot. If it prompts for a password, the SSH key was not applied correctly — check hPanel.

---

## 4. Run setup_vps.sh

Upload the script from your laptop, then run it on the VPS.

```powershell
# On your laptop
scp deploy/setup_vps.sh root@<vps-ip>:/root/setup_vps.sh
ssh root@<vps-ip> "bash /root/setup_vps.sh"
```

The script:
- Installs Python 3.12, git, ufw
- Creates the `keepa` service user
- Creates `/home/keepa/secrets` with `chmod 700`
- Configures UFW (SSH inbound only; all outbound allowed)

Review the printed next-steps summary at the end before continuing.

---

## 5. Clone the Repo (as user `keepa`)

Switch to the service user on the VPS:

```bash
# On VPS, as root
su - keepa
```

### Option A — Public repo

```bash
git clone https://github.com/<your-org>/AtlasDB.git atlas
```

### Option B — Private repo via Personal Access Token (PAT)

1. On GitHub: Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token
2. Scope: `repo` (read-only is sufficient for clone)
3. On the VPS:

```bash
git clone https://<github-username>:<pat-token>@github.com/<your-org>/AtlasDB.git atlas
```

The PAT appears in the clone URL only during this command. It is not stored on disk unless git credential helper caches it.

### Option C — Private repo via deploy key (recommended for long-term)

1. On the VPS, as the `keepa` user:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/atlasdb_deploy -N ""
   cat ~/.ssh/atlasdb_deploy.pub
   ```
2. Add the public key to GitHub: repo → Settings → Deploy keys → Add deploy key (read-only).
3. Clone:
   ```bash
   GIT_SSH_COMMAND="ssh -i /home/keepa/.ssh/atlasdb_deploy" \
     git clone git@github.com:<your-org>/AtlasDB.git atlas
   ```

---

## 6. Create Virtual Environment

```bash
# On VPS, as user keepa
cd /home/keepa/atlas
python3.12 -m venv .venv
```

---

## 7. Install Requirements

```bash
# On VPS, as user keepa, inside /home/keepa/atlas
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

This installs all packages from the pinned `requirements.txt`, including `keepa`, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, and `python-dotenv`.

Deactivate the venv when done — the systemd service uses the interpreter path directly:

```bash
deactivate
```

---

## 8. Copy token.json and client_secret.json

Run these commands on **your laptop**, not the VPS. Replace the paths with the actual locations of your credential files.

```powershell
# On your laptop
scp C:\path\to\token.json         keepa@<vps-ip>:/home/keepa/secrets/token.json
scp C:\path\to\client_secret.json keepa@<vps-ip>:/home/keepa/secrets/client_secret.json
```

Set restrictive permissions on the VPS:

```bash
# On VPS, as user keepa
chmod 600 /home/keepa/secrets/token.json
chmod 600 /home/keepa/secrets/client_secret.json
```

Verify:

```bash
ls -la /home/keepa/secrets/
# Expected output:
# -rw------- 1 keepa keepa  ... client_secret.json
# -rw------- 1 keepa keepa  ... token.json
```

**Do not paste token contents into the terminal or any chat.** If you accidentally expose a token, revoke it immediately in Google Cloud Console → APIs & Services → Credentials.

---

## 9. Create .env on the VPS

```bash
# On VPS, as user keepa
nano /home/keepa/atlas/.env
```

Type the following, substituting your actual Keepa API key:

```
KEEPA_API_KEY=<your-keepa-api-key>
GOOGLE_OAUTH_TOKEN_JSON=/home/keepa/secrets/token.json
GOOGLE_OAUTH_CLIENT_SECRET_JSON=/home/keepa/secrets/client_secret.json
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`). Set permissions:

```bash
chmod 600 /home/keepa/atlas/.env
```

Verify the file is not world-readable:

```bash
ls -la /home/keepa/atlas/.env
# Expected: -rw------- 1 keepa keepa ... .env
```

**Do not `cat` this file into a terminal session that is being recorded or shared.**

---

## 10. Manual Dry-Run

The dry-run queries Keepa and reads the Google Sheet but writes nothing to Sheets. Run this first.

```bash
# On VPS, as user keepa
cd /home/keepa/atlas
export $(grep -v '^#' .env | xargs)
source .venv/bin/activate
python src/main.py update-keepa-sheets --marketplace CA --max-asins 5 --dry-run
```

Expected output:
- Token balance and refill rate printed
- ASIN list read from KeepaCA sheet
- Planned writes shown (no actual writes)
- `DRY-RUN complete` line at the end
- No errors

If the Keepa API fails: verify `KEEPA_API_KEY` in `.env`.
If the Sheets API fails: verify `token.json` and `client_secret.json` paths and file contents.
If you see `InstalledAppFlow` launching: the token is invalid. Re-authenticate on your laptop and re-copy.

---

## 11. Manual Live Test (3 ASINs)

Only run this after the dry-run succeeds.

```bash
# On VPS, as user keepa
python src/main.py update-keepa-sheets --marketplace CA --max-asins 3
```

After it completes:
- Open the KeepaCA spreadsheet in your browser
- Check that 3 rows have updated values in columns Q, R, Z, AB, AG, AI, etc.
- If the data looks correct, proceed to section 12

Check the checkpoint was written:

```bash
cat /home/keepa/atlas/data/state/keepa_rolling_checkpoint.json
```

---

## 12. Install systemd Service and Timer

Run the following as **root**:

```bash
# On VPS, as root
cp /home/keepa/atlas/deploy/systemd/keepa-updater-ca.service /etc/systemd/system/
cp /home/keepa/atlas/deploy/systemd/keepa-updater-ca.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now keepa-updater-ca.timer
```

---

## 13. Verify the Timer is Running

```bash
# Show next scheduled run and last trigger time
systemctl list-timers keepa-updater-ca.timer

# Show service status
systemctl status keepa-updater-ca.service

# Show journal output from the most recent run
journalctl -u keepa-updater-ca.service -n 50
```

The timer fires automatically 5 minutes after boot (`OnBootSec=5min`), then every 60 minutes (`OnUnitActiveSec=60min`). `Persistent=true` means a missed run (e.g. VPS was off) fires once on next boot rather than being skipped silently.

---

## 14. Viewing Logs

Each run produces a timestamped log file.

```bash
# View the most recent log (last 50 lines)
ls -t /home/keepa/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -50

# Follow a run in real time
ls -t /home/keepa/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -f

# View journal output for all runs in the last 24 hours
journalctl -u keepa-updater-ca.service --since "24 hours ago"

# Quick check from your laptop (replace <vps-ip>)
ssh keepa@<vps-ip> "ls -t ~/atlas/data/logs/keepa_sheet_update_*.log | head -1 | xargs tail -10"
```

Log rotation (add as a weekly root cron — `crontab -e` as root):

```
0 3 * * 0  find /home/keepa/atlas/data/logs -name "keepa_sheet_update_*.log" -mtime +30 -delete
```

---

## 15. Rollback Commands

**Pause the timer immediately (no data lost, checkpoint preserved):**

```bash
# As root
systemctl stop keepa-updater-ca.timer
systemctl disable keepa-updater-ca.timer
```

Re-enable when ready:

```bash
systemctl enable --now keepa-updater-ca.timer
```

**If a sheet write produced wrong data:**
- Open the affected spreadsheet → File → Version history → See version history
- The updater only writes the 16 columns in `_COL_MAP` and never clears cells
- Restore affected rows from version history manually

**If the OAuth token becomes invalid:**

```bash
# On your laptop — triggers re-authentication if token is stale
python src/main.py update-keepa-sheets --marketplace CA --max-asins 1 --dry-run

# Then re-copy the refreshed token to the VPS
scp C:\path\to\token.json keepa@<vps-ip>:/home/keepa/secrets/token.json
ssh keepa@<vps-ip> "chmod 600 /home/keepa/secrets/token.json"
```

**If the VPS needs to be destroyed:**

```bash
# On your laptop — back up checkpoint and recent logs before destroying
scp keepa@<vps-ip>:~/atlas/data/state/keepa_rolling_checkpoint.json ./backups/
scp -r keepa@<vps-ip>:~/atlas/data/logs/ ./backups/logs/
```

The next deployment starts from row 8 automatically — safe because the updater never overwrites non-null cells.

---

## 16. Security Checklist

Complete this before considering the deployment production-ready.

### SSH hardening

```bash
# On VPS, as root — edit sshd config
nano /etc/ssh/sshd_config
```

Confirm or set these values:

```
PasswordAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
```

Restart SSH after editing:

```bash
systemctl restart ssh
```

**Test from a second terminal that you can still log in before closing the first.**

### File permissions audit

```bash
# Run as root — check all permissions at once
echo "=== .env ===" && ls -la /home/keepa/atlas/.env
echo "=== secrets/ ===" && ls -la /home/keepa/secrets/
echo "=== UFW ===" && ufw status verbose
echo "=== keepa user ===" && id keepa
```

Expected results:

| Path | Permission | Owner |
|---|---|---|
| `/home/keepa/atlas/.env` | `-rw-------` (600) | `keepa` |
| `/home/keepa/secrets/` | `drwx------` (700) | `keepa` |
| `/home/keepa/secrets/token.json` | `-rw-------` (600) | `keepa` |
| `/home/keepa/secrets/client_secret.json` | `-rw-------` (600) | `keepa` |

### Credentials deployed on this VPS

At the end of Phase 1, the only credentials present should be:

- [ ] Keepa API key (in `.env`)
- [ ] Google OAuth token — Sheets API scope only (in `secrets/token.json`)
- [ ] Google OAuth client secret (in `secrets/client_secret.json`)

No AWS keys. No SP-API credentials. No SellerSnap credentials. No database passwords.

---

---

## 17. Phase 3 — Multi-market Keepa Cycle Deployment

Switches the VPS from the CA-only timer (`keepa-updater-ca.timer`) to the
multi-marketplace cycle timer (`keepa-updater-cycle.timer`).

**Do not run the CA-only timer and the cycle timer at the same time.**
The transition window where both are stopped is safe — the cycle timer fires
on its own `OnBootSec=5min` trigger and catches up via `Persistent=true`.

---

### 17.1 Pull latest code on VPS

```bash
# On VPS, as user keepa
cd /home/keepa/atlas
git pull --ff-only
```

If `git pull` fails with "not possible to fast-forward", do not force-push or
reset. Stop and investigate — the branch may have diverged.

---

### 17.2 Manual dry-run

Queries Keepa and reads the active marketplace's sheet; writes nothing.

```bash
# On VPS, as user keepa
cd /home/keepa/atlas
export $(grep -v '^#' .env | xargs)
source .venv/bin/activate
python src/main.py update-keepa-sheets-cycle --max-asins 5 --dry-run
```

Expected output:
- Active marketplace shown (defaults to CA if no cycle state file exists)
- Keepa token balance printed
- "DRY-RUN SUMMARY" block shown with planned writes
- "Cycle NOT advanced: dry_run=True, no state written"
- No errors

If this fails, do not proceed to the live test.

---

### 17.3 Tiny live test (3 ASINs)

Only run after the dry-run succeeds.

```bash
# On VPS, as user keepa
python src/main.py update-keepa-sheets-cycle --max-asins 3
```

Check the cycle state file was created:

```bash
cat /home/keepa/atlas/data/state/keepa_cycle_state.json
```

Expected: `active_marketplace` is `CA` (or the next marketplace if CA just
completed a full pass). The rolling checkpoint file is separate and unchanged
from the CA-only timer's checkpoint.

```bash
cat /home/keepa/atlas/data/state/keepa_rolling_checkpoint.json
```

---

### 17.4 Install new systemd files

Run as **root**:

```bash
# On VPS, as root
cp /home/keepa/atlas/deploy/systemd/keepa-updater-cycle.service /etc/systemd/system/
cp /home/keepa/atlas/deploy/systemd/keepa-updater-cycle.timer   /etc/systemd/system/
systemctl daemon-reload
```

---

### 17.5 Disable the CA-only timer

Stop and disable the CA-only timer **before** enabling the cycle timer.
This prevents both timers running the same marketplace concurrently.

```bash
# On VPS, as root
sudo systemctl disable --now keepa-updater-ca.timer
```

Confirm it is stopped:

```bash
systemctl status keepa-updater-ca.timer
# Expected: "inactive (dead)"
```

---

### 17.6 Start cycle service manually once

Runs the cycle once synchronously so you can check logs before enabling the
timer.

```bash
# On VPS, as root
sudo systemctl start keepa-updater-cycle.service
```

---

### 17.7 Check status and logs

```bash
# Service exit status
sudo systemctl status keepa-updater-cycle.service --no-pager

# Journal output from this run
sudo journalctl -u keepa-updater-cycle.service -n 100 --no-pager
```

Expected: service exits with code 0, marketplace processed, checkpoint saved.

---

### 17.8 Enable the cycle timer

```bash
# On VPS, as root
sudo systemctl enable --now keepa-updater-cycle.timer
```

---

### 17.9 Confirm timers

```bash
systemctl list-timers 'keepa-updater*' --no-pager
```

Expected output shows only `keepa-updater-cycle.timer` active; the CA timer
should be absent or inactive. The next trigger time should be roughly 61 minutes
from now.

---

### 17.10 Rollback to CA-only timer

If anything goes wrong, revert to the CA-only timer:

```bash
# On VPS, as root
sudo systemctl disable --now keepa-updater-cycle.timer
sudo systemctl enable --now keepa-updater-ca.timer
```

Confirm rollback:

```bash
systemctl list-timers 'keepa-updater*' --no-pager
# Expected: keepa-updater-ca.timer active; cycle timer absent
```

The CA rolling checkpoint is unaffected — it persists in `keepa_rolling_checkpoint.json`
and the CA-only service resumes from where it left off.

---

### 17.11 Manual verification checklist

After enabling the cycle timer, confirm all of the following before treating
the deployment as production-ready:

- [ ] Missing cycle state file starts with `active_marketplace: CA` (default).
- [ ] Existing CA rolling checkpoint is preserved — `keepa_rolling_checkpoint.json`
      still contains the `CA` entry from the CA-only timer's runs.
- [ ] Each timer run processes exactly one marketplace; the cycle state file
      advances to the next marketplace only when all advancement conditions are met.
- [ ] `keepa-updater-ca.timer` is disabled — confirm with
      `systemctl is-enabled keepa-updater-ca.timer` returning `disabled`.
- [ ] `keepa-updater-cycle.timer` is enabled — confirm with
      `systemctl is-enabled keepa-updater-cycle.timer` returning `enabled`.
- [ ] Only one timer fires at a time — `systemctl list-timers 'keepa-updater*'`
      shows a single active timer.
- [ ] `keepa_cycle_state.json` and `keepa_rolling_checkpoint.json` are separate
      files (cycle state controls which marketplace is next; rolling checkpoint
      stores per-marketplace row progress).

---

## Appendix: Useful One-Liners

```bash
# Check token balance in the checkpoint (not live Keepa balance)
cat /home/keepa/atlas/data/state/keepa_rolling_checkpoint.json | python3 -m json.tool

# Count log files
ls /home/keepa/atlas/data/logs/keepa_sheet_update_*.log | wc -l

# Show disk usage of logs directory
du -sh /home/keepa/atlas/data/logs/

# Show systemd timer schedule
systemctl list-timers --all | grep keepa
```
