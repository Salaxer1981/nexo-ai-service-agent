#!/usr/bin/env bash
# PRE-02 step 1 — READ-ONLY apt/repository/conflict inspection before Docker install.
# Run: ssh -p 9922 user@<VM> 'bash -s' < inspect.sh
# No sudo, no installs, no config edits.
set -u
sec() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1 || printf '(exit %s)\n' "$?"; }

sec "OS / ARCH COMPATIBILITY"
run grep -E '^(VERSION_ID|VERSION_CODENAME|UBUNTU_CODENAME)=' /etc/os-release
run dpkg --print-architecture

sec "APT SOURCES"
run ls -la /etc/apt/sources.list.d/
run ls -la /etc/apt/keyrings/
run grep -rhE '^(Types|URIs|Suites|Components|deb )' /etc/apt/sources.list /etc/apt/sources.list.d/
run grep -rl 'download.docker.com' /etc/apt/sources.list /etc/apt/sources.list.d/

sec "CONFLICTING PACKAGES (Docker docs list)"
for p in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc docker-ce docker-ce-cli containerd.io; do
  printf '%-20s %s\n' "$p" "$(dpkg-query -W -f='${Status} ${Version}' "$p" 2>/dev/null || echo 'not-installed')"
done
run snap list docker
run apt-cache policy docker-ce docker.io

sec "APT/DPKG ACTIVITY (must be idle)"
run pgrep -a 'apt|dpkg|unattended'

sec "PREREQUISITES"
run dpkg-query -W -f='${Package} ${Version}\n' ca-certificates curl gnupg
run command -v gpg

sec "FIREWALL CONTEXT (read-only)"
run systemctl is-active ufw
run update-alternatives --query iptables

sec "EXISTING docker GROUP / USER GROUPS"
run getent group docker
run id

sec "REACHABILITY"
printf '$ curl https://download.docker.com/linux/ubuntu/dists/noble/Release\n'
curl -sS -o /dev/null -m 15 -w 'http_code=%{http_code}\n' https://download.docker.com/linux/ubuntu/dists/noble/Release 2>&1 || echo "(curl failed)"
printf '$ curl https://registry-1.docker.io/v2/\n'
curl -sS -o /dev/null -m 15 -w 'http_code=%{http_code} (401 expected = reachable)\n' https://registry-1.docker.io/v2/ 2>&1 || echo "(curl failed)"

sec "DISK BEFORE"
run df -h /
