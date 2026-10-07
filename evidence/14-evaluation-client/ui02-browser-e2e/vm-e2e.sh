#!/usr/bin/env bash
# UI-02 — REAL browser E2E of the Nexo evaluation client on the VM. Owner-run, ONE SSH session that also carries two
# loopback tunnels (web client :8080 and an allowlisted control endpoint :8099). stdin = <OpenRouter key line> +
# <control token line> + <git bundle>:
#   { sed -n 's/^OPENROUTER_API_KEY=//p' ../../../.env | tr -d '\r\n'; echo; cat raw/control.token; echo; cat raw/ui02.bundle; } \
#     | ssh -p 9922 -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=6 -L 127.0.0.1:8080:127.0.0.1:8080 -L 127.0.0.1:8099:127.0.0.1:8099 user@<VM> \
#       "EXPECTED_SHA=<commit>; BUNDLE_SHA256=<sha>; $(cat vm-e2e.sh)" > raw/run.raw.log 2>&1
# REAL: PostgreSQL/pgvector, backend, n8n, OpenRouter x-ai/grok-4.7 + embeddings, web client. No fixture backend.
# The OpenRouter key travels only inside the encrypted SSH stream, lives in 600-mode files, and is deleted at cleanup.
# All other secrets are generated on the VM. Nothing secret is printed. Loopback-only ports. TEMPORARY: full teardown.
# The control endpoint (127.0.0.1:8099, VM loopback) needs the control token and runs ONLY fixed actions:
# status, log tail, read-only DB/audit/n8n queries, n8n stop/start, stack restart, secret scan, teardown.
# There is no arbitrary command. It tears everything down by itself after 3 h without requests.
set -u
# Run-1 lesson: a dropped SSH connection must never leave the stack or secrets behind. Ignore SIGPIPE so that writes to
# the dead connection fail harmlessly; the control endpoint notices the disconnect (heartbeat) and the cleanup still runs.
trap '' PIPE
: "${EXPECTED_SHA:?set EXPECTED_SHA}"; : "${BUNDLE_SHA256:?set BUNDLE_SHA256}"
export WORK="$HOME/nexo-ui02"
REPO="$WORK/repo"; LOG="$WORK/run.log"
FAILED=0
sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
psql_db(){ docker compose exec -T db sh -c 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
n8n_cli(){ docker compose exec -T -u node n8n n8n "$@"; }
health(){ docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")"; }
nets_of(){ docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$(docker compose ps -q "$1")" | tr ' ' '\n' | grep . | sort | tr '\n' ' '; }

sec "0. PRE-CHECKS (VM preflight)"
[ -e "$WORK" ] && { echo "ABORT: $WORK exists"; exit 1; }
ss -tlnH | grep -qE ':(8000|5678|5432|8080|8099) ' && { echo "ABORT: port 8000/5678/5432/8080/8099 in use"; exit 1; }
docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"' && { echo "ABORT: project nexo exists"; exit 1; }
for v in nexo_db_data nexo_n8n_data; do docker volume inspect "$v" >/dev/null 2>&1 && { echo "ABORT: volume $v exists"; exit 1; }; done
echo "pre-checks passed"
run sh -c '. /etc/os-release; echo "$PRETTY_NAME"'; run docker --version; run docker compose version
run free -m; run df -h /; run docker ps -a; run docker system df; run ss -tlnH

sec "1. RECEIVE OPENROUTER KEY + CONTROL TOKEN (stdin, never printed) + BUNDLE"
IFS= read -r ORK; IFS= read -r CTL
mkdir -p "$WORK"; chmod 700 "$WORK"
( umask 077; printf '%s' "$ORK" > "$WORK/ork"; printf '%s' "$CTL" > "$WORK/control.token" )
case "$ORK" in sk-or-*) KEYOK=1 ;; *) KEYOK=0 ;; esac
case "$CTL" in [0-9a-f]*) [ "${#CTL}" -ge 32 ] && CTLOK=1 || CTLOK=0 ;; *) CTLOK=0 ;; esac
unset ORK CTL
[ "$KEYOK" = 1 ] && [ "$CTLOK" = 1 ] || { echo "ABORT: stdin framing (key line / control token line) invalid"; rm -rf -- "$WORK"; exit 1; }
echo "key and control token received on stdin: format ok, stored in 600-mode files (values not shown)"
docker images -q --no-trunc | sort -u > "$WORK/images.before"
exec > >(tee "$LOG") 2>&1
cat > "$WORK/ui02.bundle"
check "bundle sha256 matches the local bundle" '[ "$(sha256sum "$WORK/ui02.bundle" | cut -d" " -f1)" = "$BUNDLE_SHA256" ]'

