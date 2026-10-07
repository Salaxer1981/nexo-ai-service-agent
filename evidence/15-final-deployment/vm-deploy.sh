#!/usr/bin/env bash
# FINAL-02 — PERMANENT evaluation deployment of Nexo on the VM + final real evidence. Owner-run, ONE SSH session with
# loopback tunnels: web client :8080, n8n UI :5678, allowlisted control endpoint :8099. stdin = <OpenRouter key line> +
# <control token line> + <git bundle>:
#   { sed -n 's/^OPENROUTER_API_KEY=//p' ../../.env | tr -d '\r\n'; echo; cat raw/control.token; echo; cat raw/final.bundle; } \
#     | ssh -p <SSH_PORT> -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 -o ServerAliveCountMax=6 \
#       -L 127.0.0.1:8080:127.0.0.1:8080 -L 127.0.0.1:5678:127.0.0.1:5678 -L 127.0.0.1:8099:127.0.0.1:8099 <user>@<VM_HOST> \
#       "EXPECTED_SHA=<commit>; BUNDLE_SHA256=<sha>; $(cat vm-deploy.sh)" > raw/run.raw.log 2>&1
# PERMANENT: the stack stays UP at the end (restart: unless-stopped).
#   Persistent: ~/nexo-eval/repo (checkout + .env, mode 600, holds the OpenRouter key and the synthetic credentials),
#   the Docker volumes, ~/nexo-eval-backups (mode 700).
#   Temporary (deleted at the end): ~/nexo-eval-tmp (bundle, control token, raw lead-writer token, logs, control script).
# The raw lead-writer token ends up ONLY in n8n's encrypted credential store; the backend gets its SHA-256.
# The control endpoint (VM loopback :8099, token-protected) runs ONLY fixed actions and has no arbitrary command:
# status/log/DB/audit/n8n reads, stack restart, n8n|backend|db stop/start, 120->150 knowledge change + restore,
# backup + restore, secret scan, finish. If the owner's SSH session drops, it stops itself (heartbeat). The stack then
# stays up and the temporary secrets are still deleted.
set -u
trap '' PIPE
: "${EXPECTED_SHA:?set EXPECTED_SHA}"; : "${BUNDLE_SHA256:?set BUNDLE_SHA256}"
export WORK="$HOME/nexo-eval" TMPD="$HOME/nexo-eval-tmp" BKD="$HOME/nexo-eval-backups"
REPO="$WORK/repo"; LOG="$TMPD/run.log"
FAILED=0
sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
psql_db(){ docker compose exec -T db sh -c 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
n8n_cli(){ docker compose exec -T -u node n8n n8n "$@"; }
health(){ docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")"; }
nets_of(){ docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$(docker compose ps -q "$1")" | tr ' ' '\n' | grep . | sort | tr '\n' ' '; }

sec "0. PRE-CHECKS (VM preflight)"
for d in "$WORK" "$TMPD" "$BKD"; do [ -e "$d" ] && { echo "ABORT: $d exists"; exit 1; }; done
ss -tlnH | grep -qE ':(8000|5678|5432|8080|8099) ' && { echo "ABORT: port 8000/5678/5432/8080/8099 in use"; exit 1; }
docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"' && { echo "ABORT: project nexo exists"; exit 1; }
for v in nexo_db_data nexo_n8n_data; do docker volume inspect "$v" >/dev/null 2>&1 && { echo "ABORT: volume $v exists"; exit 1; }; done
echo "pre-checks passed"
run sh -c '. /etc/os-release; echo "$PRETTY_NAME"'; run docker --version; run docker compose version
run free -m; run df -h /; run docker ps -a; run docker system df; run ss -tlnH
run systemctl is-enabled docker

sec "1. RECEIVE OPENROUTER KEY + CONTROL TOKEN (stdin, never printed) + BUNDLE"
IFS= read -r ORK; IFS= read -r CTL
mkdir -p "$TMPD" "$WORK" "$BKD"; chmod 700 "$TMPD" "$WORK" "$BKD"
( umask 077; printf '%s' "$ORK" > "$TMPD/ork"; printf '%s' "$CTL" > "$TMPD/control.token" )
case "$ORK" in sk-or-*) KEYOK=1 ;; *) KEYOK=0 ;; esac
case "$CTL" in [0-9a-f]*) [ "${#CTL}" -ge 32 ] && CTLOK=1 || CTLOK=0 ;; *) CTLOK=0 ;; esac
unset ORK CTL
[ "$KEYOK" = 1 ] && [ "$CTLOK" = 1 ] || { echo "ABORT: stdin framing invalid"; rm -rf -- "$TMPD" "$WORK" "$BKD"; exit 1; }
echo "key and control token received on stdin: format ok, stored in 600-mode files (values not shown)"
exec > >(tee "$LOG") 2>&1
cat > "$TMPD/final.bundle"
check "bundle sha256 matches the local bundle" '[ "$(sha256sum "$TMPD/final.bundle" | cut -d" " -f1)" = "$BUNDLE_SHA256" ]'

