#!/usr/bin/env bash
# PRE-01 read-only VM preflight. Run remotely via: ssh <user>@<host> 'bash -s' < preflight.sh
# Makes NO changes: no sudo, no installs, no config edits, no container/network/volume creation.
set -u
sec() { printf '\n===== %s =====\n' "$1"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1 || printf '(exit %s)\n' "$?"; }

sec "A. ACCESS"
run whoami
run id
run hostname
run date -u

sec "B. OPERATING SYSTEM"
run cat /etc/os-release
run uname -r
run uname -m

sec "C. CAPACITY"
run nproc
run lscpu
run free -h
run df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay
run df -h /var/lib/docker /home /tmp

sec "D. CONTAINERS"
run command -v docker
run docker --version
run docker compose version
run docker-compose --version
run systemctl is-active docker
run docker info --format 'ServerVersion={{.ServerVersion}} Driver={{.Driver}} RootDir={{.DockerRootDir}} Containers={{.Containers}} Running={{.ContainersRunning}}'
run docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
run docker network ls
run docker volume ls
run docker system df

sec "E. NETWORK"
run ss -tlnH
run ss -ulnH
printf '$ curl -sS -o /dev/null -w ... https://openrouter.ai/api/v1/models\n'
curl -sS -o /dev/null -m 15 -w 'http_code=%{http_code} time=%{time_total}s\n' https://openrouter.ai/api/v1/models 2>&1 || echo "(curl failed)"
printf '$ curl -sS -o /dev/null -w ... https://pypi.org/simple/\n'
curl -sS -o /dev/null -m 15 -w 'http_code=%{http_code} time=%{time_total}s\n' https://pypi.org/simple/ 2>&1 || echo "(curl failed)"

sec "F. RUNTIME"
run git --version
run python3 --version
run python3 -c 'import venv, ensurepip; print("venv+ensurepip OK")'
run pip3 --version
run curl --version