sec "2. CHECKOUT EXACT COMMIT"
run git clone -q "$WORK/ui02.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$(git -C "$REPO" rev-parse HEAD)" = "$EXPECTED_SHA" ]'
check "working tree clean (no edits)" '[ -z "$(git -C "$REPO" status --porcelain)" ]'
cd "$REPO" || exit 1

sec "3. VM-LOCAL SECRETS (generated; OpenRouter key from the 600-mode file; never printed)"
( umask 077
  tok(){ python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  tok > "$WORK/lead_writer.token"
  LWH="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1]).read().strip().encode()).hexdigest())' "$WORK/lead_writer.token")"
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nAUTH_TOKEN_CUSTOMER_A=%s\nAUTH_TOKEN_CUSTOMER_B=%s\nN8N_ENCRYPTION_KEY=%s\nLEAD_WRITER_TOKEN_SHA256=%s\nOPENROUTER_API_KEY=%s\n' \
    "$(tok)" "$(tok)" "$(tok)" "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" "$LWH" "$(cat "$WORK/ork")" > .env
  python3 - "$WORK/lead_writer.token" "$WORK/cred.json" <<'PY'
import json, sys
token = open(sys.argv[1]).read().strip()
json.dump([{"id": "NexoLeadWriter01", "name": "nexo-lead-writer", "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": "Bearer " + token}}], open(sys.argv[2], "w"))
PY
)
run stat -c '%A %n' .env "$WORK/ork" "$WORK/control.token" "$WORK/lead_writer.token" "$WORK/cred.json"
echo ".env names: $(cut -d= -f1 .env | tr '\n' ' ')"

sec "4. CONFIG + BUILD + START (db, backend, n8n, web)"
check "docker compose config valid (output not printed: it would contain secrets)" 'docker compose config --quiet'
check "web service has no build args" '[ -z "$(docker compose config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)[\"services\"][\"web\"][\"build\"].get(\"args\") or \"\")")" ]'
run docker compose --progress plain build backend web 2>&1 | grep -E "npm ci|added [0-9]+ packages|vite v|built in|tsc|ERROR|error" | head -20
run docker compose up -d --wait --wait-timeout 300 2>&1 | grep -vE 'Pulling fs layer|Downloading|Download complete|Extracting|Pull complete|Waiting|Already exists'
run docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
for s in db backend n8n web; do check "$s healthy" '[ "$(health '"$s"')" = healthy ]'; done
echo "--- web startup: $(docker compose logs --no-color web 2>&1 | grep -o 'nexo-web listening.*')"

