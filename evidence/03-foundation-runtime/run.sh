#!/usr/bin/env bash
# FOUNDATION-02 — temporary runtime validation of FOUNDATION-01 on the VM.
# Owner-run, single SSH session. The repo arrives as a git bundle on stdin:
#   ssh -p 9922 user@<VM> "$(cat run.sh)" < foundation.bundle > raw/run.raw.log 2>&1
# Secrets: the DB password is generated on the VM, written only to a chmod-600
# VM-local .env, never printed; the log is checked for it before .env is deleted.
# No sudo. No firewall/SSH changes. No LLM calls. Cleans up everything it created.
set -u
EXPECTED_SHA=59264698b854ddcd7e58ffb8168d68f60766bd28
WORK="$HOME/nexo-f02"
REPO="$WORK/repo"
LOG="$WORK/run.log"
DB_IMAGE=pgvector/pgvector:0.8.7-pg17-bookworm
BASE_IMAGE=python:3.12.15-slim-bookworm
BACKEND_IMAGE=nexo-backend:0.1.0
FAILED=0

sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
psql_db(){ docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"' ; }

sec "0. PRE-CHECKS"
if [ -e "$WORK" ]; then echo "ABORT: $WORK already exists"; exit 1; fi
if ss -tlnH | grep -q ':8000 '; then echo "ABORT: port 8000 already in use"; exit 1; fi
if docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"'; then echo "ABORT: compose project 'nexo' already exists"; exit 1; fi
if docker volume inspect nexo_db_data >/dev/null 2>&1; then echo "ABORT: volume nexo_db_data already exists"; exit 1; fi
echo "pre-checks passed (no existing dir/project/volume, port 8000 free)"
run date -u
run docker system df

mkdir -p "$WORK"
exec > >(tee "$LOG") 2>&1

sec "1. CHECKOUT EXACT COMMIT"
cat > "$WORK/foundation.bundle"
run git bundle verify "$WORK/foundation.bundle" | tail -1
run git clone -q "$WORK/foundation.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
HEAD_SHA="$(git -C "$REPO" rev-parse HEAD)"
echo "VM checkout HEAD: $HEAD_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$HEAD_SHA" = "$EXPECTED_SHA" ]'
check "working tree clean" '[ -z "$(git -C "$REPO" status --porcelain)" ]'
cd "$REPO" || exit 1

sec "2. VM-LOCAL .env (generated; values never printed)"
( umask 077
  PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nBACKEND_PORT=8000\n' "$PW" > .env )
run stat -c '%A %U %n' .env
echo ".env variable names: $(cut -d= -f1 .env | tr '\n' ' ')"
check ".env ignored by git" 'git check-ignore -q .env'

sec "3. docker compose config"
run docker compose config --quiet && echo "compose config: VALID"
check "docker compose config succeeds" 'docker compose config --quiet'
echo "--- resolved config (POSTGRES_PASSWORD redacted):"
docker compose config 2>&1 | sed -E 's/(POSTGRES_PASSWORD:).*/\1 <REDACTED>/'

sec "4. BUILD BACKEND IMAGE"
run docker compose --progress plain build backend 2>&1 | tail -40
check "backend image built" 'docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1'
run docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Size}}'

sec "5. START STACK (backend + db, wait for healthy)"
run docker compose up -d --wait --wait-timeout 180
run docker compose ps --format 'table {{.Service}}\t{{.Name}}\t{{.Status}}\t{{.Ports}}'
DB_STATUS="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q db)")"
BE_STATUS="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q backend)")"
echo "db health: $DB_STATUS / backend health: $BE_STATUS"
check "db container healthy" '[ "$DB_STATUS" = healthy ]'
check "backend container healthy" '[ "$BE_STATUS" = healthy ]'

sec "6. /health FROM VM HOST"
BODY="$(curl -s -o - -w '\n%{http_code}' http://127.0.0.1:8000/health)"
CODE="$(printf '%s' "$BODY" | tail -1)"; BODY="$(printf '%s' "$BODY" | head -1)"
echo "HTTP $CODE body=$BODY"
check "/health HTTP 200" '[ "$CODE" = 200 ]'
check "/health body exactly {\"status\":\"ok\"}" '[ "$BODY" = "{\"status\":\"ok\"}" ]'

sec "7. PORTS AND NETWORK"
run docker port "$(docker compose ps -q db)"; echo "(empty above = db has no published port)"
run docker port "$(docker compose ps -q backend)"
run ss -tlnH
check "no host listener on 5432" '! ss -tlnH | grep -q ":5432 "'
check "backend bound only to 127.0.0.1:8000" '[ "$(ss -tlnH | grep ":8000 " | awk "{print \$4}" | sort -u | tr "\n" " ")" = "127.0.0.1:8000 " ]'
check "public listeners unchanged (only :9922)" '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'
run docker network inspect nexo_internal --format 'name={{.Name}} driver={{.Driver}} internal={{.Internal}}'
check "network nexo_internal is not internal-only (egress possible)" '[ "$(docker network inspect nexo_internal -f {{.Internal}})" = false ]'