sec "2. CHECKOUT EXACT COMMIT (persistent)"
run git clone -q "$TMPD/final.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$(git -C "$REPO" rev-parse HEAD)" = "$EXPECTED_SHA" ]'
check "working tree clean (no edits)" '[ -z "$(git -C "$REPO" status --porcelain)" ]'
cd "$REPO" || exit 1

sec "3. SECRETS (generated on the VM; persistent .env mode 600; never printed)"
( umask 077
  tok(){ python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  tok > "$TMPD/lead_writer.token"
  LWH="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1]).read().strip().encode()).hexdigest())' "$TMPD/lead_writer.token")"
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nAUTH_TOKEN_CUSTOMER_A=%s\nAUTH_TOKEN_CUSTOMER_B=%s\nN8N_ENCRYPTION_KEY=%s\nLEAD_WRITER_TOKEN_SHA256=%s\nOPENROUTER_API_KEY=%s\n' \
    "$(tok)" "$(tok)" "$(tok)" "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" "$LWH" "$(cat "$TMPD/ork")" > .env
  python3 - "$TMPD/lead_writer.token" "$TMPD/cred.json" <<'PY'
import json, sys
token = open(sys.argv[1]).read().strip()
json.dump([{"id": "NexoLeadWriter01", "name": "nexo-lead-writer", "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": "Bearer " + token}}], open(sys.argv[2], "w"))
PY
)
rm -f "$TMPD/ork"
check "OpenRouter key file removed; key now only in the 600-mode .env" '[ ! -e "$TMPD/ork" ] && [ "$(stat -c %a .env)" = 600 ]'
check ".env is git-ignored in the checkout" 'git check-ignore -q .env'
echo ".env names: $(cut -d= -f1 .env | tr '\n' ' ')"

sec "4. CONFIG + BUILD + START (db, backend, n8n, web)"
check "docker compose config valid (output not printed)" 'docker compose config --quiet'
check "web service has no build args" '[ -z "$(docker compose config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)[\"services\"][\"web\"][\"build\"].get(\"args\") or \"\")")" ]'
run docker compose --progress plain build backend web 2>&1 | grep -E "added [0-9]+ packages|built in|ERROR|error" | head -10
run docker compose up -d --wait --wait-timeout 300 2>&1 | grep -vE 'Pulling fs layer|Downloading|Download complete|Extracting|Pull complete|Waiting|Already exists'
run docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
for s in db backend n8n web; do check "$s healthy" '[ "$(health '"$s"')" = healthy ]'; done
check "restart policy unless-stopped on all services" '[ "$(for s in db backend n8n web; do docker inspect -f "{{.HostConfig.RestartPolicy.Name}}" "$(docker compose ps -q $s)"; done | sort -u)" = unless-stopped ]'

