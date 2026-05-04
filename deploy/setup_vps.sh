#!/bin/bash
# setup_vps.sh — one-time VPS preparation for the AtlasDB Keepa updater.
#
# Run as root on a fresh Hostinger KVM 2 (Ubuntu 24.04 LTS) after first login.
# This script does NOT clone the repo, write secrets, or start any service.
# All secret values must be added manually after this script completes.
#
# Usage:
#   scp deploy/setup_vps.sh root@<vps-ip>:/root/setup_vps.sh
#   ssh root@<vps-ip> "bash /root/setup_vps.sh"

set -euo pipefail

# ── Guard: must run as root ────────────────────────────────────────────────────

if [[ "$(id -u)" -ne 0 ]]; then
    echo "[error] This script must be run as root." >&2
    exit 1
fi

echo ""
echo "=== AtlasDB VPS setup — Keepa updater (Phase 1: CA) ==="
echo ""

# ── System packages ────────────────────────────────────────────────────────────

echo "[step 1/5] Updating package lists..."
apt-get update -qq

echo "[step 2/5] Installing Python 3.12, Git, UFW..."
apt-get install -y -q python3.12 python3.12-venv python3-pip git ufw

# ── Service user ───────────────────────────────────────────────────────────────

echo "[step 3/5] Creating service user 'keepa'..."
if id -u keepa &>/dev/null; then
    echo "  [ok] User 'keepa' already exists — skipping."
else
    useradd -m -s /bin/bash keepa
    echo "  [ok] User 'keepa' created."
fi

# ── Secrets directory ──────────────────────────────────────────────────────────

echo "[step 4/5] Creating secrets directory..."
mkdir -p /home/keepa/secrets
chown keepa:keepa /home/keepa/secrets
chmod 700 /home/keepa/secrets
echo "  [ok] /home/keepa/secrets — chmod 700, owned by keepa."

# ── Firewall ───────────────────────────────────────────────────────────────────
#
# SSH (port 22) is allowed BEFORE enabling UFW to prevent locking out this
# session. Do not reorder these lines.

echo "[step 5/5] Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable
ufw status verbose
echo "  [ok] UFW enabled. Inbound: SSH only. Outbound: unrestricted."
echo "  NOTE: When you add n8n later, run: ufw allow 80 && ufw allow 443"

# ── Print next manual steps ────────────────────────────────────────────────────

echo ""
echo "================================================================"
echo " Setup complete. Manual steps required before the service runs:"
echo "================================================================"
echo ""
echo "  1. Clone the AtlasDB repo as the keepa user:"
echo "       su - keepa"
echo "       git clone <your-repo-url> atlas"
echo "         (For private repos: use a deploy key or Personal Access"
echo "          Token. See the deployment runbook for instructions.)"
echo ""
echo "  2. Create the Python virtual environment:"
echo "       cd /home/keepa/atlas"
echo "       python3.12 -m venv .venv"
echo "       source .venv/bin/activate"
echo "       pip install -r requirements.txt"
echo ""
echo "  3. Upload credentials from your laptop (run on your laptop):"
echo "       scp /path/to/token.json         keepa@<vps-ip>:/home/keepa/secrets/token.json"
echo "       scp /path/to/client_secret.json keepa@<vps-ip>:/home/keepa/secrets/client_secret.json"
echo "       ssh keepa@<vps-ip> 'chmod 600 /home/keepa/secrets/*.json'"
echo ""
echo "  4. Create /home/keepa/atlas/.env (as the keepa user):"
echo "       nano /home/keepa/atlas/.env"
echo "     Add these three lines with your actual values:"
echo "       KEEPA_API_KEY=<your-keepa-api-key>"
echo "       GOOGLE_OAUTH_TOKEN_JSON=/home/keepa/secrets/token.json"
echo "       GOOGLE_OAUTH_CLIENT_SECRET_JSON=/home/keepa/secrets/client_secret.json"
echo "     Then set permissions:"
echo "       chmod 600 /home/keepa/atlas/.env"
echo ""
echo "  5. Test manually before enabling the timer."
echo "     See: docs/hostinger_keepa_deployment_runbook.md"
echo ""
echo "  6. Copy systemd files and enable the timer (as root):"
echo "       cp /home/keepa/atlas/deploy/systemd/keepa-updater-ca.service /etc/systemd/system/"
echo "       cp /home/keepa/atlas/deploy/systemd/keepa-updater-ca.timer   /etc/systemd/system/"
echo "       systemctl daemon-reload"
echo "       systemctl enable --now keepa-updater-ca.timer"
echo ""
echo "================================================================"
echo ""