sec "8. SERVICE-TO-SERVICE COMMUNICATION"
run docker compose exec -T backend python -c "import socket; a=socket.getaddrinfo('db',5432)[0][4][0]; s=socket.create_connection(('db',5432),3); print('backend -> db:5432 TCP OK, db resolves to', a); s.close()"
check "backend reaches db:5432 over Docker DNS" 'docker compose exec -T backend python -c "import socket; socket.create_connection((\"db\",5432),3)" >/dev/null 2>&1'
echo "--- authenticated SQL login over the network (password via --env-file, not command line):"
run docker run --rm --network nexo_internal --env-file .env "$DB_IMAGE" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -t -A -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select '"'"'network login ok, server '"'"' || current_setting('"'"'server_version'"'"')"'

sec "9. EGRESS READINESS (no API key, no LLM call)"
run docker compose exec -T backend python -c "import socket,urllib.request; print('dns openrouter.ai ->', socket.getaddrinfo('openrouter.ai',443)[0][4][0]); r=urllib.request.urlopen('https://openrouter.ai/api/v1/models', timeout=15); print('HTTPS GET /api/v1/models (public, unauthenticated) ->', r.status)"

sec "10. PERSISTENCE — A/B: create and read marker"
MARKER="f02-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"
echo "marker: $MARKER"
printf "CREATE TABLE foundation02_marker (id serial PRIMARY KEY, marker text NOT NULL, created_at timestamptz DEFAULT now());\nINSERT INTO foundation02_marker (marker) VALUES ('%s');\n" "$MARKER" | psql_db
echo "SELECT id, marker, created_at FROM foundation02_marker;" | psql_db
DB_CID_BEFORE="$(docker compose ps -q db)"
VOL_CREATED="$(docker volume inspect nexo_db_data -f '{{.CreatedAt}}')"
echo "db container before: ${DB_CID_BEFORE:0:12}  volume nexo_db_data created: $VOL_CREATED"
run docker inspect -f '{{range .Mounts}}{{.Type}} {{.Name}} -> {{.Destination}}{{println}}{{end}}' "$DB_CID_BEFORE"

sec "10. PERSISTENCE — C: remove containers + network (volume kept), recreate"
run docker compose down
run docker compose ps -a
run docker volume ls --filter name=nexo_db_data
check "no nexo containers remain after down" '[ -z "$(docker compose ps -aq)" ]'
check "volume nexo_db_data still exists after down" 'docker volume inspect nexo_db_data >/dev/null 2>&1'
run docker compose up -d --wait --wait-timeout 180
DB_CID_AFTER="$(docker compose ps -q db)"
echo "db container after:  ${DB_CID_AFTER:0:12}  volume created: $(docker volume inspect nexo_db_data -f '{{.CreatedAt}}')"
check "db container was recreated (different ID)" '[ -n "$DB_CID_AFTER" ] && [ "$DB_CID_AFTER" != "$DB_CID_BEFORE" ]'
check "same volume instance (CreatedAt unchanged)" '[ "$(docker volume inspect nexo_db_data -f {{.CreatedAt}})" = "$VOL_CREATED" ]'

sec "10. PERSISTENCE — D: marker after recreation"
AFTER="$(echo "SELECT marker FROM foundation02_marker;" | psql_db)"
echo "marker read after recreate: $AFTER"
check "marker survived container recreation" '[ "$AFTER" = "$MARKER" ]'
check "/health still 200 after recreate" '[ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/health)" = 200 ]'

sec "11. RESULT"
if [ "$FAILED" = 0 ]; then echo "FOUNDATION-02 RUNTIME: ALL CHECKS PASS"; else echo "FOUNDATION-02 RUNTIME: FAILURES (see CHECK FAIL)"; run docker compose logs --no-color --tail 50; fi

sec "12. CLEANUP"
echo "DROP TABLE foundation02_marker;" | psql_db && echo "marker table dropped"
echo "SELECT to_regclass('foundation02_marker') IS NULL AS table_gone;" | psql_db
run docker compose down -v
run docker image rm "$BACKEND_IMAGE" "$DB_IMAGE" "$BASE_IMAGE"
run docker builder prune -f

sec "13. SECRET-IN-LOG CHECK (value never printed)"
PW="$(sed -n 's/^POSTGRES_PASSWORD=//p' "$REPO/.env")"
HITS="$(grep -cF -- "$PW" "$LOG")"; unset PW
echo "occurrences of generated DB password in run log: $HITS"
cd "$HOME"
case "$WORK" in "$HOME"/nexo-f02) rm -rf -- "$WORK" ;; *) echo "refusing to remove unexpected path";; esac

sec "14. FINAL STATE"
run docker ps -a
run docker images
run docker volume ls
run docker network ls
run docker system df
run ss -tlnH
run test ! -e "$HOME/nexo-f02" && echo "temporary directory removed (incl. .env)"