sec "5. MIGRATIONS + SCHEMA"
echo "SELECT version || ' ' || checksum FROM schema_migrations ORDER BY version;" | psql_db > "$TMPD/db_mig.txt"
for f in src/backend/app/migrations/*.sql; do echo "$(basename "$f" .sql) $(sha256sum "$f" | cut -d' ' -f1)"; done > "$TMPD/file_mig.txt"
check "schema_migrations == files 0001..0009 (identical checksums)" 'diff -q "$TMPD/db_mig.txt" "$TMPD/file_mig.txt" >/dev/null && [ "$(wc -l < "$TMPD/db_mig.txt")" = 9 ]'
echo "SELECT 'seed refs: ' || string_agg(reference || '=' || customer_id, ', ' ORDER BY reference) FROM tickets;" | psql_db

sec "6. NETWORK / EXPOSURE / BOUNDARIES"
run ss -tlnH
check "web only 127.0.0.1:8080" '[ "$(docker port "$(docker compose ps -q web)")" = "8080/tcp -> 127.0.0.1:8080" ]'
check "backend only 127.0.0.1:8000; n8n only 127.0.0.1:5678" '[ "$(docker port "$(docker compose ps -q backend)")" = "8000/tcp -> 127.0.0.1:8000" ] && [ "$(docker port "$(docker compose ps -q n8n)")" = "5678/tcp -> 127.0.0.1:5678" ]'
check "db no published port; no :5432 listener" '[ -z "$(docker port "$(docker compose ps -q db)")" ] && ! ss -tlnH | grep -q ":5432 "'
check "public listeners only :9922" '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'
for s in web backend n8n db; do echo "$s networks: $(nets_of $s)"; done
check "web only on nexo_web; n8n only on nexo_automation; db only on nexo_internal" '[ "$(nets_of web)" = "nexo_web " ] && [ "$(nets_of n8n)" = "nexo_automation " ] && [ "$(nets_of db)" = "nexo_internal " ]'
check "web cannot resolve db nor n8n" 'docker compose exec -T web node -e "const d=require(\"dns\");d.lookup(\"db\",e1=>d.lookup(\"n8n\",e2=>process.exit(e1&&e2?0:1)))"'
check "web container: read-only rootfs, non-root, no capabilities" '[ "$(docker inspect -f "{{.HostConfig.ReadonlyRootfs}} {{.Config.User}} {{.HostConfig.CapDrop}}" "$(docker compose ps -q web)")" = "true node [ALL]" ]'

sec "7. REAL n8n: credential + workflow (supported CLI)"
docker compose cp "$TMPD/cred.json" n8n:/tmp/cred.json
run n8n_cli import:credentials --input=/tmp/cred.json
docker compose exec -T n8n rm -f /tmp/cred.json; rm -f "$TMPD/cred.json"
check "temporary credential files deleted (host + container)" '[ ! -e "$TMPD/cred.json" ] && ! docker compose exec -T n8n test -e /tmp/cred.json'
docker compose cp n8n/workflows/nexo-lead-create.json n8n:/tmp/nexo-lead-create.json
run n8n_cli import:workflow --input=/tmp/nexo-lead-create.json
docker compose exec -T n8n rm -f /tmp/nexo-lead-create.json
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
cat > "$TMPD/control.py" <<'PY'
"""FINAL-02 control endpoint: fixed, allowlisted actions only. Bound to VM loopback; reachable only through the owner's tunnel."""
import glob, hmac, json, os, re, shutil, sqlite3, subprocess, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

WORK = os.environ["WORK"]; TMPD = os.environ["TMPD"]; BKD = os.environ["BKD"]
REPO = os.path.join(WORK, "repo"); LOG = os.path.join(TMPD, "run.log")
TOKEN = open(os.path.join(TMPD, "control.token")).read().strip()
SAFE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
KFILE = "knowledge/03_commercial_policy.md"
IDLE_LIMIT = 3 * 3600
state = {"last": time.time(), "stop": False}


def sh(args, inp=None, timeout=900):
    r = subprocess.run(args, cwd=REPO, input=inp, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def note(msg):
    with open(LOG, "a") as f:
        f.write(f"[control {time.strftime('%H:%M:%S')}] {msg}\n")


def env():
    return dict(l.split("=", 1) for l in open(os.path.join(REPO, ".env")).read().splitlines() if "=" in l)


def secrets():
    e = env()
    out = {k: e[k] for k in ("POSTGRES_PASSWORD", "AUTH_TOKEN_CUSTOMER_A", "AUTH_TOKEN_CUSTOMER_B", "N8N_ENCRYPTION_KEY", "OPENROUTER_API_KEY")}
    out["LEAD_WRITER_TOKEN"] = open(os.path.join(TMPD, "lead_writer.token")).read().strip()
    out["CONTROL_TOKEN"] = TOKEN
    return out


def sql(q):
    rc, out, err = sh(["docker", "compose", "exec", "-T", "db", "sh", "-c", 'psql -X -q -t -A -F "|" -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], q)
    return [l.split("|") for l in out.strip().splitlines() if l]


def health():
    out = {}
    for s in ("db", "backend", "n8n", "web"):
        rc, cid, _ = sh(["docker", "compose", "ps", "-a", "-q", s])
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
    d = os.path.join(TMPD, "n8ncopy"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for suffix in ("", "-wal"):
        sh(["docker", "compose", "cp", f"n8n:/home/node/.n8n/database.sqlite{suffix}", d])
    conn = sqlite3.connect(os.path.join(d, "database.sqlite"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(execution_entity)")]
    sel = [c for c in ("id", "status", "finished", "mode", "startedAt") if c in cols]
    rows = conn.execute(f"SELECT {', '.join(sel)} FROM execution_entity WHERE workflowId = 'NexoLeadCreate01' ORDER BY id").fetchall()
    conn.close(); shutil.rmtree(d, ignore_errors=True)
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
    html = urllib.request.urlopen("http://127.0.0.1:8080/", timeout=10).read()
    assets = [html] + [urllib.request.urlopen("http://127.0.0.1:8080" + a.decode(), timeout=10).read()
                       for a in re.findall(rb'(/assets/[A-Za-z0-9._-]+)', html)]
    result["served_bundle"] = count_in_stream(assets, sec)
    rc, cid, _ = sh(["docker", "create", "nexo-web:0.1.0"]); cid = cid.strip()
    p = subprocess.Popen(["docker", "export", cid], stdout=subprocess.PIPE)
    result["web_image_filesystem"] = count_in_stream(iter(lambda: p.stdout.read(1 << 20), b""), sec); p.wait()
    sh(["docker", "rm", cid])
    rc, hist, _ = sh(["docker", "history", "--no-trunc", "nexo-web:0.1.0"])
    rc, insp, _ = sh(["docker", "image", "inspect", "nexo-web:0.1.0"])
    result["web_image_history_config"] = count_in_stream([(hist + insp).encode()], sec)
    result["backups_dir"] = count_in_stream([open(f, "rb").read() for f in glob.glob(os.path.join(BKD, "*.json"))] or [b""], sec)
    total = sum(v for k, d in result.items() if isinstance(d, dict) for v in d.values())
    return {"total_secret_occurrences": total, **result}


def summary():
    return {
        "counts": sql("SELECT (SELECT count(*) FROM tickets), (SELECT count(*) FROM leads), (SELECT count(*) FROM handoffs), (SELECT count(*) FROM chat_conversations);")[0],
        "tickets": sql("SELECT reference, customer_id, priority, status, created_at FROM tickets ORDER BY created_at;"),
        "leads": sql("SELECT id, requested_by_customer_id, company_name, contact_email, workflow_execution_id, created_at FROM leads ORDER BY created_at;"),
        "handoffs": sql("SELECT id, customer_id, reason, status, created_at FROM handoffs ORDER BY created_at;"),
        "pending_ticket_actions": sql("SELECT status, count(*) FROM pending_ticket_actions GROUP BY status ORDER BY status;"),
        "pending_lead_actions": sql("SELECT status, count(*) FROM pending_lead_actions GROUP BY status ORDER BY status;"),
    }


def conversation(cid):
    q = cid.replace("'", "")
    return {
        "chat_conversation": sql(f"SELECT customer_id, action_kind, action_status, revision FROM chat_conversations WHERE conversation_id = '{q}';"),
        "tickets": sql(f"SELECT t.reference, t.customer_id, t.priority, t.status FROM tickets t JOIN pending_ticket_actions a ON a.id = t.source_action_id WHERE a.conversation_id = '{q}';"),
        "leads": sql(f"SELECT l.id, l.requested_by_customer_id, l.workflow_execution_id FROM leads l JOIN pending_lead_actions a ON a.id = l.source_action_id WHERE a.conversation_id = '{q}';"),
        "handoffs": sql(f"SELECT customer_id, reason, status FROM handoffs WHERE conversation_id = '{q}';"),
    }


def svc_stop(name):
    sh(["docker", "compose", "stop", name])
    return {"health": health()}


def svc_start(name):
    sh(["docker", "compose", "start", name]); sh(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "300"])
    return {"health": health(), "webhook_ready_after_s": webhook_ready()}


def stack_restart():
    sh(["docker", "compose", "restart"]); sh(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "300"])
    return {"health": health(), "webhook_ready_after_s": webhook_ready()}


def rag_search(q):
    req = urllib.request.Request("http://127.0.0.1:8000/rag/search", method="POST",
                                 data=json.dumps({"query": q, "top_k": 3}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + env()["AUTH_TOKEN_CUSTOMER_A"]})
    js = json.loads(urllib.request.urlopen(req, timeout=60).read())
    return {"evidence": js.get("evidence"), "matches": [{"reference": m.get("reference"), "score": m.get("score"),
            "has_120": "120 €" in (m.get("text") or m.get("content") or ""), "has_150": "150 €" in (m.get("text") or m.get("content") or "")}
            for m in js.get("matches", [])]}


def ingest():
    rc, out, err = sh(["docker", "compose", "exec", "-T", "backend", "python", "-m", "app.rag_ingest"])
    return (out + err).strip().splitlines()[-1:]


def price150():
    path = os.path.join(REPO, KFILE); text = open(path, encoding="utf-8").read()
    if text.count("120 €") != 1:
        return {"error": "expected exactly one '120 €'"}
    open(path, "w", encoding="utf-8").write(text.replace("120 €", "150 €"))
    rc, diff, _ = sh(["git", "diff", "--", KFILE])
    return {"diff": [l for l in diff.splitlines() if l.startswith(("-D", "+D"))], "ingest": ingest(),
            "db_rows_with_120": sql("SELECT count(*) FROM knowledge_chunks WHERE content LIKE '%120 €%';"),
            "search": rag_search("¿Cuánto cuesta el diagnóstico inicial?")}


def rag_restore():
    sh(["git", "checkout", "--", KFILE])
    rc, st, _ = sh(["git", "status", "--porcelain"])
    return {"git_status_clean": st.strip() == "", "ingest": ingest(),
            "db_rows_with_150": sql("SELECT count(*) FROM knowledge_chunks WHERE content LIKE '%150 €%';"),
            "search": rag_search("¿Cuánto cuesta el diagnóstico inicial?")}


def backup():
    ts = time.strftime("%Y%m%dT%H%M%S"); dump = os.path.join(BKD, f"nexo-db-{ts}.dump")
    with open(dump, "wb") as f:
        p = subprocess.run(["docker", "compose", "exec", "-T", "db", "sh", "-c", 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc'], cwd=REPO, stdout=f)
    os.chmod(dump, 0o600)
    sh(["docker", "compose", "stop", "n8n"])
    n8ndir = os.path.join(BKD, f"n8n-state-{ts}")
    sh(["docker", "compose", "cp", "n8n:/home/node/.n8n", n8ndir])
    sh(["docker", "compose", "start", "n8n"]); sh(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "180", "n8n"])
    snap = summary()
    json.dump(snap, open(os.path.join(BKD, f"snapshot-{ts}.json"), "w"), default=str)
    return {"dump": os.path.basename(dump), "dump_bytes": os.path.getsize(dump), "pg_dump_rc": p.returncode,
            "n8n_state_copied": os.path.isdir(n8ndir), "counts_at_backup": snap["counts"], "webhook_ready_after_s": webhook_ready()}


def restore():
    dumps = sorted(glob.glob(os.path.join(BKD, "nexo-db-*.dump")))
    if not dumps:
        return {"error": "no dump"}
    with open(dumps[-1], "rb") as f:
        p = subprocess.run(["docker", "compose", "exec", "-T", "db", "sh", "-c", 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists'], cwd=REPO, stdin=f, capture_output=True)
    snap = summary()
    return {"restored_from": os.path.basename(dumps[-1]), "pg_restore_rc": p.returncode, "stderr_lines": len(p.stderr.splitlines()),
            "counts_after_restore": snap["counts"], "handoffs_after_restore": [h[2:4] for h in snap["handoffs"]]}


GET = {
    "/status": lambda q: {"health": health(), "idle_s": round(time.time() - state["last"])},
    "/log": lambda q: {"tail": open(LOG, errors="replace").read().splitlines()[-int(q.get("n", ["80"])[0]):]},
    "/db/summary": lambda q: summary(),
    "/n8n/executions": lambda q: n8n_execs(),
    "/scan": lambda q: scan(),
}
POST = {
    "/n8n/stop": lambda: svc_stop("n8n"), "/n8n/start": lambda: svc_start("n8n"),
    "/backend/stop": lambda: svc_stop("backend"), "/backend/start": lambda: svc_start("backend"),
    "/db/stop": lambda: svc_stop("db"), "/db/start": lambda: svc_start("db"),
    "/stack/restart": stack_restart,
    "/rag/price150": price150, "/rag/restore": rag_restore,
    "/backup": backup, "/restore": restore,
    "/finish": lambda: (state.update(stop=True), {"finish": "scheduled: control endpoint stops; stack stays up"})[1],
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
        except Exception as exc:
            return self._send(500, {"error": type(exc).__name__})

    def do_GET(self): self._handle(GET)
    def do_POST(self): self._handle(POST)
    def log_message(self, *a): pass


srv = HTTPServer(("127.0.0.1", 8099), H); srv.timeout = 30
print("control endpoint ready on 127.0.0.1:8099", flush=True)
beat, lost = time.time(), False
while not state["stop"] and time.time() - state["last"] < IDLE_LIMIT:
    srv.handle_request()
    if time.time() - beat >= 60:
        beat = time.time()
        try:
            print(f"[heartbeat {time.strftime('%H:%M:%S')}]", flush=True)
        except OSError:
            lost = True
            break
reason = "finish requested" if state["stop"] else ("SSH session lost" if lost else "idle limit reached")
note("control endpoint stopped: " + reason)
try:
    print("control endpoint stopped: " + reason, flush=True)
except OSError:
    pass
PY
echo "STACK READY FOR FINAL EVIDENCE: web http://127.0.0.1:8080, n8n UI http://127.0.0.1:5678 (via tunnels). Waiting for /finish."
python3 "$TMPD/control.py"

sec "10. FINAL SECRET SCAN OF THIS RUN LOG + LOGS"
docker compose logs --no-color > "$TMPD/compose.log" 2>&1
for var in POSTGRES_PASSWORD AUTH_TOKEN_CUSTOMER_A AUTH_TOKEN_CUSTOMER_B N8N_ENCRYPTION_KEY OPENROUTER_API_KEY; do
  V="$(sed -n "s/^$var=//p" .env)"
  check "$var value not in run log or container logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$TMPD/compose.log")" = 0 ]'
  unset V
done
V="$(cat "$TMPD/lead_writer.token")"; check "lead-writer token not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$TMPD/compose.log")" = 0 ]'; unset V
V="$(cat "$TMPD/control.token")"; check "control token not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$TMPD/compose.log")" = 0 ]'; unset V

sec "11. FINISH (PERMANENT DEPLOYMENT: stack stays up; temporary material removed)"
check "knowledge base is the canonical committed corpus" '[ -z "$(git status --porcelain)" ]'
for s in db backend n8n web; do check "$s healthy at hand-over" '[ "$(health '"$s"')" = healthy ]'; done
echo "SELECT 'hand-over data: tickets=' || (SELECT count(*) FROM tickets) || ' leads=' || (SELECT count(*) FROM leads) || ' handoffs=' || (SELECT count(*) FROM handoffs) || ' knowledge_chunks=' || (SELECT count(*) FROM knowledge_chunks);" | psql_db
[ "$FAILED" = 0 ] && echo "FINAL-02 VM HARNESS: ALL CHECKS PASS" || echo "FINAL-02 VM HARNESS: FAILURES (see CHECK FAIL)"
run docker builder prune -f | tail -1
cd "$HOME"; case "$TMPD" in "$HOME"/nexo-eval-tmp) rm -rf -- "$TMPD" ;; esac
echo "temporary material removed: $([ -e "$HOME/nexo-eval-tmp" ] && echo NO || echo yes) (bundle, control token, raw lead-writer token, logs, control script)"

sec "12. HAND-OVER STATE"
run docker compose -f "$REPO/compose.yaml" --project-directory "$REPO" ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
run ss -tlnH
echo "persistent: $REPO (commit $(git -C "$REPO" rev-parse --short HEAD), .env mode $(stat -c %a "$REPO/.env")); backups: $(ls -1 "$BKD" | tr '\n' ' ')"
echo "control endpoint listening: $(ss -tlnH | grep -c ':8099 ')"
