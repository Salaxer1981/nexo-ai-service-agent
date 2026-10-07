#!/usr/bin/env bash
# APP-03BV1 — temporary VM validation of the lead flow with REAL n8n 2.42.3. Owner-run, one SSH session:
#   ssh -p 9922 user@<VM> "EXPECTED_SHA=<commit>; $(cat vm-validate.sh)" < leads.bundle > raw/run.raw.log 2>&1
# All secrets are generated on the VM; the backend gets only the SHA-256 of the lead-writer token, the raw token
# goes only into n8n's encrypted credential store (and the harness's 600-mode temp file for negative tests).
# Nothing is printed raw; no LLM calls; only 127.0.0.1 exposure; full cleanup. No application/workflow edits.
set -u
: "${EXPECTED_SHA:?set EXPECTED_SHA}"
export WORK="$HOME/nexo-app03bv1"
REPO="$WORK/repo"; LOG="$WORK/run.log"
IMAGES="nexo-backend:0.1.0 pgvector/pgvector:0.8.7-pg17-bookworm n8nio/n8n:2.42.3"
FAILED=0
sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
n8n_cli(){ docker compose exec -T -u node n8n n8n "$@"; }
psql_db(){ docker compose exec -T db sh -c 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }
drv(){ python3 "$WORK/driver.py" "$1" || FAILED=1; }
health(){ docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$1")"; }
nets_of(){ docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$(docker compose ps -q "$1")" | tr ' ' '\n' | grep . | sort | tr '\n' ' '; }
keyfp(){ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$(docker compose ps -q n8n)" | sed -n 's/^N8N_ENCRYPTION_KEY=//p' | sha256sum | cut -c1-16; }

sec "0. PRE-CHECKS"
[ -e "$WORK" ] && { echo "ABORT: $WORK exists"; exit 1; }
ss -tlnH | grep -qE ':(8000|5678) ' && { echo "ABORT: port 8000/5678 in use"; exit 1; }
docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"' && { echo "ABORT: project nexo exists"; exit 1; }
for v in nexo_db_data nexo_n8n_data; do docker volume inspect "$v" >/dev/null 2>&1 && { echo "ABORT: volume $v exists"; exit 1; }; done
echo "pre-checks passed"; run docker system df; run ss -tlnH

mkdir -p "$WORK"; chmod 700 "$WORK"; exec > >(tee "$LOG") 2>&1

sec "1. CHECKOUT EXACT COMMIT"
cat > "$WORK/leads.bundle"
run git clone -q "$WORK/leads.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$(git -C "$REPO" rev-parse HEAD)" = "$EXPECTED_SHA" ]'
check "working tree clean (no edits)" '[ -z "$(git -C "$REPO" status --porcelain)" ]'
cd "$REPO" || exit 1

sec "2. VM-LOCAL SECRETS (generated; never printed)"
( umask 077
  tok(){ python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  tok > "$WORK/lead_writer.token"
  LWH="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1]).read().strip().encode()).hexdigest())' "$WORK/lead_writer.token")"
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nAUTH_TOKEN_CUSTOMER_A=%s\nAUTH_TOKEN_CUSTOMER_B=%s\nN8N_ENCRYPTION_KEY=%s\nLEAD_WRITER_TOKEN_SHA256=%s\n' \
    "$(tok)" "$(tok)" "$(tok)" "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" "$LWH" > .env
  python3 - "$WORK/lead_writer.token" "$WORK/cred.json" <<'PY'
import json, sys
token = open(sys.argv[1]).read().strip()
json.dump([{"id": "NexoLeadWriter01", "name": "nexo-lead-writer", "type": "httpHeaderAuth",
            "data": {"name": "Authorization", "value": "Bearer " + token}}], open(sys.argv[2], "w"))
PY
)
run stat -c '%A %n' .env "$WORK/lead_writer.token" "$WORK/cred.json"
echo ".env names: $(cut -d= -f1 .env | tr '\n' ' ')"
check ".env holds no raw lead-writer token (hash only)" '! grep -qF "$(cat "$WORK/lead_writer.token")" .env'

sec "3. CONFIG + BUILD + START (db, backend, n8n)"
check "docker compose config valid" 'docker compose config --quiet'
run docker compose --progress plain build backend 2>&1 | tail -3
run docker compose up -d --wait --wait-timeout 300
run docker compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
for s in db backend n8n; do check "$s healthy" '[ "$(health '"$s"')" = healthy ]'; done
check "backend /health/ready 200" '[ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/health/ready)" = 200 ]'
check "n8n /healthz 200" '[ "$(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:5678/healthz)" = 200 ]'
run n8n_cli --version
echo "--- backend startup:"; docker compose logs --no-color backend 2>&1 | grep -E 'migrations applied|provisioned' | sed -E 's/^[^|]*\| //'

sec "4. MIGRATIONS 0001-0006 + CHECKSUMS"
echo "SELECT version || ' ' || checksum FROM schema_migrations ORDER BY version;" | psql_db > "$WORK/db_mig.txt"
for f in src/backend/app/migrations/*.sql; do echo "$(basename "$f" .sql) $(sha256sum "$f" | cut -d' ' -f1)"; done > "$WORK/file_mig.txt"
cat "$WORK/db_mig.txt"
check "schema_migrations == files 0001..0006 (identical checksums)" 'diff -q "$WORK/db_mig.txt" "$WORK/file_mig.txt" >/dev/null && [ "$(wc -l < "$WORK/db_mig.txt")" = 6 ]'

sec "5. NETWORK / EXPOSURE / ENV BOUNDARIES"
run ss -tlnH
check "backend only 127.0.0.1:8000" '[ "$(docker port "$(docker compose ps -q backend)")" = "8000/tcp -> 127.0.0.1:8000" ]'
check "n8n only 127.0.0.1:5678" '[ "$(docker port "$(docker compose ps -q n8n)")" = "5678/tcp -> 127.0.0.1:5678" ]'
check "db no published port" '[ -z "$(docker port "$(docker compose ps -q db)")" ]'
check "no :5432 host listener" '! ss -tlnH | grep -q ":5432 "'
check "public listeners only :9922" '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'
for s in n8n backend db; do echo "$s networks: $(nets_of $s)"; done
check "n8n only on nexo_automation" '[ "$(nets_of n8n)" = "nexo_automation " ]'
check "backend on automation + internal" '[ "$(nets_of backend)" = "nexo_automation nexo_internal " ]'
check "db only on nexo_internal" '[ "$(nets_of db)" = "nexo_internal " ]'
check "n8n reaches backend /health" 'docker compose exec -T n8n node -e "fetch(\"http://backend:8000/health\").then(r=>process.exit(r.status===200?0:1)).catch(()=>process.exit(1))"'
check "n8n cannot resolve db" 'docker compose exec -T n8n node -e "require(\"dns\").lookup(\"db\",e=>process.exit(e?0:1))"'
benv(){ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$(docker compose ps -q backend)"; }
check "backend env has NO raw lead-writer token" '! benv | grep -qF "$(cat "$WORK/lead_writer.token")"'
check "backend env LEAD_WRITER_TOKEN_SHA256 = sha256(raw token)" '[ "$(benv | sed -n "s/^LEAD_WRITER_TOKEN_SHA256=//p")" = "$(python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1]).read().strip().encode()).hexdigest())" "$WORK/lead_writer.token")" ]'
n8nenv(){ docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$(docker compose ps -q n8n)" | cut -d= -f1 | tr '\n' ' '; }
echo "n8n env names: $(n8nenv)"
check "n8n env has no POSTGRES_/AUTH_TOKEN_/LEAD_ vars" '! n8nenv | tr " " "\n" | grep -qE "^(POSTGRES_|AUTH_TOKEN_|LEAD_)"'

sec "6. DRIVER (host python3 stdlib; secrets read from files, never printed)"
cat > "$WORK/driver.py" <<'PY'
"""APP-03BV1 checks against the REAL stack (backend 127.0.0.1:8000, real n8n 127.0.0.1:5678)."""
import hashlib, json, os, shutil, sqlite3, subprocess, sys, threading, urllib.error, urllib.request, uuid

WORK, RUN = os.environ["WORK"], os.environ["NEXO_RUN_ID"]
BASE, HOOK = "http://127.0.0.1:8000", "http://127.0.0.1:5678/webhook/nexo-lead-create"
ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l)
TOK = {"A": ENV["AUTH_TOKEN_CUSTOMER_A"], "B": ENV["AUTH_TOKEN_CUSTOMER_B"]}
SVC = open(os.path.join(WORK, "lead_writer.token")).read().strip()
SECRETS = [TOK["A"], TOK["B"], SVC, ENV["POSTGRES_PASSWORD"], ENV["N8N_ENCRYPTION_KEY"]]
STATE_FILE = os.path.join(WORK, "state.json")
DRAFT = {"company_name": "Asesoria Ejemplo VM (synthetic)", "contact_name": "Luis (synthetic)",
         "contact_email": "luis@example.test", "need": "Synthetic: automate client enquiries for an 18-person firm."}
FAILED = []

def state():
    return json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}

def save(**kw):
    s = state(); s.update(kw); json.dump(s, open(STATE_FILE, "w"))

def http(method, url, token=None, body=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if token is not None:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            status, raw, hdrs = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), e.headers
    text = raw.decode("utf-8", "replace")
    assert not any(s in text for s in SECRETS), "secret in response body"
    try:
        js = json.loads(text)
    except ValueError:
        js = None
    return status, js, hdrs

def check(name, ok, detail=""):
    print(("CHECK PASS: " if ok else "CHECK FAIL: ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILED.append(name)

def show(label, status, js, hdrs=None):
    keep = ("pending_action_id", "status", "id", "workflow_execution_id", "requested_by_customer_id", "code",
            "upstream_code", "lead_id", "idempotency")
    shown = {k: js[k] for k in keep if isinstance(js, dict) and k in js}
    out = hdrs.get("Idempotency-Outcome") if hdrs else None
    print(f"  {label}: HTTP {status}" + (f" Idempotency-Outcome={out}" if out else "") + f" {json.dumps(shown)}")

def sql(q):
    r = subprocess.run(["docker", "compose", "exec", "-T", "db", "sh", "-c",
                        'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], input=q, capture_output=True, text=True)
    return r.stdout.strip()

def leads_count():
    return int(sql("SELECT count(*) FROM leads;"))

def action_status(aid):
    return sql(f"SELECT status FROM pending_lead_actions WHERE id = '{aid}';")

def n8n_db():
    """Read-only COPY of n8n's SQLite DB (db + WAL) for evidence; deleted with WORK."""
    d = os.path.join(WORK, "n8ncopy"); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    for suffix in ("", "-wal"):  # main DB + WAL; -shm is rebuilt by SQLite
        subprocess.run(["docker", "compose", "cp", f"n8n:/home/node/.n8n/database.sqlite{suffix}", d],
                       capture_output=True)
    return sqlite3.connect(os.path.join(d, "database.sqlite"))

def cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]

def executions():
    conn = n8n_db()
    c = cols(conn, "execution_entity")
    sel = [x for x in ("id", "workflowId", "status", "finished", "mode") if x in c]
    rows = conn.execute(f"SELECT {', '.join(sel)} FROM execution_entity WHERE workflowId = 'NexoLeadCreate01' ORDER BY id").fetchall()
    return [dict(zip(sel, r)) for r in rows]

def prepare(who, draft, conv):
    return http("POST", BASE + "/leads/prepare", TOK[who], draft, {"X-Conversation-ID": conv})

def confirm(who, p, key, rid=None, conv=None):
    h = {"Idempotency-Key": key}
    if rid: h["X-Request-ID"] = rid
    if conv: h["X-Conversation-ID"] = conv
    return http("POST", BASE + "/leads/confirm", TOK[who],
                {"pending_action_id": p["pending_action_id"], "payload_hash": p["payload_hash"]}, h)

def envelope(p, key, lead=None):
    return {"pending_action_id": p["pending_action_id"], "idempotency_key": key, "payload_hash": p["payload_hash"],
            "lead": lead or p["summary"]}

def internal(token, p, key, lead=None, payload_hash=None):
    return http("POST", BASE + "/internal/leads", token, {
        "pending_action_id": p["pending_action_id"], "payload_hash": payload_hash or p["payload_hash"],
        "lead": lead or p["summary"], "workflow_execution_id": "direct-attempt"}, {"Idempotency-Key": key})

# ----------------------------------------------------------------------------------------------
def n8n_state():
    conn = n8n_db()
    cc = cols(conn, "credentials_entity")
    cred = conn.execute("SELECT id, name, type, data FROM credentials_entity WHERE name = 'nexo-lead-writer'").fetchall()
    print(f"  credentials_entity rows named nexo-lead-writer: {[(r[0], r[1], r[2]) for r in cred]}")
    check("credential nexo-lead-writer present (id NexoLeadWriter01, type httpHeaderAuth)",
          len(cred) == 1 and cred[0][0] == "NexoLeadWriter01" and cred[0][2] == "httpHeaderAuth")
    check("credential stored ENCRYPTED (raw token not in n8n DB)", bool(cred) and SVC not in str(cred[0][3]) and "Bearer" not in str(cred[0][3]))
    wc = cols(conn, "workflow_entity")
    sel = [x for x in ("id", "name", "active", "activeVersionId") if x in wc]
    wf = conn.execute(f"SELECT {', '.join(sel)} FROM workflow_entity WHERE id = 'NexoLeadCreate01'").fetchall()
    print(f"  workflow_entity: {[dict(zip(sel, r)) for r in wf]}")
    if len(sys.argv) > 2 and sys.argv[2] == "expect-workflow":
        check("workflow NexoLeadCreate01 present", len(wf) == 1)

def webhook_probe():
    # Run 1 finding: n8n's /healthz turns healthy BEFORE published workflows' webhooks are registered.
    # Poll (bounded) while n8n itself answers 404 "not registered"; record how long registration took.
    import time
    start = time.monotonic()
    for _ in range(90):
        s, js, h = http("POST", HOOK, None, {"probe": True}, {"X-Request-ID": f"v1-{RUN}-probe"})
        if s != 404:
            break
        time.sleep(1)
    print(f"  webhook registration observed after ~{time.monotonic() - start:.1f}s past n8n 'healthy'")
    show("webhook probe (incomplete envelope)", s, js, h)
    check("workflow ACTIVE: real n8n answers 400 invalid_envelope from its Respond node", s == 400 and (js or {}).get("code") == "invalid_envelope")

def journey():
    conv, key, rid = f"v1-lead-{RUN}", f"lk-{RUN}-main", f"v1-{RUN}-main"
    before, ex_before = leads_count(), len(executions())
    s, p, h = prepare("A", DRAFT, conv); show("A. prepare", s, p, h)
    check("prepare 201, pending, summary + 64-hex payload_hash", s == 201 and p["status"] == "pending"
          and len(p["payload_hash"]) == 64 and p["summary"] == DRAFT and p["confirmation_required"] is True)
    check("prepare: lead count unchanged", leads_count() == before)
    check("prepare: pending action row in DB", action_status(p["pending_action_id"]) == "pending")
    s, lead, h = confirm("A", p, key, rid, conv); show("B. confirm", s, lead, h)
    ok = s == 201 and h.get("Idempotency-Outcome") == "created"
    check("confirm 201 created", ok)
    if not ok:
        return
    exec_id = lead["workflow_execution_id"]
    row = sql(f"SELECT id || '|' || requested_by_customer_id || '|' || source_action_id || '|' || workflow_execution_id "
              f"FROM leads WHERE id = '{lead['id']}';")
    print(f"  PostgreSQL lead row: {row}")
    check("lead row = response id, CUSTOMER_A, same action, same execution id",
          row == f"{lead['id']}|CUSTOMER_A|{p['pending_action_id']}|{exec_id}")
    check("exactly one new lead", leads_count() == before + 1)
    check("action consumed", action_status(p["pending_action_id"]) == "consumed")
    check("workflow_execution_id is NOT a FakeN8n id", not exec_id.startswith("fake-"), exec_id)
    ex = executions()
    match = [e for e in ex if str(e.get("id")) == exec_id]
    print(f"  n8n execution_entity for NexoLeadCreate01 (new): {ex[ex_before:]}")
    check("REAL n8n execution with that id exists for workflow NexoLeadCreate01", len(match) == 1, str(match))
    check("that n8n execution finished successfully", bool(match) and (match[0].get("status") == "success" or match[0].get("finished") in (1, True)))
    check("exactly one new n8n execution", len(ex) == ex_before + 1)
    save(main={"p": p, "key": key, "lead": lead, "rid": rid, "conv": conv})

def bypass():
    m = state()["main"]
    before = leads_count()
    for path in ("/leads", "/lead", "/leads/create"):
        s, js, h = http("POST", BASE + path, TOK["A"], DRAFT, {"Idempotency-Key": f"lk-{RUN}-b"})
        check(f"no public direct route {path} (404/405)", s in (404, 405), str(s))
    for label, token in (("no token", None), ("CUSTOMER_A token", TOK["A"]), ("CUSTOMER_B token", TOK["B"]),
                         ("random token", "x" * 43)):
        s, js, h = internal(token, m["p"], m["key"]); show(f"/internal/leads with {label}", s, js, h)
        check(f"/internal/leads with {label} -> 401", s == 401)
    s, u, h = prepare("A", {**DRAFT, "need": "Synthetic: unconfirmed"}, f"v1-unconf-{RUN}")
    s, js, h = internal(SVC, u, f"lk-{RUN}-u"); show("service token + UNCONFIRMED action", s, js, h)
    check("service token + unconfirmed action -> 409 action_not_confirmed", s == 409 and js.get("code") == "action_not_confirmed")
    s, js, h = internal(SVC, m["p"], f"lk-{RUN}-wrong"); show("service token + wrong key", s, js, h)
    check("service token + wrong key -> 409", s == 409)
    s, js, h = internal(SVC, m["p"], m["key"], lead={**m["p"]["summary"], "need": "Altered"}); show("service token + altered payload", s, js, h)
    check("service token + altered payload -> 409 (no write)", s == 409)
    check("no bypass attempt created a lead", leads_count() == before)
    save(unconfirmed=u)

def idempotency():
    m = state()["main"]
    before, ex_before = leads_count(), len(executions())
    s, js, h = confirm("A", m["p"], m["key"]); show("A. same key + same request", s, js, h)
    check("A: replay, same lead id", s == 201 and h.get("Idempotency-Outcome") == "replay" and js["id"] == m["lead"]["id"])
    check("A: no new n8n execution (answered from PostgreSQL)", len(executions()) == ex_before)
    s, js, h = confirm("A", m["p"], f"lk-{RUN}-newkey"); show("C. same action + new key", s, js, h)
    check("C: 409 confirmation_already_used + same lead_id", s == 409 and js.get("code") == "confirmation_already_used" and js.get("lead_id") == m["lead"]["id"])
    s, o, h = prepare("A", {**DRAFT, "need": "Synthetic: other need"}, f"v1-other-{RUN}")
    s, js, h = confirm("A", o, m["key"]); show("D. same key + different action", s, js, h)
    check("D: 409 idempotency_key_conflict", s == 409 and js.get("code") == "idempotency_key_conflict")
    check("A/C/D created no lead", leads_count() == before)

def webhook_direct():
    m, u = state()["main"], state()["unconfirmed"]
    before = leads_count()
    s, js, h = http("POST", HOOK, None, envelope(u, f"lk-{RUN}-hook-u"), {"X-Request-ID": f"v1-{RUN}-hook-u"})
    show("webhook called directly for UNCONFIRMED action", s, js, h)
    check("webhook cannot create an unconfirmed lead (409 action_not_confirmed via n8n)", s == 409 and (js or {}).get("code") == "action_not_confirmed")
    s, js, h = http("POST", HOOK, None, envelope(m["p"], m["key"]), {"X-Request-ID": f"v1-{RUN}-dup"})
    show("B. duplicate delivery of the consumed main action into n8n", s, js, h)
    check("B: duplicate delivery -> 201 replay, same lead", s == 201 and (js or {}).get("idempotency") == "replay" and js.get("id") == m["lead"]["id"])
    check("webhook calls created no lead", leads_count() == before)

def fail1():
    before = leads_count()
    out = {}
    for name in ("X", "Y"):
        s, p, h = prepare("A", {**DRAFT, "need": f"Synthetic: failure case {name}"}, f"v1-fail{name}-{RUN}")
        key = f"lk-{RUN}-{name}"
        s, js, h = confirm("A", p, key); show(f"confirm {name} while n8n is STOPPED", s, js, h)
        check(f"{name}: 503 lead_not_confirmed (no false success)", s == 503 and js.get("code") == "lead_not_confirmed" and "id" not in js)
        check(f"{name}: action stays confirmed", action_status(p["pending_action_id"]) == "confirmed")
        out[name] = {"p": p, "key": key}
    s, js, h = confirm("A", out["X"]["p"], f"lk-{RUN}-X-other"); show("X with a different key", s, js, h)
    check("different key on confirmed action -> 409 confirmation_in_progress", s == 409 and js.get("code") == "confirmation_in_progress")
    check("no lead while n8n down", leads_count() == before)
    save(fail=out)

def fail2():
    f = state()["fail"]; before = leads_count()
    s, js, h = confirm("A", f["X"]["p"], f["X"]["key"]); show("X retry same key after n8n is back", s, js, h)
    check("X: retry -> 201 created through real n8n", s == 201 and h.get("Idempotency-Outcome") == "created" and not js["workflow_execution_id"].startswith("fake-"))
    s, hooked, h = http("POST", HOOK, None, envelope(f["Y"]["p"], f["Y"]["key"]), {"X-Request-ID": f"v1-{RUN}-lost"})
    show("E. Y delivered to n8n directly (the dispatch whose response 'was lost')", s, hooked, h)
    check("E: real n8n committed the lead", s == 201 and (hooked or {}).get("idempotency") == "created")
    s, js, h = confirm("A", f["Y"]["p"], f["Y"]["key"]); show("E. Y confirm retry with the same key", s, js, h)
    check("E: lost-response recovery -> 201 replay, same lead id", s == 201 and h.get("Idempotency-Outcome") == "replay" and js["id"] == hooked["id"])
    check("X + Y = exactly 2 new leads", leads_count() == before + 2)

def writer1():
    before = leads_count()
    s, p, h = prepare("A", {**DRAFT, "need": "Synthetic: writer failure"}, f"v1-wfail-{RUN}")
    key = f"lk-{RUN}-W"
    s, js, h = confirm("A", p, key); show("confirm while the private writer's INSERT fails", s, js, h)
    check("writer failure (n8n relays 5xx) -> 503, no false success", s == 503 and "id" not in js)
    check("writer failure: no lead, action stays confirmed", leads_count() == before and action_status(p["pending_action_id"]) == "confirmed")
    save(writer={"p": p, "key": key})

def writer2():
    w = state()["writer"]; before = leads_count()
    s, js, h = confirm("A", w["p"], w["key"]); show("retry after writer recovered", s, js, h)
    check("writer recovered: same-key retry -> 201 created, +1", s == 201 and leads_count() == before + 1)

def concurrent():
    for mode in ("same-key", "different-keys"):
        s, p, h = prepare("A", {**DRAFT, "need": f"Synthetic: concurrent {mode}"}, f"v1-conc-{mode}-{RUN}")
        keys = [f"lk-{RUN}-c-{mode}"] * 2 if mode == "same-key" else [f"lk-{RUN}-c1", f"lk-{RUN}-c2"]
        before, results, barrier = leads_count(), [None, None], threading.Barrier(2)
        def worker(i):
            barrier.wait(); results[i] = confirm("A", p, keys[i])
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        [t.start() for t in ts]; [t.join(90) for t in ts]
        summary = [(r[0], (r[1] or {}).get("id") or (r[1] or {}).get("code")) for r in results]
        print(f"  concurrent {mode}: {summary}")
        if mode == "same-key":
            check("concurrent same key: both 201, same lead", [r[0] for r in results] == [201, 201] and results[0][1]["id"] == results[1][1]["id"])
        else:
            check("concurrent different keys: one 201, one 409", sorted(r[0] for r in results) == [201, 409])
        check(f"concurrent {mode}: exactly one lead", leads_count() == before + 1)

def persist_after():
    m = state()["main"]
    row = sql(f"SELECT id FROM leads WHERE id = '{m['lead']['id']}';")
    check("main lead still in PostgreSQL after recreation", row == m["lead"]["id"])
    s, js, h = confirm("A", m["p"], m["key"]); show("main confirm retry after recreation", s, js, h)
    check("same confirmation retry -> same lead (replay)", s == 201 and js["id"] == m["lead"]["id"] and h.get("Idempotency-Outcome") == "replay")
    n8n_state()
    before = leads_count()
    s, p, h = prepare("A", {**DRAFT, "need": "Synthetic: after restart"}, f"v1-after-{RUN}")
    s, js, h = confirm("A", p, f"lk-{RUN}-after"); show("NEW journey after recreation", s, js, h)
    ok = s == 201 and h.get("Idempotency-Outcome") == "created"
    check("workflow + credential survived: new lead created through real n8n", ok and leads_count() == before + 1)
    if ok:
        check("new execution id exists in n8n", any(str(e.get("id")) == js["workflow_execution_id"] for e in executions()))

def logs():
    m = state()["main"]
    backend = open(os.path.join(WORK, "backend-before-restart.log")).read() + subprocess.run(
        ["docker", "compose", "logs", "--no-color", "backend"], capture_output=True, text=True).stdout
    n8nlog = subprocess.run(["docker", "compose", "logs", "--no-color", "n8n"], capture_output=True, text=True).stdout
    events = [json.loads(l[l.index('{"ts"'):]) for l in backend.splitlines() if '{"ts"' in l]
    conf = [e for e in events if e.get("action") == "lead_confirm" and e.get("request_id") == m["rid"]]
    write = [e for e in events if e.get("action") == "lead_write" and e.get("request_id") == m["rid"]]
    print("  correlated audit lines for the main journey:")
    for e in write + conf:
        print("   " + json.dumps(e))
    ok = len(conf) == 1 and len(write) == 1
    check("one lead_confirm + one lead_write share request_id " + m["rid"], ok)
    if ok:
        c, w = conf[0], write[0]
        fp = hashlib.sha256(m["key"].encode()).hexdigest()[:12]
        check("lead_write by service n8n-lead-writer, idempotency created", w.get("service") == "n8n-lead-writer" and w.get("idempotency") == "created")
        check("same pending_action_id on both sides", c["pending_action_id"] == w["pending_action_id"] == m["p"]["pending_action_id"])
        check("same idempotency identity (key fingerprint) on both sides", c.get("idempotency_key_fp") == w.get("idempotency_key_fp") == fp)
        check("same REAL n8n execution id on lead_write, lead_confirm, lead row",
              w["workflow_execution_id"] == c["workflow_execution_id"] == m["lead"]["workflow_execution_id"])
        check("same lead id on both sides", c["lead_id"] == w["lead_id"] == m["lead"]["id"])
    keys = [m["key"]] + [s_["key"] for s_ in state().get("fail", {}).values()]
    check("backend logs: no customer/service tokens, DB password, n8n key", not any(s in backend for s in SECRETS))
    check("backend logs: no raw Idempotency-Key", not any(k in backend for k in keys))
    check("backend logs: no lead contact/company/need text",
          not any(v in backend for v in (DRAFT["contact_email"], DRAFT["company_name"], DRAFT["need"])))
    check("n8n logs: no tokens/passwords/keys", not any(s in n8nlog for s in SECRETS))
    conn = n8n_db()
    ec = cols(conn, "execution_data")
    data = conn.execute(f"SELECT data FROM execution_data WHERE executionId = ?", (m["lead"]["workflow_execution_id"],)).fetchone()
    blob = str(data[0]) if data else ""
    print(f"  n8n execution_data columns: {ec}")
    print(f"  RETENTION (APP03B-02, LOW) for execution {m['lead']['workflow_execution_id']}: stored={bool(blob)}, "
          f"contains contact e-mail={DRAFT['contact_email'] in blob}, contains company={DRAFT['company_name'] in blob}, "
          f"contains raw Idempotency-Key={m['key'] in blob}, contains lead-writer token={SVC in blob}, "
          f"contains customer token={TOK['A'] in blob}")
    check("n8n execution data does NOT contain the lead-writer token", SVC not in blob)
    check("n8n execution data does NOT contain customer tokens", TOK["A"] not in blob and TOK["B"] not in blob)
    print(f"  total n8n executions for NexoLeadCreate01: {len(executions())}")

if __name__ == "__main__":
    {"n8n_state": n8n_state, "webhook_probe": webhook_probe, "journey": journey, "bypass": bypass,
     "idempotency": idempotency, "webhook_direct": webhook_direct, "fail1": fail1, "fail2": fail2,
     "writer1": writer1, "writer2": writer2, "concurrent": concurrent, "persist_after": persist_after,
     "logs": logs}[sys.argv[1]]()
    print(f"PHASE {sys.argv[1]}: {'PASS' if not FAILED else 'FAILURES: ' + '; '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)
PY
export NEXO_RUN_ID="$(date -u +%H%M%S)$RANDOM"
echo "driver ready (run id $NEXO_RUN_ID)"

sec "7. n8n CREDENTIAL (supported CLI: import:credentials)"
docker compose cp "$WORK/cred.json" n8n:/tmp/cred.json
run n8n_cli import:credentials --input=/tmp/cred.json
docker compose exec -T n8n rm -f /tmp/cred.json; rm -f "$WORK/cred.json"
check "temporary credential files deleted (host + container)" '[ ! -e "$WORK/cred.json" ] && ! docker compose exec -T n8n test -e /tmp/cred.json'
drv n8n_state

sec "8. WORKFLOW IMPORT + ACTIVATION (supported CLI)"
docker compose cp n8n/workflows/nexo-lead-create.json n8n:/tmp/nexo-lead-create.json
run n8n_cli import:workflow --input=/tmp/nexo-lead-create.json
if n8n_cli publish:workflow --help >/dev/null 2>&1; then
  ACT="publish:workflow --id=NexoLeadCreate01"
else
  ACT="update:workflow --id=NexoLeadCreate01 --active=true"
fi
echo "activation command used: n8n $ACT"
run n8n_cli $ACT
run docker compose restart n8n
run docker compose up -d --wait --wait-timeout 180 n8n
check "n8n healthy after activation restart" '[ "$(health n8n)" = healthy ]'
python3 "$WORK/driver.py" n8n_state expect-workflow || FAILED=1
drv webhook_probe
docker compose logs --no-color n8n 2>&1 | grep -iE 'activ|webhook|error|publish' | tail -8 | sed -E 's/^[^|]*\| //'

sec "9. REAL LEAD JOURNEY (prepare -> confirm -> REAL n8n -> /internal/leads -> PostgreSQL)"
drv journey

sec "10. BYPASS NEGATIVE TESTS"
drv bypass

sec "11. IDEMPOTENCY / RETRIES"
drv idempotency
drv webhook_direct

sec "12. FAILURES: n8n unavailable, lost response"
run docker compose stop n8n
drv fail1
run docker compose up -d --wait --wait-timeout 180 n8n
drv fail2

sec "13. FAILURE: private writer (DB INSERT fails inside /internal/leads; n8n relays 5xx)"
printf "CREATE FUNCTION v1_fail_lead() RETURNS trigger LANGUAGE plpgsql AS \$\$ BEGIN RAISE EXCEPTION 'simulated failure'; END; \$\$;\nCREATE TRIGGER v1_fail_lead AFTER INSERT ON leads FOR EACH ROW EXECUTE FUNCTION v1_fail_lead();\n" | psql_db
drv writer1
printf "DROP TRIGGER v1_fail_lead ON leads;\nDROP FUNCTION v1_fail_lead();\n" | psql_db
drv writer2
echo "NOTE: 'workflow success without a lead row' needs a modified workflow; covered only by local FakeN8n tests."

sec "14. CONCURRENT /leads/confirm (endpoint level)"
drv concurrent

sec "15. PERSISTENCE: recreate all containers, keep volumes"
docker compose logs --no-color backend > "$WORK/backend-before-restart.log" 2>&1
KFP_BEFORE="$(keyfp)"; echo "n8n encryption key fingerprint before: $KFP_BEFORE"
run docker compose down
check "volumes kept" 'docker volume inspect nexo_db_data nexo_n8n_data >/dev/null 2>&1'
run docker compose up -d --wait --wait-timeout 300
for s in db backend n8n; do check "$s healthy after recreation" '[ "$(health '"$s"')" = healthy ]'; done
echo "n8n encryption key fingerprint after:  $(keyfp)"
check "same N8N_ENCRYPTION_KEY (fingerprint)" '[ "$(keyfp)" = "$KFP_BEFORE" ]'
drv persist_after

sec "16. TRACEABILITY + SECRET HYGIENE"
drv logs
docker compose logs --no-color > "$WORK/compose.log" 2>&1
for var in POSTGRES_PASSWORD AUTH_TOKEN_CUSTOMER_A AUTH_TOKEN_CUSTOMER_B N8N_ENCRYPTION_KEY; do
  V="$(sed -n "s/^$var=//p" .env)"
  echo "$var: run log $(grep -cF -- "$V" "$LOG"), container logs $(grep -cF -- "$V" "$WORK/compose.log")"
  check "$var value not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'
  unset V
done
V="$(cat "$WORK/lead_writer.token")"
echo "lead-writer raw token: run log $(grep -cF -- "$V" "$LOG"), container logs $(grep -cF -- "$V" "$WORK/compose.log")"
check "lead-writer raw token not in logs" '[ "$(grep -cF -- "$V" "$LOG")" = 0 ] && [ "$(grep -cF -- "$V" "$WORK/compose.log")" = 0 ]'
unset V

sec "17. RESULT"
[ "$FAILED" = 0 ] && echo "APP-03BV1 VM VALIDATION: ALL CHECKS PASS" || { echo "APP-03BV1 VM VALIDATION: FAILURES (see CHECK FAIL)"; docker compose logs --no-color --tail 60 n8n backend | grep -viE 'bearer'; }
echo "SELECT 'leads=' || (SELECT count(*) FROM leads) || ' actions=' || (SELECT count(*) FROM pending_lead_actions) || ' consumed=' || (SELECT count(*) FROM pending_lead_actions WHERE status='consumed');" | psql_db

sec "18. CLEANUP"
run docker compose down -v
run docker image rm $IMAGES
run docker builder prune -f | tail -1
cd "$HOME"; case "$WORK" in "$HOME"/nexo-app03bv1) rm -rf -- "$WORK" ;; esac

sec "19. FINAL STATE"
run docker ps -a; run docker images; run docker volume ls; run docker network ls; run docker system df; run ss -tlnH
run test ! -e "$HOME/nexo-app03bv1" && echo "temporary directory removed (checkout, .env, token file, n8n DB copies, state)"
