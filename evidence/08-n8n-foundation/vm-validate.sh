#!/usr/bin/env bash
# N8N-01 — temporary VM validation of the n8n foundation. PREPARED, NOT YET EXECUTED:
# requires explicit owner authorization. Owner-run, one SSH session:
#   ssh -p 9922 user@<VM> "EXPECTED_SHA=<commit>; $(cat vm-validate.sh)" < n8n.bundle > raw/run.raw.log 2>&1
# Generates all secrets on the VM (DB password, 2 tokens, N8N_ENCRYPTION_KEY) into a chmod-600 .env;
# never prints them; no LLM calls; no business writes; nothing published beyond 127.0.0.1; full cleanup.
set -u
: "${EXPECTED_SHA:?set EXPECTED_SHA}"
WORK="$HOME/nexo-n8n01"
REPO="$WORK/repo"
LOG="$WORK/run.log"
IMAGES="nexo-backend:0.1.0 pgvector/pgvector:0.8.7-pg17-bookworm n8nio/n8n:2.42.3"
FAILED=0
sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
n8n_exec(){ docker compose exec -T -u node n8n "$@"; }

sec "0. PRE-CHECKS"
[ -e "$WORK" ] && { echo "ABORT: $WORK exists"; exit 1; }
ss -tlnH | grep -qE ':(8000|5678) ' && { echo "ABORT: port 8000 or 5678 in use"; exit 1; }
docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"' && { echo "ABORT: project nexo exists"; exit 1; }
for v in nexo_db_data nexo_n8n_data; do docker volume inspect "$v" >/dev/null 2>&1 && { echo "ABORT: volume $v exists"; exit 1; }; done
echo "pre-checks passed"; run docker system df

mkdir -p "$WORK"; exec > >(tee "$LOG") 2>&1

sec "1. CHECKOUT EXACT COMMIT"
cat > "$WORK/n8n.bundle"
run git clone -q "$WORK/n8n.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$(git -C "$REPO" rev-parse HEAD)" = "$EXPECTED_SHA" ]'
cd "$REPO" || exit 1

