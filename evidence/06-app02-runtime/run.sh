#!/usr/bin/env bash
# APP-02V1 — temporary runtime validation of APP-02/F1 on the VM. Owner-run, one SSH session:
#   ssh -p 9922 user@<VM> "$(cat run.sh)" < app02.bundle > raw/run.raw.log 2>&1
# DB password and both synthetic tokens are generated on the VM, written only to a chmod-600
# VM-local .env and never printed; the log is checked for them before .env is deleted.
# No sudo, no firewall/SSH changes, no LLM calls, nothing published beyond 127.0.0.1.
set -u
EXPECTED_SHA=1284f98197a3f0cbd21b1449397579807d8c4d58
WORK="$HOME/nexo-app02v1"
REPO="$WORK/repo"
LOG="$WORK/run.log"
DB_IMAGE=pgvector/pgvector:0.8.7-pg17-bookworm
BACKEND_IMAGE=nexo-backend:0.1.0
FAILED=0
sec()  { printf '\n===== %s =====\n' "$1"; }
run()  { printf '$ %s\n' "$*"; "$@" 2>&1 || { rc=$?; printf '(exit %s)\n' "$rc"; return $rc; }; }
check(){ if eval "$2"; then echo "CHECK PASS: $1"; else echo "CHECK FAIL: $1"; FAILED=1; fi; }
psql_db(){ docker compose exec -T db sh -c 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"'; }

sec "0. PRE-CHECKS"
if [ -e "$WORK" ]; then echo "ABORT: $WORK already exists"; exit 1; fi
if ss -tlnH | grep -q ':8000 '; then echo "ABORT: port 8000 already in use"; exit 1; fi
if docker compose ls -a --format json 2>/dev/null | grep -q '"Name":"nexo"'; then echo "ABORT: compose project 'nexo' exists"; exit 1; fi
if docker volume inspect nexo_db_data >/dev/null 2>&1; then echo "ABORT: volume nexo_db_data exists"; exit 1; fi
echo "pre-checks passed"
run date -u
run docker system df

mkdir -p "$WORK"
exec > >(tee "$LOG") 2>&1

sec "1. CHECKOUT EXACT COMMIT"
cat > "$WORK/app02.bundle"
run git clone -q "$WORK/app02.bundle" "$REPO"
git -C "$REPO" -c advice.detachedHead=false checkout -q --detach "$EXPECTED_SHA"
HEAD_SHA="$(git -C "$REPO" rev-parse HEAD)"; echo "VM checkout HEAD: $HEAD_SHA"
check "checked-out commit is $EXPECTED_SHA" '[ "$HEAD_SHA" = "$EXPECTED_SHA" ]'
check "working tree clean" '[ -z "$(git -C "$REPO" status --porcelain)" ]'
cd "$REPO" || exit 1

sec "2. VM-LOCAL .env (generated; values never printed)"
( umask 077
  gen() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  printf 'POSTGRES_DB=nexo\nPOSTGRES_USER=nexo\nPOSTGRES_PASSWORD=%s\nAUTH_TOKEN_CUSTOMER_A=%s\nAUTH_TOKEN_CUSTOMER_B=%s\nBACKEND_PORT=8000\n' \
    "$(gen)" "$(gen)" "$(gen)" > .env )
run stat -c '%A %U %n' .env
echo ".env variable names: $(cut -d= -f1 .env | tr '\n' ' ')"
check ".env ignored by git" 'git check-ignore -q .env'

sec "3. COMPOSE CONFIG + BUILD"
check "docker compose config valid" 'docker compose config --quiet'
echo "--- resolved backend/db environment keys (values redacted):"
docker compose config 2>&1 | sed -E 's/((POSTGRES_PASSWORD|AUTH_TOKEN_CUSTOMER_[AB]):).*/\1 <REDACTED>/' \
  | sed -n '/environment:/,/image:\|networks:\|ports:/p'
run docker compose --progress plain build backend 2>&1 | tail -8
check "backend image built" 'docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1'

sec "4. START (db healthy -> backend migrates, provisions, serves, healthy)"
run docker compose up -d --wait --wait-timeout 180
run docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
check "db healthy" '[ "$(docker inspect -f {{.State.Health.Status}} "$(docker compose ps -q db)")" = healthy ]'
check "backend healthy (HEALTHCHECK = /health/ready)" '[ "$(docker inspect -f {{.State.Health.Status}} "$(docker compose ps -q backend)")" = healthy ]'
echo "--- backend startup output (migrate + provision):"
docker compose logs --no-color backend 2>&1 | grep -E 'migrations applied|credentials provisioned|Uvicorn running' | sed -E 's/^[^|]*\| //'

sec "5. SCHEMA_MIGRATIONS vs CHECKED-OUT FILES"
echo "SELECT version || ' ' || checksum FROM schema_migrations ORDER BY version;" | psql_db > "$WORK/db_migrations.txt"
for f in src/backend/app/migrations/*.sql; do echo "$(basename "$f" .sql) $(sha256sum "$f" | cut -d' ' -f1)"; done > "$WORK/file_migrations.txt"
echo "--- database:"; cat "$WORK/db_migrations.txt"
check "schema_migrations == 0001..0004 with identical checksums" 'diff -q "$WORK/db_migrations.txt" "$WORK/file_migrations.txt" >/dev/null'
check "exactly 4 migrations applied" '[ "$(wc -l < "$WORK/db_migrations.txt")" = 4 ]'

sec "6. PORTS AND NETWORK"
run docker port "$(docker compose ps -q db)"; echo "(empty above = db has no published port)"
run docker port "$(docker compose ps -q backend)"
run ss -tlnH
check "no host listener on 5432" '! ss -tlnH | grep -q ":5432 "'
check "backend bound only to 127.0.0.1:8000" '[ "$(ss -tlnH | grep ":8000 " | awk "{print \$4}" | sort -u | tr "\n" " ")" = "127.0.0.1:8000 " ]'
check "public listeners only :9922" '[ -z "$(ss -tlnH | awk "{print \$4}" | grep -vE "^(127\.|\[::1\]|0\.0\.0\.0:9922$|\[::\]:9922$)")" ]'
run docker compose exec -T backend python -c "import socket; s=socket.create_connection(('db',5432),3); print('backend -> db:5432 over Docker DNS OK'); s.close()"

sec "7. API CHECKS (phase 1) — host python3 stdlib, 127.0.0.1 only"
cat > "$WORK/vm_checks.py" <<'PY'
"""APP-02V1 API checks. Reads tokens from .env into memory; never prints them.
NEXO_SQL_CMD / NEXO_LOGS_CMD (JSON lists) override the docker commands for a local dry run only."""
import json, os, subprocess, sys, threading, urllib.error, urllib.request, uuid

BASE = "http://127.0.0.1:8000"
SQL_CMD = json.loads(os.environ.get("NEXO_SQL_CMD", "null")) or [
    "docker", "compose", "exec", "-T", "db", "sh", "-c", 'psql -X -q -t -A -U "$POSTGRES_USER" -d "$POSTGRES_DB"']
LOGS_CMD = json.loads(os.environ.get("NEXO_LOGS_CMD", "null")) or ["docker", "compose", "logs", "--no-color", "backend"]
ENV = dict(l.split("=", 1) for l in open(".env").read().splitlines() if "=" in l)
TOK = {"A": ENV["AUTH_TOKEN_CUSTOMER_A"], "B": ENV["AUTH_TOKEN_CUSTOMER_B"]}
SECRETS = [TOK["A"], TOK["B"], ENV["POSTGRES_PASSWORD"]]
TICKET_A, TICKET_B = "a0000000-0000-4000-8000-000000000001", "b0000000-0000-4000-8000-000000000001"
FAILED = []
RUN = os.environ["NEXO_RUN_ID"]  # one ID for all phases, so the log phase finds phase-1 requests


def call(method, path, who=None, body=None, headers=None, raw_token=None):
    h = {"Content-Type": "application/json", "X-Request-ID": f"v1-{RUN}-{uuid.uuid4().hex[:8]}"}
    if who or raw_token:
        h["Authorization"] = "Bearer " + (raw_token if raw_token is not None else TOK[who])
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, raw, hdrs = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), e.headers
    text = raw.decode("utf-8", "replace")
    assert not any(s in text for s in SECRETS), "secret in response body"
    try:
        js = json.loads(text)
    except ValueError:
        js = None
    return status, js, hdrs, text


def sql(query, stderr=False):
    r = subprocess.run(SQL_CMD, input=query, capture_output=True, text=True)
    return r.stderr if stderr else r.stdout.strip()


def tickets():
    return int(sql("SELECT count(*) FROM tickets;"))


def check(name, ok, detail=""):
    print(("CHECK PASS: " if ok else "CHECK FAIL: ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILED.append(name)


def line(label, status, js, hdrs):
    shown = {}
    if isinstance(js, dict):
        for k in ("customer_id", "id", "pending_action_id", "status", "priority", "code", "detail", "ticket_id", "schema_version"):
            if k in js:
                shown[k] = js[k]
    outcome = hdrs.get("Idempotency-Outcome") if hdrs else None
    print(f"  {label}: HTTP {status}" + (f" Idempotency-Outcome={outcome}" if outcome else "") + f" {json.dumps(shown)}")


DRAFT = {"contact_name": "Ana (Taller Norte, synthetic)",
         "subject": "Synthetic: no internet in the office",
         "description": "Synthetic: no internet for twenty minutes, affects the whole office.",
         "priority": "normal"}


def prepare(who, draft, conv):
    return call("POST", "/tickets/prepare", who, draft, {"X-Conversation-ID": conv})


def confirm(who, action, key, conv=None):
    headers = {"Idempotency-Key": key} if key is not None else {}
    if conv:
        headers["X-Conversation-ID"] = conv
    return call("POST", "/tickets/confirm", who,
                {"pending_action_id": action["pending_action_id"], "payload_hash": action["payload_hash"]}, headers)


def phase1():
    print("\n--- 7.1 health / readiness")
    s, js, h, _ = call("GET", "/health"); line("GET /health", s, js, h)
    check("/health 200 {status: ok}", s == 200 and js == {"status": "ok"})
    s, js, h, _ = call("GET", "/health/ready"); line("GET /health/ready", s, js, h)
    check("/health/ready 200 at schema 0004", s == 200 and js.get("schema_version") == "0004_one_pending_action_per_group")

    print("\n--- 7.2 authorization matrix")
    for who, cid in (("A", "CUSTOMER_A"), ("B", "CUSTOMER_B")):
        s, js, h, _ = call("GET", "/me", who); line(f"{cid} GET /me", s, js, h)
        check(f"{cid} /me -> {cid}", s == 200 and js["customer_id"] == cid)
    for who, tid, exp in (("A", TICKET_A, 200), ("B", TICKET_B, 200), ("A", TICKET_B, 404), ("B", TICKET_A, 404)):
        s, js, h, text = call("GET", f"/tickets/{tid}", who); line(f"CUSTOMER_{who} GET ticket {tid[:8]}", s, js, h)
        check(f"CUSTOMER_{who} reads {tid[:8]} -> {exp}", s == exp)
        if exp == 404:
            check(f"404 body generic, no leak", js == {"detail": "Ticket not found"} and "CUSTOMER" not in text)
    s, js, h, _ = call("GET", "/me", raw_token="invalid-" + "x" * 40); line("invalid token GET /me", s, js, h)
    check("invalid token -> 401", s == 401)
    s, js, h, _ = call("GET", f"/tickets/{TICKET_A}"); line("no token GET ticket A", s, js, h)
    check("missing token -> 401", s == 401)

    print("\n--- 7.3 prepare / confirm (CUSTOMER_A, priority normal)")
    conv = f"v1-basic-{RUN}"
    before = tickets()
    s, prep, h, _ = prepare("A", DRAFT, conv); line("prepare", s, prep, h)
    check("prepare 201 with pending action, summary and hash",
          s == 201 and prep["status"] == "pending" and len(prep["payload_hash"]) == 64
          and prep["summary"]["customer_id"] == "CUSTOMER_A" and prep["confirmation_required"] is True)
    check("prepare creates NO ticket", tickets() == before, f"{before} -> {tickets()}")
    k1 = f"v1-k1-{RUN}"
    s, created, h, _ = confirm("A", prep, k1, conv); line("confirm K1", s, created, h)
    check("confirm 201 created with real ticket id", s == 201 and h.get("Idempotency-Outcome") == "created" and "id" in created)
    check("exactly one ticket created", tickets() == before + 1)
    row = sql(f"SELECT customer_id || '|' || source_action_id || '|' || priority FROM tickets WHERE id = '{created['id']}';")
    print(f"  DB row: {row}")
    check("ticket persisted, owner CUSTOMER_A, linked to action", row == f"CUSTOMER_A|{prep['pending_action_id']}|normal")
    s, js, h, _ = call("GET", f"/tickets/{created['id']}", "A"); line("A GET new ticket", s, js, h)
    check("owner reads new ticket", s == 200 and js["id"] == created["id"])
    s, js, h, _ = call("GET", f"/tickets/{created['id']}", "B"); line("B GET new ticket", s, js, h)
    check("other customer gets 404", s == 404)

    print("\n--- 7.4 idempotency")
    before = tickets()
    s, replay, h, _ = confirm("A", prep, k1, conv); line("confirm K1 again", s, replay, h)
    check("A: same key + same request -> same ticket, replay", s == 201 and replay == created and h.get("Idempotency-Outcome") == "replay")
    check("A: ticket count unchanged", tickets() == before)
    s, other, h, _ = prepare("A", {**DRAFT, "subject": "Synthetic: another request"}, f"v1-other-{RUN}"); line("prepare other action", s, other, h)
    s, js, h, _ = confirm("A", other, k1); line("confirm OTHER action with K1", s, js, h)
    check("B: same key + different action -> 409 conflict", s == 409 and js["code"] == "idempotency_key_conflict" and h.get("Idempotency-Outcome") == "conflict")
    s, js, h, _ = confirm("A", {"pending_action_id": prep["pending_action_id"], "payload_hash": other["payload_hash"]}, k1)
    line("confirm same action, different hash, K1", s, js, h)
    check("B2: same key + different hash -> 409 conflict", s == 409 and js["code"] == "idempotency_key_conflict")
    s, js, h, _ = confirm("A", prep, f"v1-k2-{RUN}"); line("confirm consumed action with new key K2", s, js, h)
    check("C: consumed + new key -> 409 confirmation_already_used + same ticket_id",
          s == 409 and js["code"] == "confirmation_already_used" and js["ticket_id"] == created["id"])
    s, js, h, _ = confirm("A", other, None); line("confirm without Idempotency-Key", s, js, h)
    check("D: missing key -> 400", s == 400)
    s, js, h, _ = confirm("A", other, "bad key/with space"); line("confirm with invalid key", s, js, h)
    check("D: invalid key -> 400", s == 400)
    check("no ticket from B/C/D", tickets() == before)
    check("other action still pending", sql(f"SELECT status FROM pending_ticket_actions WHERE id='{other['pending_action_id']}';") == "pending")

    print("\n--- 7.5 confirmation invalidation (official flow: whole office down -> critical)")
    conv = f"v1-change-{RUN}"
    before = tickets()
    s, a1, h, _ = prepare("A", DRAFT, conv); line("prepare A (priority normal)", s, a1, h)
    s, b1, h, _ = prepare("A", {**DRAFT, "priority": "critical"}, conv); line("prepare B (priority critical)", s, b1, h)
    st = sql(f"SELECT status FROM pending_ticket_actions WHERE id='{a1['pending_action_id']}';")
    check("A superseded after changed re-prepare", st == "superseded", st)
    s, js, h, _ = confirm("A", a1, f"v1-ka-{RUN}", conv); line("confirm superseded A", s, js, h)
    check("confirm A -> 409 confirmation_invalid", s == 409 and js["code"] == "confirmation_invalid")
    s, js, h, _ = confirm("A", b1, f"v1-kb-{RUN}", conv); line("confirm B", s, js, h)
    check("confirm B -> 201 with priority critical", s == 201 and js["priority"] == "critical")
    check("exactly one new ticket", tickets() == before + 1)

    print("\n--- 7.6 concurrent prepare (same customer + same X-Conversation-ID), 3 rounds x 8 threads")
    for rnd in range(3):
        conv = f"v1-race-{RUN}-{rnd}"
        results, barrier = [None] * 8, threading.Barrier(8)

        def worker(i):
            barrier.wait()
            results[i] = prepare("A", {**DRAFT, "subject": f"Synthetic: race {i}"}, conv)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in threads]; [t.join(60) for t in threads]
        ok = all(r is not None and r[0] == 201 for r in results)
        dist = sql(f"SELECT string_agg(status || '=' || n, ',' ORDER BY status) FROM"
                   f" (SELECT status, count(*) n FROM pending_ticket_actions WHERE conversation_id='{conv}' GROUP BY status) s;")
        print(f"  round {rnd}: all 8 prepares HTTP 201: {ok}; DB statuses: {dist}")
        check(f"round {rnd}: exactly 1 pending, 7 superseded", ok and dist == "pending=1,superseded=7", dist)
        pending = sql(f"SELECT id FROM pending_ticket_actions WHERE conversation_id='{conv}' AND status='pending';")
        before = tickets()
        codes = []
        for r in results:
            action = r[1]
            s, js, h, _ = confirm("A", action, f"v1-race-{RUN}-{rnd}-{action['pending_action_id'][:8]}", conv)
            codes.append((action["pending_action_id"] == pending, s))
        check(f"round {rnd}: only the pending action confirms (201), the 7 others 409",
              sorted(codes) == [(False, 409)] * 7 + [(True, 201)], str(sorted(codes)))
        check(f"round {rnd}: exactly one ticket", tickets() == before + 1)

    print("\n--- 7.7 cross-customer confirmation")
    before = tickets()
    s, bact, h, _ = prepare("B", {**DRAFT, "contact_name": "Synthetic B contact"}, f"v1-cross-{RUN}"); line("B prepare", s, bact, h)
    s, js, h, text = confirm("A", bact, f"v1-cross-a-{RUN}"); line("A confirms B's action", s, js, h)
    s2, js2, _, _ = confirm("A", {"pending_action_id": str(uuid.uuid4()), "payload_hash": bact["payload_hash"]}, f"v1-cross-u-{RUN}")
    check("A on B's action == nonexistent (404, identical body)", s == s2 == 404 and js == js2 == {"detail": "Pending action not found"})
    check("no leak of B or action data", all(x not in text for x in ("CUSTOMER_B", "Synthetic B contact", bact["pending_action_id"])))
    check("no ticket created", tickets() == before)
    s, js, h, _ = confirm("B", bact, f"v1-cross-b-{RUN}"); line("B confirms own action", s, js, h)
    check("B confirms own action -> 201 owner CUSTOMER_B", s == 201 and js["customer_id"] == "CUSTOMER_B")

    print("\n--- 7.8 priority policy")
    for p in ("normal", "critical"):
        s, js, h, _ = prepare("A", {**DRAFT, "priority": p}, f"v1-prio-{p}-{RUN}"); line(f"prepare priority={p}", s, js, h)
        check(f"priority {p} accepted", s == 201)
    actions_before = sql("SELECT count(*) FROM pending_ticket_actions;")
    for p in ("low", "medium", "high", "urgent"):
        s, js, h, _ = prepare("A", {**DRAFT, "priority": p}, f"v1-prio-{p}-{RUN}"); line(f"prepare priority={p}", s, js, h)
        check(f"priority {p} rejected (422)", s == 422)
    check("no action created for rejected priorities", sql("SELECT count(*) FROM pending_ticket_actions;") == actions_before)
    err = sql("UPDATE tickets SET priority='high' WHERE id='a0000000-0000-4000-8000-000000000001';", stderr=True)
    print("  DB-level UPDATE priority='high': " + (err.strip().splitlines() or ["(no error)"])[0])
    check("DB CHECK rejects legacy priority", "tickets_priority_check" in err)

    print("\n--- 7.9 persistence fixture: one confirmed ticket")
    s, pa, h, _ = prepare("A", {**DRAFT, "subject": "Synthetic: persistence check"}, f"v1-persist-{RUN}")
    key = f"v1-persist-{RUN}"
    s, pt, h, _ = confirm("A", pa, key); line("persistence ticket", s, pt, h)
    check("persistence ticket created", s == 201)
    json.dump({"ticket": pt, "action": pa, "key": key}, open("persist.json", "w"))


def phase2():
    print("\n--- 9.1 after container recreation")
    saved = json.load(open("persist.json"))
    s, js, h, _ = call("GET", "/health/ready"); line("GET /health/ready", s, js, h)
    check("/health/ready 200 after recreate", s == 200)
    s, js, h, _ = call("GET", f"/tickets/{saved['ticket']['id']}", "A"); line("A GET persisted ticket", s, js, h)
    check("same ticket queryable by owner after recreate", s == 200 and js == saved["ticket"])
    s, js, h, _ = call("GET", f"/tickets/{saved['ticket']['id']}", "B")
    check("still 404 for other customer", s == 404)
    s, js, h, _ = confirm("A", saved["action"], saved["key"]); line("replay persisted key", s, js, h)
    check("idempotency record survived restart (replay, same ticket)", s == 201 and h.get("Idempotency-Outcome") == "replay" and js == saved["ticket"])


def logs_check():
    print("\n--- 10. traceability (backend audit lines for this run)")
    logs = subprocess.run(LOGS_CMD, capture_output=True, text=True).stdout
    events = []
    for l in logs.splitlines():
        if '{"ts"' in l:
            events.append(json.loads(l[l.index('{"ts"'):]))
    mine = [e for e in events if str(e.get("request_id", "")).startswith(f"v1-{RUN}")]
    for e in mine:
        if e.get("action") in ("ticket_prepare", "ticket_confirm") and (e.get("conversation_id") or "").startswith(("v1-basic", "v1-other")):
            print("  " + json.dumps(e))
    outcomes = {e.get("idempotency") for e in mine if e.get("action") == "ticket_confirm"}
    check("audit has created/replay/conflict outcomes", {"created", "replay", "conflict"} <= outcomes, str(outcomes))
    check("every audit line has request_id + status + duration_ms",
          all({"request_id", "status", "duration_ms"} <= e.keys() for e in mine) and len(mine) > 50, f"{len(mine)} lines")
    check("ticket_id only on successful confirm/replay or conflict lookups",
          all(e.get("status") in (201, 409) for e in mine if e.get("action") == "ticket_confirm" and "ticket_id" in e))
    check("no tokens / DB password in backend logs", not any(s in logs for s in SECRETS))
    check("no 'Bearer' / authorization header in logs", "Bearer " not in logs and "authorization" not in logs.lower())
    check("no ticket description text in logs", DRAFT["description"] not in logs)


if __name__ == "__main__":
    {"phase1": phase1, "phase2": phase2, "logs": logs_check}[sys.argv[1]]()
    print(f"\nPHASE {sys.argv[1]}: {'ALL CHECKS PASS' if not FAILED else 'FAILURES: ' + '; '.join(FAILED)}")
    sys.exit(1 if FAILED else 0)
PY
export NEXO_RUN_ID="$(date -u +%H%M%S)$RANDOM"
python3 "$WORK/vm_checks.py" phase1 || FAILED=1

sec "8. PERSISTENCE: recreate containers, keep volume"
# Run 1 lesson: container logs disappear with the container on `down`, so save the
# phase-1 backend logs first; the log phase reads this file plus the new container's logs.
docker compose logs --no-color backend > "$WORK/backend-before-restart.log" 2>&1
echo "saved phase-1 backend logs: $(grep -c '"ts"' "$WORK/backend-before-restart.log") audit lines"
DB_CID_BEFORE="$(docker compose ps -q db)"; VOL_CREATED="$(docker volume inspect nexo_db_data -f '{{.CreatedAt}}')"
run docker compose down
check "no nexo containers after down" '[ -z "$(docker compose ps -aq)" ]'
check "volume nexo_db_data kept" 'docker volume inspect nexo_db_data >/dev/null 2>&1'
run docker compose up -d --wait --wait-timeout 180
check "db recreated (new container id)" '[ "$(docker compose ps -q db)" != "$DB_CID_BEFORE" ]'
check "same volume instance" '[ "$(docker volume inspect nexo_db_data -f {{.CreatedAt}})" = "$VOL_CREATED" ]'
echo "--- backend startup output after recreate:"
docker compose logs --no-color backend 2>&1 | grep -E 'migrations applied|credentials provisioned' | sed -E 's/^[^|]*\| //'

sec "9. API CHECKS (phase 2: after recreate)"
python3 "$WORK/vm_checks.py" phase2 || FAILED=1

sec "10. TRACEABILITY / LOG HYGIENE (backend logs from before AND after the restart)"
export NEXO_LOGS_CMD="[\"sh\", \"-c\", \"cat $WORK/backend-before-restart.log; docker compose logs --no-color backend\"]"
python3 "$WORK/vm_checks.py" logs || FAILED=1

sec "11. RESULT"
if [ "$FAILED" = 0 ]; then echo "APP-02V1 RUNTIME: ALL CHECKS PASS"; else echo "APP-02V1 RUNTIME: FAILURES (see CHECK FAIL)"; docker compose logs --no-color --tail 40; fi
echo "SELECT 'tickets=' || (SELECT count(*) FROM tickets) || ' pending_actions=' || (SELECT count(*) FROM pending_ticket_actions WHERE status='pending') || ' idempotency_keys=' || (SELECT count(*) FROM idempotency_keys);" | psql_db

sec "12. CLEANUP"
run docker compose down -v
run docker image rm "$BACKEND_IMAGE" "$DB_IMAGE"
run docker builder prune -f | tail -1

sec "13. SECRET-IN-LOG CHECK (values never printed)"
for var in POSTGRES_PASSWORD AUTH_TOKEN_CUSTOMER_A AUTH_TOKEN_CUSTOMER_B; do
  V="$(sed -n "s/^$var=//p" "$REPO/.env")"; echo "occurrences of $var value in run log: $(grep -cF -- "$V" "$LOG")"; unset V
done
cd "$HOME"
case "$WORK" in "$HOME"/nexo-app02v1) rm -rf -- "$WORK" ;; *) echo "refusing to remove unexpected path";; esac

sec "14. FINAL STATE"
run docker ps -a
run docker images
run docker volume ls
run docker network ls
run docker system df
run ss -tlnH
run test ! -e "$HOME/nexo-app02v1" && echo "temporary directory removed (checkout, .env, persist.json, logs)"