sec "5. MIGRATIONS + SCHEMA"
echo "SELECT version || ' ' || checksum FROM schema_migrations ORDER BY version;" | psql_db > "$WORK/db_mig.txt"
for f in src/backend/app/migrations/*.sql; do echo "$(basename "$f" .sql) $(sha256sum "$f" | cut -d' ' -f1)"; done > "$WORK/file_mig.txt"
check "schema_migrations == files 0001..0009 (identical checksums)" 'diff -q "$WORK/db_mig.txt" "$WORK/file_mig.txt" >/dev/null && [ "$(wc -l < "$WORK/db_mig.txt")" = 9 ]'
echo "SELECT 'seed refs: ' || string_agg(reference || '=' || customer_id, ', ' ORDER BY reference) FROM tickets;" | psql_db

sec "6. NETWORK / EXPOSURE / BOUNDARIES"
run ss -tlnH
check "web only 127.0.0.1:8080" '[ "$(docker port "$(docker compose ps -q web)")" = "8080/tcp -> 127.0.0.1:8080" ]'
check "backend only 127.0.0.1:8000; n8n only 127.0.0.1:5678" '[ "$(docker port "$(docker compose ps -q backend)")" = "8000/tcp -> 127.0.0.1:8000" ] && [ "$(docker port "$(docker compose ps -q n8n)")" = "5678/tcp -> 127.0.0.1:5678" ]'
check "db no published port; no :5432 listener" '[ -z "$(docker port "$(docker compose ps -q db)")" ] && ! ss -tlnH | grep -q ":5432 "'
check "public listeners only :9922" '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'
for s in web backend n8n db; do echo "$s networks: $(nets_of $s)"; done
check "web only on nexo_web; n8n only on nexo_automation; db only on nexo_internal" '[ "$(nets_of web)" = "nexo_web " ] && [ "$(nets_of n8n)" = "nexo_automation " ] && [ "$(nets_of db)" = "nexo_internal " ]'
check "web reaches backend /health/ready" 'docker compose exec -T web node -e "fetch(\"http://backend:8000/health/ready\").then(r=>process.exit(r.status===200?0:1)).catch(()=>process.exit(1))"'
check "web cannot resolve db nor n8n" 'docker compose exec -T web node -e "const d=require(\"dns\");d.lookup(\"db\",e1=>d.lookup(\"n8n\",e2=>process.exit(e1&&e2?0:1)))"'
check "web container: read-only rootfs, non-root, no capabilities" '[ "$(docker inspect -f "{{.HostConfig.ReadonlyRootfs}} {{.Config.User}} {{.HostConfig.CapDrop}}" "$(docker compose ps -q web)")" = "true node [ALL]" ]'
docker compose exec -T backend python -c "
from app.config import load_settings; from app.llm import chat_client_from_settings
s = load_settings(); print('runtime config: chat model=%s | client=%r | embeddings=%s | min_score=%s' % (s.openrouter_chat_model, chat_client_from_settings(s), s.rag_embedding_model, s.rag_min_score))"

sec "7. REAL n8n: credential + workflow (supported CLI)"
docker compose cp "$WORK/cred.json" n8n:/tmp/cred.json
run n8n_cli import:credentials --input=/tmp/cred.json
docker compose exec -T n8n rm -f /tmp/cred.json; rm -f "$WORK/cred.json"
check "temporary credential files deleted (host + container)" '[ ! -e "$WORK/cred.json" ] && ! docker compose exec -T n8n test -e /tmp/cred.json'
docker compose cp n8n/workflows/nexo-lead-create.json n8n:/tmp/nexo-lead-create.json
run n8n_cli import:workflow --input=/tmp/nexo-lead-create.json
if n8n_cli publish:workflow --help >/dev/null 2>&1; then ACT="publish:workflow --id=NexoLeadCreate01"; else ACT="update:workflow --id=NexoLeadCreate01 --active=true"; fi
echo "activation command used: n8n $ACT"
run n8n_cli $ACT
run docker compose restart n8n
run docker compose up -d --wait --wait-timeout 180 n8n
check "n8n healthy after activation restart" '[ "$(health n8n)" = healthy ]'

sec "8. RAG INGESTION (REAL embeddings)"
docker compose exec -T backend python -m app.rag_ingest 2>&1 | tail -1
check "web /api/health/ready through the server-side boundary" 'python3 -c "
import urllib.request; r = urllib.request.urlopen(urllib.request.Request(\"http://127.0.0.1:8080/api/health/ready\", headers={\"X-Demo-Session\": \"A\"}), timeout=10); raise SystemExit(0 if r.status == 200 else 1)"'

sec "9. CONTROL ENDPOINT (127.0.0.1:8099, token-protected, allowlisted actions only)"
cat > "$WORK/control.py" <<'PY'
"""UI-02 control endpoint: fixed, allowlisted actions only. Bound to VM loopback; reachable only through the owner's tunnel."""
import hmac, json, os, re, shutil, sqlite3, subprocess, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

WORK = os.environ["WORK"]; REPO = os.path.join(WORK, "repo"); LOG = os.path.join(WORK, "run.log")
TOKEN = open(os.path.join(WORK, "control.token")).read().strip()
SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
IDLE_LIMIT = 3 * 3600
state = {"last": time.time(), "stop": False}


def sh(args, inp=None, timeout=600):
    r = subprocess.run(args, cwd=REPO, input=inp, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def note(msg):
    with open(LOG, "a") as f:
        f.write(f"[control {time.strftime('%H:%M:%S')}] {msg}\n")


def secrets():
    env = dict(l.split("=", 1) for l in open(os.path.join(REPO, ".env")).read().splitlines() if "=" in l)
    out = {k: env[k] for k in ("POSTGRES_PASSWORD", "AUTH_TOKEN_CUSTOMER_A", "AUTH_TOKEN_CUSTOMER_B", "N8N_ENCRYPTION_KEY", "OPENROUTER_API_KEY")}
    out["LEAD_WRITER_TOKEN"] = open(os.path.join(WORK, "lead_writer.token")).read().strip()
    out["CONTROL_TOKEN"] = TOKEN
    return out


def sql(q):
    rc, out, err = sh(["docker", "compose", "exec", "-T", "db", "sh", "-c", 'psql -X -q -t -A -F "|" -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], q)
    return [l.split("|") for l in out.strip().splitlines() if l]


def health():
    out = {}
    for s in ("db", "backend", "n8n", "web"):
        rc, cid, _ = sh(["docker", "compose", "ps", "-q", s])
        rc, st, _ = sh(["docker", "inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", cid.strip()]) if cid.strip() else (1, "absent", "")
        out[s] = st.strip()
    return out


def webhook_ready(limit=90):
    start = time.monotonic()
    while time.monotonic() - start < limit:
        req = urllib.request.Request("http://127.0.0.1:5678/webhook/nexo-lead-create", data=b'{"probe":true}', method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return round(time.monotonic() - start, 1)
        except Exception:
            pass
        time.sleep(1)
    return None


def n8n_execs():
    d = os.path.join(WORK, "n8ncopy"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for suffix in ("", "-wal"):
        sh(["docker", "compose", "cp", f"n8n:/home/node/.n8n/database.sqlite{suffix}", d])
    conn = sqlite3.connect(os.path.join(d, "database.sqlite"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(execution_entity)")]
    sel = [c for c in ("id", "status", "finished", "mode", "startedAt") if c in cols]
    rows = conn.execute(f"SELECT {', '.join(sel)} FROM execution_entity WHERE workflowId = 'NexoLeadCreate01' ORDER BY id").fetchall()
    return [dict(zip(sel, r)) for r in rows]


def audit(rid):
    rc, out, _ = sh(["docker", "compose", "logs", "--no-color", "backend"])
    found = []
    for line in out.splitlines():
        if '{"ts"' in line:
            e = json.loads(line[line.index('{"ts"'):])
            if e.get("request_id") == rid:
                found.append(e)
    return found


def count_in_stream(chunks, needles):
    counts = {k: 0 for k in needles}; tail = b""; keep = max(len(v) for v in needles.values())
    for chunk in chunks:
        buf = tail + chunk
        for k, v in needles.items():
            counts[k] += buf.count(v)
        tail = buf[-keep:]
    return counts


def scan():
    sec = {k: v.encode() for k, v in secrets().items()}
    result = {}
    for svc in ("backend", "web", "n8n", "db"):
        rc, out, err = sh(["docker", "compose", "logs", "--no-color", svc])
        result[f"logs:{svc}"] = count_in_stream([(out + err).encode()], sec)
    result["run_log"] = count_in_stream([open(LOG, "rb").read()], sec)
    # served bundle: index + every asset it references, fetched like a browser through the web boundary
    html = urllib.request.urlopen("http://127.0.0.1:8080/", timeout=10).read()
    assets = [html] + [urllib.request.urlopen("http://127.0.0.1:8080" + a.decode(), timeout=10).read()
                       for a in re.findall(rb'(/assets/[A-Za-z0-9._-]+)', html)]
    result["served_bundle"] = count_in_stream(assets, sec)
    result["served_bundle_files"] = len(assets)
    # web image: the merged filesystem of a stopped container created from it + its history and config
    rc, cid, _ = sh(["docker", "create", "nexo-web:0.1.0"]); cid = cid.strip()
    p = subprocess.Popen(["docker", "export", cid], stdout=subprocess.PIPE)
    result["web_image_filesystem"] = count_in_stream(iter(lambda: p.stdout.read(1 << 20), b""), sec); p.wait()
    sh(["docker", "rm", cid])
    rc, hist, _ = sh(["docker", "history", "--no-trunc", "nexo-web:0.1.0"])
    rc, insp, _ = sh(["docker", "image", "inspect", "nexo-web:0.1.0"])
    result["web_image_history_config"] = count_in_stream([(hist + insp).encode()], sec)
    result["web_image_env_names"] = [e.split("=")[0] for e in json.loads(insp)[0]["Config"]["Env"]]
    total = sum(v for k, d in result.items() if isinstance(d, dict) for v in d.values())
    return {"total_secret_occurrences": total, **result}


def summary():
    return {
        "counts": sql("SELECT (SELECT count(*) FROM tickets), (SELECT count(*) FROM leads), (SELECT count(*) FROM handoffs), (SELECT count(*) FROM chat_conversations);")[0],
        "tickets": sql("SELECT reference, customer_id, priority, status, (source_action_id IS NOT NULL) FROM tickets ORDER BY created_at;"),
        "leads": sql("SELECT id, requested_by_customer_id, company_name, contact_email, workflow_execution_id, source_action_id FROM leads ORDER BY created_at;"),
        "handoffs": sql("SELECT id, customer_id, conversation_id, reason, status FROM handoffs ORDER BY created_at;"),
        "pending_ticket_actions": sql("SELECT status, count(*) FROM pending_ticket_actions GROUP BY status ORDER BY status;"),
        "pending_lead_actions": sql("SELECT status, count(*) FROM pending_lead_actions GROUP BY status ORDER BY status;"),
    }


def conversation(cid):
    q = cid.replace("'", "")
    return {
        "chat_conversation": sql(f"SELECT customer_id, action_kind, action_status, revision FROM chat_conversations WHERE conversation_id = '{q}';"),
        "ticket_actions": sql(f"SELECT id, customer_id, status FROM pending_ticket_actions WHERE conversation_id = '{q}' ORDER BY created_at;"),
        "lead_actions": sql(f"SELECT id, customer_id, status FROM pending_lead_actions WHERE conversation_id = '{q}' ORDER BY created_at;"),
        "tickets": sql(f"SELECT t.reference, t.customer_id, t.priority, t.status FROM tickets t JOIN pending_ticket_actions a ON a.id = t.source_action_id WHERE a.conversation_id = '{q}';"),
        "leads": sql(f"SELECT l.id, l.requested_by_customer_id, l.workflow_execution_id FROM leads l JOIN pending_lead_actions a ON a.id = l.source_action_id WHERE a.conversation_id = '{q}';"),
        "handoffs": sql(f"SELECT customer_id, reason, status FROM handoffs WHERE conversation_id = '{q}';"),
    }


def stack_restart():
    sh(["docker", "compose", "restart"]); sh(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "300"])
    return {"health": health(), "webhook_ready_after_s": webhook_ready()}


def n8n_start():
    sh(["docker", "compose", "start", "n8n"]); sh(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "180", "n8n"])
    return {"health": health(), "webhook_ready_after_s": webhook_ready()}


GET = {
    "/status": lambda q: {"health": health(), "idle_s": round(time.time() - state["last"])},
    "/log": lambda q: {"tail": open(LOG, errors="replace").read().splitlines()[-int(q.get("n", ["80"])[0]):]},
    "/db/summary": lambda q: summary(),
    "/n8n/executions": lambda q: n8n_execs(),
    "/scan": lambda q: scan(),
}
POST = {
    "/n8n/stop": lambda: (sh(["docker", "compose", "stop", "n8n"]), {"health": health()})[1],
    "/n8n/start": n8n_start,
    "/stack/restart": stack_restart,
    "/teardown": lambda: (state.update(stop=True), {"teardown": "scheduled"})[1],
}


class H(BaseHTTPRequestHandler):
    def _auth(self):
        return hmac.compare_digest(self.headers.get("X-Control-Token", ""), TOKEN)

    def _send(self, code, body):
        data = json.dumps(body, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def _handle(self, table):
        if not self._auth():
            return self._send(401, {"detail": "unauthorized"})
        u = urlparse(self.path); q = parse_qs(u.query); state["last"] = time.time()
        try:
            if table is GET and u.path in ("/db/conversation", "/audit"):
                key = (q.get("id") or q.get("rid") or [""])[0]
                if not SAFE.match(key):
                    return self._send(400, {"detail": "bad id"})
                note(f"{self.command} {u.path} {key}")
                return self._send(200, conversation(key) if u.path == "/db/conversation" else audit(key))
            fn = table.get(u.path)
            if not fn:
                return self._send(404, {"detail": "not allowed"})
            note(f"{self.command} {u.path}")
            return self._send(200, fn(q) if table is GET else fn())
        except Exception as exc:  # report the failure class only
            return self._send(500, {"error": type(exc).__name__})

    def do_GET(self): self._handle(GET)
    def do_POST(self): self._handle(POST)
    def log_message(self, *a): pass


srv = HTTPServer(("127.0.0.1", 8099), H); srv.timeout = 30
print("control endpoint ready on 127.0.0.1:8099", flush=True)
beat, lost = time.time(), False
while not state["stop"] and time.time() - state["last"] < IDLE_LIMIT:
    srv.handle_request()
    if time.time() - beat >= 60:  # heartbeat through the SSH stream: a write error means the owner's session is gone
        beat = time.time()
        try:
            print(f"[heartbeat {time.strftime('%H:%M:%S')}]", flush=True)
        except OSError:
            lost = True
            break
reason = "teardown requested" if state["stop"] else ("SSH session lost: automatic teardown" if lost else "idle limit reached")
note("control endpoint stopped: " + reason)
try:
    print("control endpoint stopped: " + reason, flush=True)
except OSError:
    pass
PY
echo "STACK READY FOR BROWSER E2E: web http://127.0.0.1:8080 (via tunnel). Waiting for /teardown (auto-teardown after 3 h idle)."
python3 "$WORK/control.py"

sec "10. FINAL SECRET SCAN OF THIS RUN LOG (before cleanup)"
docker compose logs --no-color > "$WORK/compose.log" 2>&1
for var in POSTGRES_PASSWORD AUTH_TOKEN_CUSTOMER_A AUTH_TOKEN_CUSTOMER_B N8N_ENCRYPTION_KEY OPENROUTER_API_KEY; do
  V="$(sed -n "s/^$var=//p" .env)"
  check "$var value not in run log or container logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'
  unset V
done
V="$(cat "$WORK/lead_writer.token")"; check "lead-writer token not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'; unset V
V="$(cat "$WORK/control.token")"; check "control token not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'; unset V
echo "SELECT 'final: tickets=' || (SELECT count(*) FROM tickets) || ' leads=' || (SELECT count(*) FROM leads) || ' handoffs=' || (SELECT count(*) FROM handoffs);" | psql_db
[ "$FAILED" = 0 ] && echo "UI-02 VM HARNESS: ALL HARNESS CHECKS PASS" || echo "UI-02 VM HARNESS: FAILURES (see CHECK FAIL)"

sec "11. CLEANUP (temporary validation: full teardown)"
run docker compose down -v 2>&1 | tail -6
docker images -q --no-trunc | sort -u > "$WORK/images.after"
NEW_IMAGES="$(comm -13 "$WORK/images.before" "$WORK/images.after" | tr '\n' ' ')"
[ -n "$NEW_IMAGES" ] && run docker image rm -f $NEW_IMAGES | tail -6
run docker builder prune -f | tail -1
cd "$HOME"; case "$WORK" in "$HOME"/nexo-ui02) rm -rf -- "$WORK" ;; esac

sec "12. FINAL STATE"
run docker ps -a; run docker images; run docker volume ls; run docker system df; run ss -tlnH
echo "nexo containers: $(docker ps -aq --filter label=com.docker.compose.project=nexo | wc -l)"
ss -tlnH | grep -qE ':(8000|5432|5678|8080|8099) ' && echo "LISTENER STILL PRESENT" || echo "no :8000/:5432/:5678/:8080/:8099 listener"
test ! -e "$HOME/nexo-ui02" && echo "temporary directory removed (checkout, .env, key, tokens, bundle, control script)"