sec "2. VM-LOCAL .env (generated; values never printed)"
( umask 077
  tok() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nAUTH_TOKEN_CUSTOMER_A=%s\nAUTH_TOKEN_CUSTOMER_B=%s\nN8N_ENCRYPTION_KEY=%s\n' \
    "$(tok)" "$(tok)" "$(tok)" "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > .env )
run stat -c '%A %n' .env; echo ".env names: $(cut -d= -f1 .env | tr '\n' ' ')"

sec "3. CONFIG + BUILD + START"
check "docker compose config valid" 'docker compose config --quiet'
run docker compose --progress plain build backend 2>&1 | tail -3
run docker compose up -d --wait --wait-timeout 300
run docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
for s in db backend n8n; do
  check "$s healthy" '[ "$(docker inspect -f {{.State.Health.Status}} "$(docker compose ps -q '"$s"')")" = healthy ]'
done
check "n8n /healthz 200 via host loopback" '[ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:5678/healthz)" = 200 ]'
check "backend /health/ready 200 via host loopback" '[ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/health/ready)" = 200 ]'
run docker compose exec -T n8n n8n --version

sec "4. HOST EXPOSURE"
run ss -tlnH
run docker port "$(docker compose ps -q n8n)"
check "n8n published only on 127.0.0.1:5678" '[ "$(docker port "$(docker compose ps -q n8n)")" = "5678/tcp -> 127.0.0.1:5678" ]'
check "no host listener on 5432" '! ss -tlnH | grep -q ":5432 "'
check "new listeners only on loopback (8000, 5678); public only :9922" \
  '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'

sec "5. NETWORKS (least privilege)"
for n in nexo_internal nexo_automation; do
  echo "$n: $(docker network inspect "$n" -f '{{range .Containers}}{{.Name}} {{end}}')"
done
check "automation = backend + n8n only" '[ "$(docker network inspect nexo_automation -f "{{range .Containers}}{{.Name}} {{end}}" | tr " " "\n" | grep . | sort | tr "\n" " ")" = "nexo-backend-1 nexo-n8n-1 " ]'
check "internal = backend + db only" '[ "$(docker network inspect nexo_internal -f "{{range .Containers}}{{.Name}} {{end}}" | tr " " "\n" | grep . | sort | tr "\n" " ")" = "nexo-backend-1 nexo-db-1 " ]'
nets_of(){ docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$(docker compose ps -q "$1")" | tr ' ' '\n' | grep . | sort | tr '\n' ' '; }
for s in n8n backend db; do echo "$s attached to: $(nets_of $s)"; done
check "n8n container only on nexo_automation" '[ "$(nets_of n8n)" = "nexo_automation " ]'
check "backend container on nexo_automation + nexo_internal" '[ "$(nets_of backend)" = "nexo_automation nexo_internal " ]'

sec "5b. ENVIRONMENT PASSED TO n8n (names only, values never printed)"
n8n_env_names(){ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$(docker compose ps -q n8n)" | cut -d= -f1 | grep . | sort | tr '\n' ' '; }
echo "n8n env names: $(n8n_env_names)"
check "no application secrets in n8n env (POSTGRES_*, AUTH_TOKEN_*)" '! n8n_env_names | tr " " "\n" | grep -qE "^(POSTGRES_|AUTH_TOKEN_)"'

sec "6. CONNECTIVITY (no LLM, no business write)"
run docker compose exec -T n8n node -e "fetch('http://backend:8000/health').then(async r=>{console.log('n8n -> http://backend:8000/health:', r.status, await r.text()); process.exit(r.status===200?0:1)}).catch(e=>{console.log('error', e.message); process.exit(1)})"
check "n8n reaches backend via Docker DNS" 'docker compose exec -T n8n node -e "fetch(\"http://backend:8000/health\").then(r=>process.exit(r.status===200?0:1)).catch(()=>process.exit(1))"'
run docker compose exec -T n8n node -e "require('dns').lookup('db',(e,a)=>{console.log(e?'n8n cannot resolve db: '+e.code:'n8n RESOLVED db -> '+a); process.exit(e?0:1)})"
check "n8n cannot resolve the database host" 'docker compose exec -T n8n node -e "require(\"dns\").lookup(\"db\",e=>process.exit(e?0:1))"'

sec "7. FIRST-RUN OWNER STATE (info only; internal endpoint, not a contract)"
curl -s http://127.0.0.1:5678/rest/settings | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin).get("data",{}); print("userManagement.showSetupOnFirstLoad =", d.get("userManagement",{}).get("showSetupOnFirstLoad"))
except Exception as e: print("settings not readable:", type(e).__name__)'

sec "8. PERSISTENCE (harmless inactive marker workflow via n8n CLI)"
cat > "$WORK/marker.json" <<'JSON'
{"id":"NexoMarker000001","name":"nexo-persistence-marker","active":false,"settings":{},"connections":{},
 "nodes":[{"id":"6f0c6a2e-0000-4000-8000-000000000001","name":"Manual Trigger","type":"n8n-nodes-base.manualTrigger","typeVersion":1,"position":[0,0],"parameters":{}}]}
JSON
docker compose cp "$WORK/marker.json" n8n:/tmp/marker.json
run n8n_exec n8n import:workflow --input=/tmp/marker.json
marker_present(){ n8n_exec n8n export:workflow --id=NexoMarker000001 --output=/tmp/marker-out.json >/dev/null 2>&1 \
  && n8n_exec sh -c 'grep -q nexo-persistence-marker /tmp/marker-out.json'; }
check "marker workflow stored" 'marker_present'
key_fp(){ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$(docker compose ps -q n8n)" \
  | sed -n 's/^N8N_ENCRYPTION_KEY=//p' | sha256sum | cut -c1-16; }  # fingerprint only, never the key
KEY_FP_BEFORE="$(key_fp)"; echo "encryption key fingerprint before: $KEY_FP_BEFORE"
CID_BEFORE="$(docker compose ps -q n8n)"
run docker compose rm -sf n8n
check "n8n_data volume kept" 'docker volume inspect nexo_n8n_data >/dev/null 2>&1'
run docker compose up -d --wait --wait-timeout 180 n8n
check "n8n container recreated" '[ "$(docker compose ps -q n8n)" != "$CID_BEFORE" ]'
check "marker workflow survived recreation" 'marker_present'
check "n8n healthy after recreation" '[ "$(docker inspect -f {{.State.Health.Status}} "$(docker compose ps -q n8n)")" = healthy ]'
echo "encryption key fingerprint after:  $(key_fp)"
check "same encryption key across recreation (fingerprint match)" '[ "$(key_fp)" = "$KEY_FP_BEFORE" ] && [ -n "$KEY_FP_BEFORE" ]'
check "no encryption-key mismatch reported by n8n" '! docker compose logs --no-color n8n 2>&1 | grep -qi "mismatching encryption keys"'

sec "8b. APP-03A HANDOFF SMOKE (authenticated, synthetic; tokens read from .env, never printed)"
python3 - <<'PY' || FAILED=1
import json, re, urllib.error, urllib.request, uuid
env = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l)
tok, key, conv = env["AUTH_TOKEN_CUSTOMER_A"], f"v1-handoff-{uuid.uuid4().hex[:8]}", "conv-n8n01-smoke"
def post():
    req = urllib.request.Request("http://127.0.0.1:8000/handoffs", method="POST",
        data=json.dumps({"conversation_id": conv, "reason": "human_requested",
                         "summary": "Synthetic: VM smoke test handoff."}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok,
                 "Idempotency-Key": key, "X-Conversation-ID": conv})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read()), r.headers.get("Idempotency-Outcome"), None
    except urllib.error.HTTPError as e:
        return e.code, None, None, e.read()[:200]
s1, b1, o1, _ = post(); s2, b2, o2, _ = post()
for label, s, b, o in (("first", s1, b1, o1), ("replay", s2, b2, o2)):
    print(f"  {label}: HTTP {s} Idempotency-Outcome={o} id={b and b['id']} customer_id={b and b['customer_id']} status={b and b['status']}")
forbidden = re.compile(r"\b(is|are) (now )?(attending|handling)|\bassigned to\b|\bin progress\b|\bbeing (handled|attended)\b", re.I)
checks = [
    ("handoff created 201 pending for CUSTOMER_A", s1 == 201 and o1 == "created" and b1["status"] == "pending" and b1["customer_id"] == "CUSTOMER_A"),
    ("same key replays same handoff id", s2 == 201 and o2 == "replay" and b2["id"] == b1["id"]),
    ("status_message says pending human attention", "pending human attention" in b1["status_message"]),
    ("no false human-attendance wording", not forbidden.search(json.dumps(b1))),
]
for name, ok in checks:
    print(("CHECK PASS: " if ok else "CHECK FAIL: ") + name)
raise SystemExit(0 if all(ok for _, ok in checks) else 1)
PY
echo "handoff rows for this smoke (count|statuses): $(echo "SELECT count(*), string_agg(DISTINCT status, ',') FROM handoffs WHERE conversation_id = 'conv-n8n01-smoke';" | docker compose exec -T db sh -c 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"')"

sec "9. SECRET HYGIENE"
docker compose logs --no-color > "$WORK/compose.log" 2>&1
for var in POSTGRES_PASSWORD AUTH_TOKEN_CUSTOMER_A AUTH_TOKEN_CUSTOMER_B N8N_ENCRYPTION_KEY; do
  V="$(sed -n "s/^$var=//p" .env)"
  echo "$var value: run log $(grep -cF -- "$V" "$LOG"), container logs $(grep -cF -- "$V" "$WORK/compose.log")"
  check "$var not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'
  unset V
done

sec "10. RESULT"
[ "$FAILED" = 0 ] && echo "N8N-01 VM VALIDATION: ALL CHECKS PASS" || { echo "N8N-01 VM VALIDATION: FAILURES"; docker compose logs --no-color --tail 40 n8n; }

sec "11. CLEANUP"
run docker compose down -v
run docker image rm $IMAGES
run docker builder prune -f | tail -1
cd "$HOME"; case "$WORK" in "$HOME"/nexo-n8n01) rm -rf -- "$WORK" ;; esac

sec "12. FINAL STATE"
run docker ps -a; run docker images; run docker volume ls; run docker network ls; run docker system df; run ss -tlnH
run test ! -e "$HOME/nexo-n8n01" && echo "temporary directory removed"
