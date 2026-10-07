#!/usr/bin/env bash
# PRE-02 step 2 — Docker Engine install via Docker's official apt repository
# (https://docs.docker.com/engine/install/ubuntu/). Authorized scope only:
# docker-ce, docker-ce-cli, containerd.io, docker-buildx-plugin, docker-compose-plugin,
# add `user` to group docker. No SSH/firewall/network/unrelated config changes.
# Run interactively (sudo prompts on the TTY; password is never passed in a command):
#   ssh -t -p 9922 user@<VM> "$(cat install.sh)" 2>&1 | tee raw/install.raw.log
set -euo pipefail
step() { printf '\n===== %s =====\n' "$1"; }

# Docker's published release-signing key fingerprint (docs.docker.com).
EXPECTED_FPR="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
PACKAGES="docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"

step "GUARD: OS, arch, conflicts (abort before any change)"
. /etc/os-release
[ "$ID" = ubuntu ] && [ "$VERSION_CODENAME" = noble ] || { echo "ABORT: unexpected OS $ID $VERSION_CODENAME"; exit 1; }
[ "$(dpkg --print-architecture)" = amd64 ] || { echo "ABORT: unexpected arch"; exit 1; }
for p in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed'; then
    echo "ABORT: conflicting package installed: $p"; exit 1
  fi
done
if grep -rqs 'download.docker.com' /etc/apt/sources.list /etc/apt/sources.list.d/; then
  echo "ABORT: a Docker apt source already exists"; exit 1
fi
echo "guards passed: ubuntu noble amd64, no conflicts, no existing docker source"

step "SUDO (interactive prompt on TTY)"
sudo -v

step "FETCH + VERIFY DOCKER GPG KEY"
TMPKEY="$(mktemp)"
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$TMPKEY"
FPR="$(gpg --show-keys --with-colons "$TMPKEY" | awk -F: '/^fpr:/{print $10; exit}')"
echo "key fingerprint: $FPR"
[ "$FPR" = "$EXPECTED_FPR" ] || { echo "ABORT: fingerprint mismatch"; rm -f "$TMPKEY"; exit 1; }
sudo install -m 0755 -d /etc/apt/keyrings
sudo install -m 0644 "$TMPKEY" /etc/apt/keyrings/docker.asc
rm -f "$TMPKEY"

step "ADD DOCKER APT SOURCE"
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
cat /etc/apt/sources.list.d/docker.sources

step "APT UPDATE"
sudo apt-get update

step "CANDIDATE VERSIONS"
apt-cache policy $PACKAGES | grep -E '^[a-z]|Candidate'

step "INSTALL"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y $PACKAGES

step "GROUP MEMBERSHIP"
sudo usermod -aG docker user
getent group docker

step "SERVICE (enabled/started by package postinst)"
systemctl is-enabled docker containerd || true
systemctl is-active docker containerd || true

step "INSTALLED PACKAGES"
dpkg-query -W -f='${Package} ${Version}\n' $PACKAGES docker-ce-rootless-extras 2>/dev/null || true

echo
echo "INSTALL: DONE (log out and back in for docker group to apply)"
