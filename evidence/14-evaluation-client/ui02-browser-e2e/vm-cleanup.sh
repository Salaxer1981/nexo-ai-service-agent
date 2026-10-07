#!/usr/bin/env bash
# UI-02 — recovery cleanup after the run-1 SSH disconnect (owner-run). Removes ONLY what the UI-02 harness created:
# the compose project "nexo" (containers, volumes, networks), the images it built or pulled, the build cache, any
# leftover harness / control endpoint process, and ~/nexo-ui02 (checkout, .env, key and token files).
# v2: process patterns use a regex bracket ("nexo-ui0[2]") so they can never match THIS script's own command line
# (v1 matched itself and killed itself before cleaning). Own PID and parent are also excluded explicitly.
set -u
W="$HOME/nexo-ui02"
SELF="$$"; PARENT="$PPID"
procs(){ pgrep -f "$1" | grep -vxE "$SELF|$PARENT" || true; }
HARNESS='EXPECTED_SHA=ca86d7[c]3459f713319aa80de482cbcdb8c22fa01'
CONTROL='nexo-ui0[2]/control[.]py'
echo "===== FOUND ====="
echo "work dir present: $([ -e "$W" ] && echo yes || echo no)"
echo "harness shells: $(procs "$HARNESS" | wc -l) | control endpoint processes: $(procs "$CONTROL" | wc -l)"
docker ps -a --format '{{.Names}} {{.Status}}'
echo "===== CLEANUP ====="
for p in $(procs "$HARNESS") $(procs "$CONTROL"); do kill "$p" 2>/dev/null && echo "stopped UI-02 process $p"; done
sleep 2
for p in $(procs "$HARNESS") $(procs "$CONTROL"); do kill -9 "$p" 2>/dev/null && echo "force-stopped UI-02 process $p"; done
if [ -f "$W/repo/compose.yaml" ]; then (cd "$W/repo" && docker compose down -v 2>&1 | tail -12); else docker compose -p nexo down -v 2>&1 | tail -12; fi
for img in nexo-web:0.1.0 nexo-backend:0.1.0 pgvector/pgvector:0.8.7-pg17-bookworm n8nio/n8n:2.42.3 node:22.16.0-alpine; do
  docker image inspect "$img" >/dev/null 2>&1 && docker image rm -f "$img" 2>&1 | head -1
done
docker builder prune -f 2>&1 | tail -1
case "$W" in "$HOME"/nexo-ui02) rm -rf -- "$W" ;; esac
echo "===== FINAL STATE (post-cleanup) ====="
docker ps -a; docker images; docker volume ls; docker network ls; docker system df; ss -tlnH
echo "VERIFY nexo containers: $(docker ps -aq --filter label=com.docker.compose.project=nexo | wc -l)"
echo "VERIFY nexo volumes: $(docker volume ls -q --filter label=com.docker.compose.project=nexo | wc -l)"
echo "VERIFY nexo networks: $(docker network ls -q --filter label=com.docker.compose.project=nexo | wc -l)"
echo "VERIFY UI-02 harness/control processes: $(( $(procs "$HARNESS" | wc -l) + $(procs "$CONTROL" | wc -l) ))"
echo "VERIFY work dir: $([ -e "$W" ] && echo PRESENT || echo removed)"
for port in 8000 5432 5678 8080 8099; do
  echo "VERIFY listener :$port: $(ss -tlnH | awk '{print $4}' | grep -cE ":$port\$")"
done
